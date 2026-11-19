"""Alta de cuentas del medico y del equipo (seccion 2).

Uso (desde la carpeta del backend, con la base configurada en .env):
    uv run python -m scripts.crear_medico --usuario dra.quispe --rol medico
    uv run python -m scripts.crear_medico --usuario fabricio --rol equipo

La contrasena se pide por teclado (nunca como argumento, para que no quede en el
historial de la terminal) y se guarda con Argon2.
"""

import argparse
import asyncio
import getpass
import sys

from app.modules.revision.servicio import crear_usuario
from app.shared.auth import Rol
from app.shared.db import obtener_engine, obtener_sesionador

LONGITUD_MINIMA = 12


async def principal(usuario: str, rol: Rol, contrasena: str) -> None:
    try:
        async with obtener_sesionador()() as sesion:
            id_usuario = await crear_usuario(sesion, usuario, contrasena, rol)
    finally:
        await obtener_engine().dispose()
    print(f"Cuenta creada: {usuario} ({rol.value}), id {id_usuario}")


def _pedir_contrasena() -> str:
    contrasena = getpass.getpass("Contrasena: ")
    if len(contrasena) < LONGITUD_MINIMA:
        raise SystemExit(f"La contrasena debe tener al menos {LONGITUD_MINIMA} caracteres.")
    if getpass.getpass("Repite la contrasena: ") != contrasena:
        raise SystemExit("Las contrasenas no coinciden.")
    return contrasena


if __name__ == "__main__":
    analizador = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    analizador.add_argument("--usuario", required=True)
    analizador.add_argument("--rol", required=True, choices=[r.value for r in Rol])
    argumentos = analizador.parse_args()
    try:
        asyncio.run(principal(argumentos.usuario, Rol(argumentos.rol), _pedir_contrasena()))
    except ValueError as error:
        sys.exit(str(error))
