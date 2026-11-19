# Guías clínicas para el RAG

Aquí van **solo** los documentos sobre urticaria aguda en niños que aprobó la médica especialista. El LLM solo puede responder con lo que dicen estos textos (sección 7).

Cada guía es un archivo `.md` con esta cabecera:

```
---
titulo: Título del documento
anio: 2024
fuente: Organización o revista
aprobado: si
---
Texto de la guía...
```

- El nombre del archivo es el ID del documento. Usa minúsculas y guiones, por ejemplo `guia-urticaria-pediatrica.md`. Las fuentes que devuelve la API se ven así: `guia-urticaria-pediatrica#3`.
- Un archivo sin `aprobado: si` se ignora.
- Después de agregar o cambiar una guía, corre `uv run python -m scripts.ingesta_guias`.

**Todavía no hay guías aprobadas.** Mientras esta carpeta esté vacía, `POST /v1/orientacion` responde 503 y la app usa sus recomendaciones locales.
