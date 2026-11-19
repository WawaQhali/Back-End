# syntax=docker/dockerfile:1

# --- Etapa 1: dependencias con uv -------------------------------------------
FROM python:3.12-slim AS build
COPY --from=ghcr.io/astral-sh/uv:0.13.8 /uv /bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /srv
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY app ./app
COPY migrations ./migrations
COPY alembic.ini ./

# --- Etapa 2: imagen final, sin uv y con usuario no root ------------------------
FROM python:3.12-slim
RUN useradd --create-home --uid 10001 wawa
WORKDIR /srv
COPY --from=build --chown=wawa:wawa /srv /srv
ENV PATH="/srv/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    FORWARDED_ALLOW_IPS="*"
USER wawa
EXPOSE 8000
# Las migraciones NO corren aqui: `alembic upgrade head` es un paso del despliegue.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
