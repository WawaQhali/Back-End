"""Logica de negocio del modulo revision."""

import logging
import uuid
from datetime import UTC, datetime

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.revision import repositorio
from app.modules.revision.esquemas import (
    DetalleImagen,
    EstadoImagen,
    EtiquetaFinal,
    EtiquetaParaEntrenar,
    EtiquetaPreliminar,
    ImagenVerificada,
    PaginaPendientes,
    Registrada,
    ResumenImagen,
    SolicitudEtiqueta,
    Token,
)
from app.modules.revision.tablas import Imagen, Usuario
from app.shared.auth import (
    Rol,
    Sesion,
    emitir_token,
    hashear_contrasena,
    verificar_contrasena,
)
from app.shared.errores import ErrorApi
from app.shared.eventos import AutorizacionRevocada
from app.shared.logs import hash_instalacion
from app.shared.proveedores import ProveedorBlob, obtener_proveedor_blob

log = logging.getLogger(__name__)

# Se verifica contra este hash cuando el usuario no existe, para que la respuesta
# tarde lo mismo y no revele que usuarios existen.
_HASH_DE_RELLENO = hashear_contrasena("usuario-inexistente-relleno")

NO_ENCONTRADA = ErrorApi(404, "imagen_inexistente", "No existe esa imagen.")


# --- Cuentas -------------------------------------------------------------------------


async def login(sesion: AsyncSession, usuario: str, contrasena: str) -> Token:
    fila = await repositorio.usuario_por_nombre(sesion, usuario)
    hash_guardado = fila.hash_contrasena if fila else _HASH_DE_RELLENO
    valida = verificar_contrasena(hash_guardado, contrasena)
    if fila is None or not valida or not fila.activo:
        raise ErrorApi(401, "credenciales_invalidas", "Usuario o contrasena incorrectos.")
    rol = Rol(fila.rol)
    return Token(access_token=emitir_token(str(fila.id), rol), rol=rol)


# Cuenta fija del medico, pedida por el equipo: se crea sola al arrancar.
# ⚠️ Rompe la regla de la seccion 9 (secretos fuera del codigo). Ver docs/decisiones.md D25.
CUENTA_FIJA_USUARIO = "medico"
CUENTA_FIJA_CONTRASENA = "WawaQhali-Medico-2026"  # noqa: S105


async def asegurar_cuenta_fija(sesionador: async_sessionmaker[AsyncSession]) -> None:
    """Crea la cuenta fija si no existe; si existe, la deja activa, con rol medico y con
    la contrasena del codigo. Idempotente: se llama en cada arranque."""
    async with sesionador() as sesion, sesion.begin():
        fila = await repositorio.usuario_por_nombre(sesion, CUENTA_FIJA_USUARIO)
        if fila is None:
            sesion.add(
                Usuario(
                    usuario=CUENTA_FIJA_USUARIO,
                    hash_contrasena=hashear_contrasena(CUENTA_FIJA_CONTRASENA),
                    rol=Rol.medico.value,
                    activo=True,
                )
            )
            return
        if not verificar_contrasena(fila.hash_contrasena, CUENTA_FIJA_CONTRASENA):
            fila.hash_contrasena = hashear_contrasena(CUENTA_FIJA_CONTRASENA)
        fila.rol = Rol.medico.value
        fila.activo = True


async def crear_usuario(sesion: AsyncSession, usuario: str, contrasena: str, rol: Rol) -> uuid.UUID:
    fila = Usuario(usuario=usuario, hash_contrasena=hashear_contrasena(contrasena), rol=rol.value)
    sesion.add(fila)
    try:
        await sesion.commit()
    except IntegrityError as error:
        await sesion.rollback()
        raise ValueError(f"El usuario {usuario} ya existe") from error
    return fila.id


# --- App web del medico ------------------------------------------------------------------


async def pendientes(sesion: AsyncSession, pagina: int, tamano: int) -> PaginaPendientes:
    filas, total = await repositorio.pendientes(sesion, pagina, tamano)
    return PaginaPendientes(
        items=[
            ResumenImagen(
                id=f.id,
                recibida_en=f.creado_en,
                clase=f.etiqueta_preliminar["clase"],
                confianza=f.etiqueta_preliminar["confianza"],
            )
            for f in filas
        ],
        total=total,
        pagina=pagina,
        tamano=tamano,
    )


