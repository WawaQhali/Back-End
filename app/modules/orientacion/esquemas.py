"""Modelos de Pydantic de entrada y salida del modulo orientacion (seccion 7.3 y
cuestionario v1)."""

from enum import StrEnum
from typing import Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    StrictStr,
    model_validator,
)


class Severidad(StrEnum):
    leve = "leve"
    moderada = "moderada"
    alta = "alta"


class Clase(StrEnum):
    # TODO(seccion 13): el .tflite actual tiene 2 salidas; confirmar con Diego.
    compatible = "compatible"
    no_compatible = "no_compatible"
    indeterminado = "indeterminado"


# D40: datos del nino que la app pide antes del cuestionario. Opcionales para no
# romper las versiones de la app que aun no los envian.
EDAD_MINIMA_ANIOS = 1
EDAD_MAXIMA_ANIOS = 4
Sexo = Literal["femenino", "masculino"]


class ConsultaOrientacion(BaseModel):
    severidad: Severidad
    clase: Clase
    confianza: float = Field(ge=0, le=1)
    version_cuestionario: str
    # Se valida contra preguntas.json. Estrictos: `true` no puede llegar como "true" o 1.
    respuestas: dict[str, StrictBool | StrictStr]
    texto_libre: str | None = Field(default=None, max_length=200)
    edad_anios: StrictInt | None = Field(default=None, ge=EDAD_MINIMA_ANIOS, le=EDAD_MAXIMA_ANIOS)
    sexo: Sexo | None = None

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "severidad": "leve",
                    "clase": "compatible",
                    "confianza": 0.91,
                    "version_cuestionario": "v1",
                    "respuestas": {
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
                    },
                    "texto_libre": "Empezó después de un resfrío.",
                    "edad_anios": 2,
                    "sexo": "femenino",
                }
            ]
        }
    )


class RespuestaOrientacion(BaseModel):
    """Sin severidad: la decide la app y el backend no la devuelve."""

    recomendaciones: list[str] = Field(min_length=1, max_length=5)
    fuentes: list[str] = Field(min_length=1)  # IDs de los fragmentos citados

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [
                {
                    "recomendaciones": [
                        "Mantén a tu hijo con ropa fresca y evita rascar las ronchas.",
                        "Si empeora, aparece dificultad para respirar o se hinchan los labios, "
                        "acude a emergencia.",
                    ],
                    "fuentes": ["guia-urticaria-pediatrica#3", "guia-urticaria-pediatrica#7"],
                }
            ]
        },
    )


# --- preguntas.json -------------------------------------------------------------


class Opcion(BaseModel):
    id: str
    texto: str


class Pregunta(BaseModel):
    id: str
    tipo: Literal["riesgo", "normal"]
    respuesta: Literal["si_no", "opcion"]
    texto: str
    opciones: list[Opcion] = []

    @model_validator(mode="after")
    def _coherente(self) -> "Pregunta":
        if self.respuesta == "opcion" and not self.opciones:
            raise ValueError(f"La pregunta {self.id} es de opcion y no tiene opciones")
        if self.tipo == "riesgo" and self.respuesta != "si_no":
            raise ValueError(f"La pregunta de riesgo {self.id} debe ser si_no")
        return self


class ReglaModerada(BaseModel):
    pregunta: str
    valor: StrictBool | StrictStr


class Cuestionario(BaseModel):
    version: str
    validado: bool
    mensaje_emergencia: str
    preguntas: list[Pregunta]
    reglas_moderada: list[ReglaModerada]

    model_config = ConfigDict(extra="allow")  # p. ej. "validacion"

    @model_validator(mode="after")
    def _ids_y_reglas(self) -> "Cuestionario":
        ids = [p.id for p in self.preguntas]
        if len(ids) != len(set(ids)):
            raise ValueError("Hay IDs de pregunta repetidos")
        por_id = {p.id: p for p in self.preguntas}
        for regla in self.reglas_moderada:
            pregunta = por_id.get(regla.pregunta)
            if pregunta is None:
                raise ValueError(f"La regla usa una pregunta inexistente: {regla.pregunta}")
            if not _valor_valido(pregunta, regla.valor):
                raise ValueError(f"La regla de {regla.pregunta} tiene un valor invalido")
        return self

    def pregunta(self, id_pregunta: str) -> Pregunta | None:
        return next((p for p in self.preguntas if p.id == id_pregunta), None)


def _valor_valido(pregunta: Pregunta, valor: bool | str) -> bool:
    if pregunta.respuesta == "si_no":
        return isinstance(valor, bool)
    return isinstance(valor, str) and valor in {o.id for o in pregunta.opciones}
