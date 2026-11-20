"""Calibra UMBRAL_DISTANCIA del RAG con los fragmentos reales de la base (D34).

Positivos: consultas realistas, armadas con el mismo `texto_consulta` del backend, contra los
fragmentos de rag.fragmentos. Negativos: las mismas consultas contra fragmentos señuelo de otros
temas, que no se guardan en la base. No escribe nada en la base.

Uso (desde Back-End, con las mismas variables de Azure que la ingesta):
    uv run python -m scripts.calibrar_umbral [salida.json]

Hay que repetirlo cada vez que cambien las guías.
"""

# ruff: noqa: S311  (el azar solo elige las consultas de prueba)

import asyncio
import itertools
import json
import math
import random
import statistics
import sys
from pathlib import Path

from sqlalchemy import select

from app.modules.orientacion.esquemas import ConsultaOrientacion
from app.modules.orientacion.servicio import CUESTIONARIO, texto_consulta
from app.modules.orientacion.tablas import Fragmento
from app.shared.db import obtener_engine, obtener_sesionador
from app.shared.proveedores import obtener_proveedor_llm

random.seed(7)
CANTIDAD_CONSULTAS = 36

SENUELOS = {
    "varicela": "La varicela es una infección viral muy contagiosa. Aparecen ampollas pequeñas "
    "con líquido que luego forman costras, junto con fiebre y malestar. Los niños deben "
    "quedarse en casa hasta que todas las lesiones tengan costra.",
    "dengue": "El dengue se transmite por la picadura del mosquito Aedes aegypti. Produce "
    "fiebre alta, dolor de cabeza, dolor detrás de los ojos y dolor muscular. Elimine los "
    "recipientes con agua estancada para evitar criaderos.",
    "otitis": "La otitis media aguda es una infección del oído medio frecuente en niños "
    "pequeños. El niño se toca la oreja, llora y puede tener fiebre. Acuda al pediatra si el "
    "dolor dura más de dos días o sale líquido del oído.",
    "diarrea": "En la diarrea aguda lo más importante es evitar la deshidratación. Ofrezca "
    "líquidos con frecuencia y siga dando de comer. Busque atención si el niño no orina, "
    "tiene la boca seca o hay sangre en las heces.",
    "dermatitis_atopica": "La dermatitis atópica es una enfermedad crónica de la piel con "
    "resequedad y eccema en pliegues de codos y rodillas. Use cremas hidratantes a diario, "
    "baños cortos con agua tibia y ropa de algodón.",
    "quemaduras": "Ante una quemadura enfríe la zona con agua corriente durante 20 minutos. "
    "No aplique hielo, pasta dental ni mantequilla. Cubra con un paño limpio y acuda a un "
    "centro de salud si la quemadura es grande o está en la cara.",
    "vacunas": "El calendario de vacunación del niño menor de 5 años incluye las vacunas "
    "pentavalente, neumococo, rotavirus, sarampión, paperas y rubéola. Lleve su carné de "
    "vacunación a cada control de crecimiento y desarrollo.",
    "sueno": "Los niños de 1 a 4 años necesitan entre 10 y 13 horas de sueño. Mantenga una "
    "rutina fija antes de dormir, evite pantallas una hora antes y un ambiente oscuro y "
    "tranquilo en la habitación.",
    "asma": "En la crisis de asma el niño tiene silbidos en el pecho, tos y le cuesta "
    "respirar. Siga el plan de acción que le dio su médico y acuda a emergencia si los "
    "labios se ponen morados o no puede hablar.",
    "cocina": "Para preparar un arroz con pollo, dore las presas, agregue cebolla, ajo y "
    "culantro licuado, luego el arroz y el caldo. Cocine a fuego bajo hasta que el arroz "
    "esté graneado.",
}

NORMALES = {
    "picazon": [True, False],
    "ronchas_cambian": [True, False],
    "tiempo_evolucion": ["menos_24h", "1_3_dias", "mas_3_dias"],
    "extension": ["una_zona", "varias_zonas"],
    "desencadenante": ["infeccion", "alimento", "medicamento", "picadura", "contacto", "no_se"],
    "muy_alergico": [True, False],
}
RIESGO = [p.id for p in CUESTIONARIO.preguntas if p.tipo == "riesgo"]


def severidad(normales: dict) -> str:
    """Las mismas reglas_moderada de preguntas.json."""
    moderada = (
        normales["tiempo_evolucion"] == "mas_3_dias"
        or normales["extension"] == "varias_zonas"
        or normales["muy_alergico"] is True
    )
    return "moderada" if moderada else "leve"


