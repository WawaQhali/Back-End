"""Bus de eventos respaldado en shared.eventos (seccion 3). Necesita PostgreSQL."""

import uuid

import pytest
from sqlalchemy import func, select

from app.shared.eventos import AutorizacionRevocada, BusEventos, EventoFila

pytestmark = pytest.mark.bd


async def _contar_eventos(sesionador) -> int:  # noqa: ANN001
    async with sesionador() as s:
        return (await s.execute(select(func.count()).select_from(EventoFila))).scalar_one()


async def test_evento_publicado_y_confirmado_llega_a_cada_suscriptor(sesionador) -> None:  # noqa: ANN001
    bus = BusEventos()
    recibidos: dict[str, list[uuid.UUID]] = {"recepcion": [], "revision": []}

    for modulo in recibidos:

        async def manejador(_sesion, evento, modulo=modulo) -> None:  # noqa: ANN001
            recibidos[modulo].append(evento.installation_id)

        bus.suscribir(AutorizacionRevocada, modulo, manejador)

    instalacion = uuid.uuid4()
    async with sesionador() as s, s.begin():
        await bus.publicar(s, AutorizacionRevocada(instalacion))

    assert await bus.procesar_pendientes(sesionador) == 2
    assert recibidos == {"recepcion": [instalacion], "revision": [instalacion]}

    # Ya procesado: una segunda pasada (p. ej. al reiniciar) no lo repite.
    assert await bus.procesar_pendientes(sesionador) == 0

    async with sesionador() as s:
        fila = (await s.execute(select(EventoFila))).scalar_one()
    assert set(fila.procesado_por) == {"recepcion", "revision"}


async def test_si_la_transaccion_se_revierte_el_evento_no_existe(sesionador) -> None:  # noqa: ANN001
    bus = BusEventos()
    async with sesionador() as s:
        await s.begin()
        await bus.publicar(s, AutorizacionRevocada(uuid.uuid4()))
        await s.rollback()
    assert await _contar_eventos(sesionador) == 0


async def test_evento_pendiente_se_procesa_al_arrancar(sesionador) -> None:  # noqa: ANN001
    """Simula un reinicio: se publica sin suscriptores y otro bus lo procesa despues."""
    instalacion = uuid.uuid4()
    async with sesionador() as s, s.begin():
        await BusEventos().publicar(s, AutorizacionRevocada(instalacion))

    bus_tras_reinicio = BusEventos()
    recibidos: list[uuid.UUID] = []

    async def manejador(_sesion, evento) -> None:  # noqa: ANN001
        recibidos.append(evento.installation_id)

    bus_tras_reinicio.suscribir(AutorizacionRevocada, "recepcion", manejador)
    assert await bus_tras_reinicio.procesar_pendientes(sesionador) == 1
    assert recibidos == [instalacion]


async def test_si_el_manejador_falla_no_se_marca_y_se_reintenta(sesionador) -> None:  # noqa: ANN001
    bus = BusEventos()
    intentos = 0

    async def manejador(_sesion, _evento) -> None:  # noqa: ANN001
        nonlocal intentos
        intentos += 1
        if intentos == 1:
            raise RuntimeError("Blob no disponible")

    bus.suscribir(AutorizacionRevocada, "recepcion", manejador)
    async with sesionador() as s, s.begin():
        await bus.publicar(s, AutorizacionRevocada(uuid.uuid4()))

    assert await bus.procesar_pendientes(sesionador) == 0
    async with sesionador() as s:
        assert (await s.execute(select(EventoFila))).scalar_one().procesado_por == {}

    assert await bus.procesar_pendientes(sesionador) == 1
    assert intentos == 2


async def test_cambios_del_manejador_y_marca_van_en_la_misma_transaccion(sesionador) -> None:  # noqa: ANN001
    """Si el manejador escribe y luego falla, se revierte todo, incluida la marca."""
    bus = BusEventos()

    async def manejador(sesion, _evento) -> None:  # noqa: ANN001
        await bus.publicar(sesion, AutorizacionRevocada(uuid.uuid4()))  # una escritura
        raise RuntimeError("falla despues de escribir")

    bus.suscribir(AutorizacionRevocada, "revision", manejador)
    async with sesionador() as s, s.begin():
        await bus.publicar(s, AutorizacionRevocada(uuid.uuid4()))

    await bus.procesar_pendientes(sesionador)
    assert await _contar_eventos(sesionador) == 1


def test_no_se_puede_suscribir_dos_veces_el_mismo_modulo() -> None:
    bus = BusEventos()

    async def manejador(_s, _e) -> None:  # noqa: ANN001
        return None

    bus.suscribir(AutorizacionRevocada, "recepcion", manejador)
    with pytest.raises(ValueError, match="ya esta suscrito"):
        bus.suscribir(AutorizacionRevocada, "recepcion", manejador)
