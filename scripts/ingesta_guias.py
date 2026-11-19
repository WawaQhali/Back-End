"""Carga al RAG las guias clinicas aprobadas de la carpeta guias/ (seccion 7.1).

Uso (desde la carpeta del backend):
    uv run python -m scripts.ingesta_guias            # todas las aprobadas
    uv run python -m scripts.ingesta_guias archivo.md # solo una

Cada archivo .md empieza con una cabecera:
    ---
    titulo: Urticaria aguda en ninos
    anio: 2024
    fuente: Sociedad X
    aprobado: si
    ---
Sin `aprobado: si` el archivo se ignora. Volver a correrlo reemplaza los fragmentos
del documento. Con AZURE_OPENAI_ENDPOINT usa Azure; si no, embeddings falsos.
"""

import asyncio
import sys
from pathlib import Path

from app.modules.orientacion.servicio import ingestar, leer_guia
from app.shared.db import obtener_engine, obtener_sesionador
from app.shared.proveedores import obtener_proveedor_llm

CARPETA_GUIAS = Path(__file__).resolve().parents[1] / "guias"


async def principal(nombres: list[str]) -> int:
    rutas = [CARPETA_GUIAS / n for n in nombres] if nombres else sorted(CARPETA_GUIAS.glob("*.md"))
    llm = obtener_proveedor_llm()
    total = 0
    try:
        for ruta in rutas:
            if ruta.name.lower() == "readme.md":
                continue
            documento = leer_guia(ruta)
            if documento is None:
                print(f"- {ruta.name}: sin aprobar, se omite")
                continue
            async with obtener_sesionador()() as sesion, sesion.begin():
                cantidad = await ingestar(sesion, llm, documento)
            print(f"- {ruta.name}: {cantidad} fragmentos")
            total += cantidad
    finally:
        await obtener_engine().dispose()
    print(f"Listo: {total} fragmentos en rag.fragmentos")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(principal(sys.argv[1:])))
