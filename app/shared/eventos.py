"""Bus de eventos entre modulos, respaldado en la tabla shared.eventos (seccion 3).

- `publicar` inserta el evento en la MISMA sesion (y transaccion) que el cambio que lo
  origina. Si esa transaccion se revierte, el evento no existe.
- `procesar_pendientes` entrega cada evento a cada suscriptor en su propia transaccion:
  el efecto del manejador y la marca en `procesado_por` se guardan juntos. Si el
  manejador falla, no se marca y se reintenta en la siguiente pasada.
- La app llama a `procesar_pendientes` al arrancar, despues de publicar y cada minuto.

Entrega "al menos una vez": los manejadores deben ser idempotentes.
"""

import logging
import uuid
from collections import defaultdict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, ClassVar, Protocol

from sqlalchemy import DateTime, String, func, select, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.db import Base

log = logging.getLogger(__name__)


class EventoFila(Base):
    __tablename__ = "eventos"
    __table_args__ = {"schema": "shared"}

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tipo: Mapped[str] = mapped_column(String(100), index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB)
    creado_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    # {"recepcion": "2026-11-17T10:00:00+00:00", ...}
    procesado_por: Mapped[dict[str, str]] = mapped_column(
        JSONB, default=dict, server_default=text("'{}'::jsonb")
    )


class Evento(Protocol):
    TIPO: ClassVar[str]

    def a_payload(self) -> dict[str, Any]: ...

    @classmethod
    def desde_payload(cls, payload: dict[str, Any]) -> "Evento": ...


@dataclass(frozen=True)
class AutorizacionRevocada:
    """Lo publica Autorizacion; lo escuchan Recepcion y Revision."""

    installation_id: uuid.UUID
    TIPO: ClassVar[str] = "AutorizacionRevocada"

    def a_payload(self) -> dict[str, Any]:
        return {"installation_id": str(self.installation_id)}

    @classmethod
    def desde_payload(cls, payload: dict[str, Any]) -> "AutorizacionRevocada":
        return cls(installation_id=uuid.UUID(payload["installation_id"]))


TIPOS_DE_EVENTO: dict[str, type[Evento]] = {AutorizacionRevocada.TIPO: AutorizacionRevocada}

Manejador = Callable[[AsyncSession, Any], Awaitable[None]]


class BusEventos:
    def __init__(self) -> None:
        self._suscripciones: dict[str, dict[str, Manejador]] = defaultdict(dict)

    def suscribir(self, tipo_evento: type[Evento], modulo: str, manejador: Manejador) -> None:
        if modulo in self._suscripciones[tipo_evento.TIPO]:
            raise ValueError(f"{modulo} ya esta suscrito a {tipo_evento.TIPO}")
        self._suscripciones[tipo_evento.TIPO][modulo] = manejador

    def limpiar(self) -> None:
        """Solo para pruebas."""
        self._suscripciones.clear()

    async def publicar(self, sesion: AsyncSession, evento: Evento) -> uuid.UUID:
        """Guarda el evento sin hacer commit: lo confirma la transaccion de quien publica."""
        fila = EventoFila(tipo=evento.TIPO, payload=evento.a_payload())
        sesion.add(fila)
        await sesion.flush()
        return fila.id

    async def procesar_pendientes(self, sesionador: async_sessionmaker[AsyncSession]) -> int:
        """Entrega los eventos pendientes. Devuelve cuantas entregas se completaron."""
        entregados = 0
        for tipo, suscriptores in list(self._suscripciones.items()):
            clase = TIPOS_DE_EVENTO[tipo]
            for modulo, manejador in list(suscriptores.items()):
                while await self._entregar_uno(sesionador, tipo, clase, modulo, manejador):
                    entregados += 1
        return entregados

    async def _entregar_uno(
        self,
        sesionador: async_sessionmaker[AsyncSession],
        tipo: str,
        clase: type[Evento],
        modulo: str,
        manejador: Manejador,
    ) -> bool:
        try:
            async with sesionador() as sesion, sesion.begin():
                consulta = (
                    select(EventoFila)
                    .where(EventoFila.tipo == tipo, ~EventoFila.procesado_por.has_key(modulo))
                    .order_by(EventoFila.creado_en)
                    .limit(1)
                    .with_for_update(skip_locked=True)
                )
                fila = (await sesion.execute(consulta)).scalar_one_or_none()
                if fila is None:
                    return False
                await manejador(sesion, clase.desde_payload(fila.payload))
                fila.procesado_por = {
                    **fila.procesado_por,
                    modulo: datetime.now(UTC).isoformat(),
                }
            return True
        except Exception:
            # Sin payload en el log: puede tener el installation_id.
            log.exception("Fallo el manejador de %s en %s; se reintentara", tipo, modulo)
            return False


bus = BusEventos()
