"""Datos de DEMOSTRACION para probar la app movil y la web contra el backend en local.

    uv run python -m scripts.sembrar_demo

- Carga al RAG un fragmento `demo-no-clinica#1` armado con los textos de preguntas.json.
  NO es una guia clinica: solo sirve para que /v1/orientacion tenga algo que recuperar.
- Sube 3 imagenes sinteticas a `verificadas/` y las registra en Revision como pendientes
  (lo que en produccion hace el servicio de reentrenamiento).

Se niega a correr si hay Azure configurado, para no ensuciar datos reales.
"""

import asyncio
import math
import struct
import sys
import uuid
import zlib

from app.config import obtener_settings
from app.modules.orientacion.servicio import CUESTIONARIO, DocumentoGuia, ingestar
from app.modules.revision.esquemas import EtiquetaPreliminar, ImagenVerificada
from app.modules.revision.servicio import registrar_verificada
from app.shared.db import obtener_engine, obtener_sesionador
from app.shared.proveedores import (
    ProveedorBlobMemoria,
    obtener_proveedor_blob,
    obtener_proveedor_llm,
)

RESPUESTAS = {
    "dificultad_respirar": False,
    "labios_morados": False,
    "tos_repentina": False,
    "hinchazon_cara": False,
    "dificultad_tragar": False,
    "angustia": False,
    "vomitos_diarrea": False,
    "decaimiento": False,
    "picazon": True,
    "ronchas_cambian": True,
    "tiempo_evolucion": "menos_24h",
    "extension": "una_zona",
    "desencadenante": "infeccion",
    "muy_alergico": False,
}

CASOS = [
    ("compatible", 0.91, (207, 156, 126), "habones", {}),
    (
        "no_compatible",
        0.84,
        (217, 174, 142),
        "puntos",
        {"picazon": False, "ronchas_cambian": False},
    ),
    ("indeterminado", 0.52, (224, 184, 154), "habones", {"extension": "varias_zonas"}),
]
# Edad (1 a 4 anios) y sexo de cada caso, en el mismo orden (D40).
NINOS = [(2, "femenino"), (4, "masculino"), (1, "femenino")]


def _png(ancho: int, alto: int, piel: tuple[int, int, int], tipo: str) -> bytes:
    """PNG sintetico: piel con habones (anillos) o puntitos rojos. Sin librerias."""
    rojo = (215, 128, 108)
    if tipo == "habones":
        manchas = [(0.38, 0.52, 0.17), (0.68, 0.33, 0.11), (0.66, 0.75, 0.09)]
    else:
        manchas = [(0.30 + 0.05 * (i % 4), 0.40 + 0.06 * (i // 4), 0.012) for i in range(12)]
    filas = bytearray()
    for y in range(alto):
        filas.append(0)  # filtro "None"
        for x in range(ancho):
            u, v = x / ancho, y / alto
            mezcla = 0.0
            for cx, cy, r in manchas:
                d = math.hypot((u - cx) * ancho / alto, v - cy) / r
                if tipo == "habones":
                    mezcla = max(mezcla, 0.8 * math.exp(-((d - 0.8) ** 2) * 6) if d < 1.6 else 0)
                else:
                    mezcla = max(mezcla, 0.85 if d < 1 else 0)
            filas += bytes(
                round(p * (1 - mezcla) + c * mezcla) for p, c in zip(piel, rojo, strict=True)
            )

    def bloque(tipo_bloque: bytes, datos: bytes) -> bytes:
        return (
            struct.pack(">I", len(datos))
            + tipo_bloque
            + datos
            + struct.pack(">I", zlib.crc32(tipo_bloque + datos))
        )

    cabecera = struct.pack(">IIBBBBB", ancho, alto, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + bloque(b"IHDR", cabecera)
        + bloque(b"IDAT", zlib.compress(bytes(filas), 9))
        + bloque(b"IEND", b"")
    )


def _texto_demo() -> str:
    lineas = [
        "DOCUMENTO DE DEMOSTRACION. No es una guia clinica aprobada.",
        "Sirve solo para probar la conexion entre la app y el backend.",
        "Severidad calculada por la aplicación: leve moderada alta.",
        "Clase del modelo: compatible no_compatible indeterminado.",
    ]
    for pregunta in CUESTIONARIO.preguntas:
        opciones = " ".join(o.texto for o in pregunta.opciones) or "Sí No"
        lineas.append(f"{pregunta.texto} {opciones}")
    return "\n".join(lineas)


async def principal() -> int:
    settings = obtener_settings()
    if settings.keyvault_url or settings.azure_openai_endpoint or settings.storage_account_url:
        print("Hay Azure configurado: este script es solo para local. No se hizo nada.")
        return 1

    blob = obtener_proveedor_blob()
    if isinstance(blob, ProveedorBlobMemoria):
        print("Falta STORAGE_CONNECTION_STRING=UseDevelopmentStorage=true en .env (Azurite):")
        print("con el Blob en memoria las imagenes se pierden al terminar este script.")
        return 1
    try:
        async with obtener_sesionador()() as sesion, sesion.begin():
            documento = DocumentoGuia(
                clave="demo-no-clinica",
                titulo="DEMO - no es una guia clinica",
                anio=2026,
                fuente="Datos de demostracion",
                texto=_texto_demo(),
            )
            cantidad = await ingestar(sesion, obtener_proveedor_llm(), documento)
        print(f"- RAG: {cantidad} fragmento de demostracion")

        for (clase, confianza, piel, tipo, cambios), (edad, sexo) in zip(CASOS, NINOS, strict=True):
            ruta = f"verificadas/demo-{uuid.uuid4()}.png"
            await blob.subir(ruta, _png(480, 360, piel, tipo), "image/png")
            datos = ImagenVerificada(
                paquete_id=uuid.uuid4(),
                installation_id=uuid.uuid4(),
                blob_path=ruta,
                etiqueta_preliminar=EtiquetaPreliminar(
                    clase=clase,
                    confianza=confianza,
                    respuestas={**RESPUESTAS, **cambios},
                    version_modelo="0.0.0-demo",
                    version_cuestionario=CUESTIONARIO.version,
                    edad_anios=edad,
                    sexo=sexo,
                ),
            )
            async with obtener_sesionador()() as sesion:
                registrada = await registrar_verificada(sesion, datos)
            print(f"- Revision: imagen {clase} ({registrada.id})")
    finally:
        await obtener_engine().dispose()
    print("Listo. La cuenta fija del medico se crea al arrancar la API.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(principal()))