def consultas() -> list[ConsultaOrientacion]:
    claves = list(NORMALES)
    combinaciones = [
        dict(zip(claves, v, strict=True)) for v in itertools.product(*NORMALES.values())
    ]
    resultado = []
    for i, normales in enumerate(random.sample(combinaciones, CANTIDAD_CONSULTAS)):
        riesgo = dict.fromkeys(RIESGO, False)
        sev = severidad(normales)
        if i % 3 == 0:  # un tercio con signos de alarma
            for r in random.sample(RIESGO, random.choice([1, 2])):
                riesgo[r] = True
            sev = "alta"
        clase = random.choice(["compatible", "compatible", "no_compatible", "indeterminado"])
        resultado.append(
            ConsultaOrientacion(
                severidad=sev,
                clase=clase,
                confianza=round(random.uniform(0.4, 0.99), 2),
                version_cuestionario=CUESTIONARIO.version,
                respuestas={**riesgo, **normales},
            )
        )
    return resultado


def distancia(a: list[float], b: list[float]) -> float:
    """Distancia coseno, igual que el operador <=> de pgvector."""
    punto = sum(x * y for x, y in zip(a, b, strict=True))
    return 1 - punto / (math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b)))


def resumen(nombre: str, valores: list[float]) -> str:
    v = sorted(valores)

    def p(q: float) -> float:
        return v[min(len(v) - 1, int(q * len(v)))]

    return (
        f"{nombre:<34} n={len(v):>3}  min={v[0]:.3f}  p10={p(0.10):.3f}  "
        f"mediana={statistics.median(v):.3f}  p90={p(0.90):.3f}  max={v[-1]:.3f}"
    )


async def principal() -> dict:
    llm = obtener_proveedor_llm()
    lista = consultas()
    textos = [texto_consulta(c, CUESTIONARIO) for c in lista]
    vectores_q: list[list[float]] = []
    for i in range(0, len(textos), 16):
        vectores_q += await llm.embeddings(textos[i : i + 16])
    vectores_s = await llm.embeddings(list(SENUELOS.values()))

    try:
        async with obtener_sesionador()() as sesion:
            fragmentos = (await sesion.execute(select(Fragmento))).scalars().all()
    finally:
        await obtener_engine().dispose()

    filas = []
    for consulta, vq in zip(lista, vectores_q, strict=True):
        reales = sorted((distancia(vq, list(f.embedding)), f.id) for f in fragmentos)
        senuelos = sorted(
            (distancia(vq, vs), n) for n, vs in zip(SENUELOS, vectores_s, strict=True)
        )
        filas.append(
            {"severidad": consulta.severidad.value, "reales": reales, "senuelos": senuelos}
        )

    top1 = [f["reales"][0][0] for f in filas]
    top5 = [d for f in filas for d, _ in f["reales"][:5]]
    sen = [d for f in filas for d, _ in f["senuelos"]]

    print(f"Fragmentos: {len(fragmentos)} · consultas: {len(lista)} · señuelos: {len(SENUELOS)}")
    print(resumen("Real más cercano (top-1)", top1))
    print(resumen("Reales top-5", top5))
    print(resumen("Todos los reales", [d for f in filas for d, _ in f["reales"]]))
    print(resumen("Señuelos (todos)", sen))
    print(resumen("Señuelo más cercano por consulta", [f["senuelos"][0][0] for f in filas]))
    for sev in ("leve", "moderada", "alta"):
        t = [f["reales"][0][0] for f in filas if f["severidad"] == sev]
        if t:
            print(resumen(f"top-1 {sev}", t))

    print("\nSeñuelo más cercano, por tema:")
    por_tema: dict[str, list[float]] = {}
    for f in filas:
        for d, n in f["senuelos"]:
            por_tema.setdefault(n, []).append(d)
    for n, ds in sorted(por_tema.items(), key=lambda t: min(t[1])):
        print(f"  {n:<20} min={min(ds):.3f}  mediana={statistics.median(ds):.3f}")

    print("\nUmbral · consultas con algún fragmento · fragmentos que pasan (de 5) · señuelos")
    for u in [x / 100 for x in range(40, 71, 2)]:
        con = sum(1 for d in top1 if d <= u) / len(top1)
        pasan = statistics.mean(sum(1 for d, _ in f["reales"][:5] if d <= u) for f in filas)
        malos = sum(1 for d in sen if d <= u) / len(sen)
        print(f"  {u:.2f}   {con:6.1%}   {pasan:4.2f}   {malos:6.1%}")

    return {"filas": filas, "textos": textos}


if __name__ == "__main__":
    destino = Path(sys.argv[1] if len(sys.argv) > 1 else "calibracion.json")
    datos = asyncio.run(principal())
    destino.write_text(json.dumps(datos, ensure_ascii=False, indent=1), encoding="utf-8")
