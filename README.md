# Wawa Qhali · Backend

API en FastAPI (monolito modular) para la app móvil, la app web del médico y el servicio de reentrenamiento.

La fuente de verdad es `wawa-qhali-backend.md`, junto con `wawa-qhali-cuestionario.md`; donde se contradicen, manda el cuestionario. Las decisiones que la guía no cubre están en [`docs/decisiones.md`](docs/decisiones.md).

## Estado

| Etapa | Contenido | Estado |
| --- | --- | --- |
| 1 | Esqueleto, docker-compose, CI, `/health`, Alembic, bus de eventos, proveedores falsos | ✅ |
| 2 | Orientación con RAG: cuestionario v1, ingesta, consulta, validación del LLM, 503 de respaldo | ✅ (faltan guías aprobadas) |
| 3 | Autorización, Recepción y cifrado; Modelos con compuerta | ✅ |
| 4 | Revisión: login, endpoints de la app web e internos; prueba completa del pipeline | ✅ (con imágenes sintéticas) |
| 5 | Evidencias: OpenAPI en `docs/evidencias/` | En curso |

El CI corre `ruff`, `lint-imports`, `pytest` (120 pruebas) y `pip-audit`.

## Endpoints

| Quién | Rutas |
| --- | --- |
| App móvil (`X-Installation-Id`) | `POST/GET/DELETE /v1/autorizaciones`, `GET /v1/claves/publica`, `POST /v1/donaciones`, `POST /v1/orientacion`, `GET /v1/modelos/manifiesto` |
| Médico (JWT, rol `medico`) | `POST /v1/auth/login`, `GET /v1/revision/pendientes`, `GET /v1/revision/{id}`, `POST /v1/revision/{id}/etiqueta`, `POST /v1/revision/{id}/eliminar` |
| Equipo (JWT, rol `equipo`) | `POST /v1/modelos/{version}/publicar`, `POST /v1/modelos/{version}/revertir` |
| Reentrenamiento (`X-Api-Key`) | `POST /v1/interno/revision/verificadas`, `GET /v1/interno/revision/etiquetas?desde=`, `POST /v1/interno/revision/usadas`, `POST /v1/interno/modelos/candidatos` |

El detalle, con ejemplos, está en `/docs` (OpenAPI) y en [`docs/evidencias/openapi.json`](docs/evidencias/openapi.json).

## Requisitos

- [uv](https://docs.astral.sh/uv/), que instala Python 3.12 solo.
- Docker Desktop.

## Correr en local

```bash
cp .env.example .env          # completa JWT_SECRET e INTERNAL_API_KEY
docker compose up -d          # PostgreSQL + pgvector y Azurite
uv sync
uv run alembic upgrade head
uv run python -m scripts.crear_medico --usuario dra.prueba --rol medico
uv run python -m scripts.ingesta_guias     # cuando haya guías aprobadas en guias/
uv run uvicorn app.main:app --reload
```

- Salud: http://localhost:8000/health
- OpenAPI: http://localhost:8000/docs

Sin `KEYVAULT_URL` ni `AZURE_OPENAI_ENDPOINT` se usan los proveedores falsos, así que no hace falta Azure.

## Calidad (igual que el CI)

```bash
uv run ruff check
uv run lint-imports
uv run pytest            # las pruebas marcadas `bd` necesitan `docker compose up -d`
```

## Estructura

```
app/
  main.py              crea la app, monta routers, /health; conecta puertos y eventos
  config.py            variables de entorno
  shared/
    db.py              engine y sesión async (identidad gestionada en Azure)
    auth.py            JWT, clave interna, X-Installation-Id, Argon2
    eventos.py         bus de eventos respaldado en shared.eventos
    puertos.py         consultas entre módulos sin importarse (autorización vigente)
    proveedores.py     ProveedorClaves, ProveedorLLM y ProveedorBlob (falsos y de Azure)
    errores.py         errores genéricos para el cliente
    limites.py         slowapi y límite de 2 MB
    logs.py            logs sin datos personales (UUID → hash)
  modules/
    autorizacion/      permiso de donar; publica AutorizacionRevocada
    recepcion/         clave pública, donaciones cifradas en cuarentena
    revision/          login, app web del médico, endpoints internos
    orientacion/       preguntas.json v1, RAG, validación del LLM
    modelos/           candidatos, compuerta, manifiesto, reversión
migrations/            0001 base · 0002 tablas de los módulos
scripts/               ingesta_guias.py · crear_medico.py
guias/                 guías clínicas aprobadas (vacío por ahora)
tests/                 una carpeta por módulo + shared + test_pipeline.py
```

## Despliegue (contrato con Fabricio, sección 10)

- Imagen: `docker build -t wawa-qhali-backend .` → puerto 8000, usuario no root.
- Migraciones: correr `alembic upgrade head` con la misma imagen, como paso del despliegue.
- En Azure, `VECTOR` tiene que estar en `azure.extensions` (D9). Los contenedores `cuarentena`, `verificadas` y `modelos` tienen que existir.
- Permisos de la identidad gestionada:
  - Key Vault: `get` y `list` sobre la clave (D3).
  - Blob: lectura y escritura, y además `generateUserDelegationKey` para los SAS.
  - PostgreSQL con Entra ID.
  - Azure OpenAI: rol de usuario.