async def _visible(sesion: AsyncSession, id_imagen: uuid.UUID, bloquear: bool = False) -> Imagen:
    fila = await repositorio.imagen(sesion, id_imagen, bloquear=bloquear)
    if fila is None or fila.estado == EstadoImagen.eliminada:
        raise NO_ENCONTRADA
    return fila


async def detalle(sesion: AsyncSession, id_imagen: uuid.UUID, blob: ProveedorBlob) -> DetalleImagen:
    fila = await _visible(sesion, id_imagen)
    return DetalleImagen(
        id=fila.id,
        estado=EstadoImagen(fila.estado),
        recibida_en=fila.creado_en,
        etiqueta_preliminar=EtiquetaPreliminar.model_validate(fila.etiqueta_preliminar),
        etiqueta_final=EtiquetaFinal(fila.etiqueta_final) if fila.etiqueta_final else None,
        comentario=fila.comentario,
        url=await blob.enlace_lectura(fila.blob_path),
    )


async def etiquetar(
    sesion: AsyncSession, id_imagen: uuid.UUID, solicitud: SolicitudEtiqueta, medico: Sesion
) -> None:
    """Guarda la etiqueta final. Se puede corregir mientras no se use en un modelo."""
    fila = await _visible(sesion, id_imagen, bloquear=True)
    if fila.usada_en_modelo:
        raise ErrorApi(409, "ya_usada", "La imagen ya se uso en un modelo; no se puede cambiar.")
    fila.etiqueta_final = solicitud.etiqueta.value
    fila.comentario = solicitud.comentario
    fila.revisada_por = medico.usuario_id
    fila.revisada_en = datetime.now(UTC)
    fila.estado = EstadoImagen.revisada
    await sesion.commit()


async def eliminar(sesion: AsyncSession, id_imagen: uuid.UUID, blob: ProveedorBlob) -> None:
    """Para imagenes con datos identificables (p. ej. un rostro). Borra el blob."""
    fila = await _visible(sesion, id_imagen, bloquear=True)
    await blob.borrar(fila.blob_path)
    fila.estado = EstadoImagen.eliminada
    fila.etiqueta_preliminar = {**fila.etiqueta_preliminar, "respuestas": {}}
    await sesion.commit()


# --- Servicio de reentrenamiento --------------------------------------------------------


async def registrar_verificada(sesion: AsyncSession, datos: ImagenVerificada) -> Registrada:
    fila = Imagen(
        paquete_id=datos.paquete_id,
        installation_id=datos.installation_id,
        blob_path=datos.blob_path,
        etiqueta_preliminar=datos.etiqueta_preliminar.model_dump(),
        estado=EstadoImagen.pendiente,
    )
    sesion.add(fila)
    try:
        await sesion.commit()
    except IntegrityError as error:
        await sesion.rollback()
        raise ErrorApi(409, "paquete_ya_registrado", "Ese paquete ya fue registrado.") from error
    return Registrada(id=fila.id)


async def etiquetas_desde(sesion: AsyncSession, desde: datetime) -> list[EtiquetaParaEntrenar]:
    filas = await repositorio.etiquetadas_desde(sesion, desde)
    return [
        EtiquetaParaEntrenar(
            id=f.id,
            paquete_id=f.paquete_id,
            blob_path=f.blob_path,
            etiqueta_final=EtiquetaFinal(f.etiqueta_final),
            etiqueta_preliminar=EtiquetaPreliminar.model_validate(f.etiqueta_preliminar),
            revisada_en=f.revisada_en,
        )
        for f in filas
        if f.etiqueta_final and f.revisada_en
    ]


async def marcar_usadas(sesion: AsyncSession, ids: list[uuid.UUID], version_modelo: str) -> int:
    cantidad = await repositorio.marcar_usadas(sesion, ids, version_modelo)
    await sesion.commit()
    return cantidad


# --- Eventos ----------------------------------------------------------------------------


async def al_revocar(sesion: AsyncSession, evento: AutorizacionRevocada) -> None:
    """Borra las imagenes de la instalacion que aun no se usaron en un modelo.
    Las ya usadas se conservan (seccion 8). Idempotente."""
    blob = obtener_proveedor_blob()
    filas = await repositorio.no_usadas_de(sesion, evento.installation_id)
    for fila in filas:
        if fila.estado != EstadoImagen.eliminada:
            await blob.borrar(fila.blob_path)
        await sesion.delete(fila)
    log.info(
        "Revocacion: %d imagenes no usadas borradas (instalacion %s)",
        len(filas),
        hash_instalacion(evento.installation_id),
    )
