"""Logica de negocio del modulo modelos: candidatos, compuerta y manifiesto.

Compuerta (seccion 4): un candidato no se publica si su sensibilidad es menor que la
del vigente, ni si cambia el orden de las clases o el tamano de entrada. En esos casos
responde 409, el candidato queda `bloqueado` y el vigente no cambia.
"""

from datetime import UTC, datetime

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.modelos import repositorio
from app.modules.modelos.esquemas import Candidato, Entrada, Estado, EstadoVersion, Manifiesto
from app.modules.modelos.tablas import VersionModelo
from app.shared.errores import ErrorApi
from app.shared.proveedores import ProveedorBlob


def _estado(fila: VersionModelo) -> EstadoVersion:
    return EstadoVersion(
        version=fila.version,
        estado=Estado(fila.estado),
        sensibilidad=fila.sensibilidad,
        publicado_en=fila.publicado_en,
    )


async def registrar_candidato(sesion: AsyncSession, candidato: Candidato) -> EstadoVersion:
    fila = VersionModelo(
        version=candidato.version,
        sensibilidad=candidato.sensibilidad,
        sha256=candidato.sha256,
        blob_path=candidato.blob_path,
        tamano=candidato.tamano,
        entrada=candidato.entrada.model_dump(),
        clases=candidato.clases,
        umbral_confianza=candidato.umbral_confianza,
        estado=Estado.candidato,
    )
    sesion.add(fila)
    try:
        await sesion.commit()
    except IntegrityError as error:
        await sesion.rollback()
        raise ErrorApi(409, "version_existente", "Esa version ya esta registrada.") from error
    return _estado(fila)


def _motivo_de_bloqueo(candidato: VersionModelo, vigente: VersionModelo) -> str | None:
    if candidato.sensibilidad < vigente.sensibilidad:
        return "La sensibilidad es menor que la del modelo vigente."
    if candidato.clases != vigente.clases:
        return "Cambia el orden o la lista de clases respecto del vigente."
    forma = ("ancho", "alto", "canales")
    if any(candidato.entrada.get(k) != vigente.entrada.get(k) for k in forma):
        return "Cambia el tamano de entrada respecto del vigente."
    return None


async def publicar(sesion: AsyncSession, version: str) -> EstadoVersion:
    candidato = await repositorio.obtener(sesion, version, bloquear=True)
    if candidato is None:
        raise ErrorApi(404, "version_inexistente", "No existe esa version.")
    if candidato.estado != Estado.candidato:
        raise ErrorApi(409, "no_es_candidato", "Solo se puede publicar un candidato.")

    vigente = await repositorio.vigente(sesion, bloquear=True)
    if vigente is not None:
        motivo = _motivo_de_bloqueo(candidato, vigente)
        if motivo:
            candidato.estado = Estado.bloqueado
            await sesion.commit()
            raise ErrorApi(409, "compuerta_rechazada", motivo)
        vigente.estado = Estado.retirado

    candidato.estado = Estado.publicado
    candidato.publicado_en = datetime.now(UTC)
    await sesion.commit()
    return _estado(candidato)


async def revertir(sesion: AsyncSession, version: str) -> EstadoVersion:
    """Retira la version vigente `version` y vuelve a publicar la anterior.
    La revertida queda `bloqueada` para que no se elija otra vez al revertir."""
    actual = await repositorio.obtener(sesion, version, bloquear=True)
    if actual is None:
        raise ErrorApi(404, "version_inexistente", "No existe esa version.")
    if actual.estado != Estado.publicado:
        raise ErrorApi(409, "no_es_vigente", "Solo se puede revertir la version vigente.")
    anterior = await repositorio.anterior_retirada(sesion, excluir=version)
    if anterior is None:
        raise ErrorApi(409, "sin_anterior", "No hay una version anterior para volver.")

    actual.estado = Estado.bloqueado
    anterior.estado = Estado.publicado
    anterior.publicado_en = datetime.now(UTC)
    await sesion.commit()
    return _estado(anterior)


async def manifiesto(sesion: AsyncSession, blob: ProveedorBlob) -> Manifiesto:
    vigente = await repositorio.vigente(sesion)
    if vigente is None:
        raise ErrorApi(404, "sin_modelo", "Todavia no hay un modelo publicado.")
    return Manifiesto(
        version=vigente.version,
        sha256=vigente.sha256,
        tamano=vigente.tamano,
        url=await blob.enlace_lectura(vigente.blob_path),
        entrada=Entrada.model_validate(vigente.entrada),
        clases=vigente.clases,
        umbral_confianza=vigente.umbral_confianza,
    )
