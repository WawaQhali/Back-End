"""Orientacion: recomendaciones con LLM y RAG para la severidad que calculo la app. Etapa 2.

Interfaz publica del modulo: `router`. Otros modulos no lo importan (seccion 3).
"""

from app.modules.orientacion.api import router

__all__ = ["router"]
