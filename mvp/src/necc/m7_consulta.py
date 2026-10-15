"""Módulo 7 · Consulta en lenguaje natural sobre los documentos y los datos estandarizados.

RAG híbrido:
  - Recuperación léxica (BM25) + semántica (embeddings Gemini, coseno), combinadas
    por Reciprocal Rank Fusion: los términos contables exactos ("pasivo global")
    los encuentra BM25; las paráfrasis, los embeddings.
  - Contexto = fragmentos recuperados (con documento y página) + tabla de valores
    estandarizados (para preguntas comparativas entre entidades).
  - Prompt anclado: responder solo con el contexto, citar [documento, página] y
    decir explícitamente cuando la información no está.
  - Cada consulta queda registrada (auditoría).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np
from rank_bm25 import BM25Okapi

from . import llm
from . import m5_almacenamiento as db
from .ontologia import obtener_ontologia
from .texto import tokens

log = logging.getLogger(__name__)

K_RRF = 60


@dataclass
class Fuente:
    documento_id: int
    entidad: str
    pagina: int
    texto: str
    puntaje: float

    def como_dict(self) -> dict:
        return {"documento_id": self.documento_id, "entidad": self.entidad, "pagina": self.pagina,
                "extracto": self.texto[:300]}


def indexar(documento_id: int) -> int:
    """Calcula embeddings de los fragmentos del documento que aún no los tienen."""
    with db.conexion() as con:
        filas = con.execute(
            "SELECT id, texto FROM fragmentos WHERE documento_id = ? AND embedding IS NULL", (documento_id,)
        ).fetchall()
        if not filas or not llm.disponible():
            return 0
        vectores = llm.embeddings([f["texto"] for f in filas], "RETRIEVAL_DOCUMENT")
        db.guardar_embeddings(con, [(f["id"], v) for f, v in zip(filas, vectores)])
    return len(filas)


def buscar(pregunta: str, k: int = 6, documento_ids: list[int] | None = None) -> list[Fuente]:
    with db.conexion() as con:
        filas = db.fragmentos_para_consulta(con, documento_ids)
    if not filas:
        return []
    rankings: list[list[int]] = []

    bm25 = BM25Okapi([tokens(f["texto"]) or ["_"] for f in filas])
    lexico = bm25.get_scores(tokens(pregunta))
    rankings.append(list(np.argsort(-lexico)))

    con_vector = [i for i, f in enumerate(filas) if f["embedding"] is not None]
    if con_vector and llm.disponible():
        try:
            q = llm.embeddings([pregunta], "RETRIEVAL_QUERY")[0]
        except Exception:
            log.exception("Falló el embedding de la pregunta; se recupera solo con BM25")
        else:
            matriz = np.stack([np.frombuffer(filas[i]["embedding"], dtype=np.float32) for i in con_vector])
            orden = np.argsort(-(matriz @ q))
            rankings.append([con_vector[j] for j in orden])

    rrf: dict[int, float] = {}
    for ranking in rankings:
        for pos, idx in enumerate(ranking[: 50]):
            rrf[int(idx)] = rrf.get(int(idx), 0.0) + 1.0 / (K_RRF + pos + 1)
    mejores = sorted(rrf, key=lambda i: -rrf[i])[:k]
    return [
        Fuente(filas[i]["documento_id"], filas[i]["entidad"] or filas[i]["nombre_archivo"], filas[i]["pagina"],
               filas[i]["texto"], rrf[i])
        for i in mejores
    ]


def _tabla_valores(documento_ids: list[int] | None) -> str:
    onto = obtener_ontologia()
    with db.conexion() as con:
        tabla = db.tabla_base(con)
    if documento_ids:
        tabla = tabla[tabla["documento_id"].isin(documento_ids)]
    if tabla.empty:
        return "(sin datos estandarizados)"
    tabla = tabla.assign(entidad=tabla["entidad"].fillna(tabla["nombre_archivo"]))
    tabla = tabla.rename(columns={c.id: c.nombre for c in onto.campos}).drop(columns=["nombre_archivo"])
    return tabla.to_csv(index=False)


SISTEMA_CONSULTA = """Rol: asistente de análisis de estados contables de aseguradoras de riesgos del trabajo (ART).
Objetivo: responder la pregunta del usuario.
Reglas:
- Basate ÚNICAMENTE en el CONTEXTO (fragmentos de documentos y tabla de valores estandarizados en pesos).
- Si la información no está en el contexto, decí exactamente: "No encuentro esa información en los documentos cargados."
- Citá las fuentes como [entidad, pág. N] para datos de fragmentos, o [tabla estandarizada] para la tabla.
- Respondé en español, de forma concisa; los montos en pesos con separador de miles."""


def responder(pregunta: str, documento_ids: list[int] | None = None, k: int = 6) -> tuple[str, list[Fuente]]:
    fuentes = buscar(pregunta, k, documento_ids)
    contexto = "\n\n".join(f"[{f.entidad}, pág. {f.pagina}]\n{f.texto}" for f in fuentes)
    prompt = (
        f"CONTEXTO — TABLA DE VALORES ESTANDARIZADOS (CSV, montos en pesos):\n{_tabla_valores(documento_ids)}\n\n"
        f"CONTEXTO — FRAGMENTOS RECUPERADOS:\n{contexto or '(ninguno)'}\n\n"
        f"PREGUNTA: {pregunta}"
    )
    respuesta = llm.generar_texto(prompt, sistema=SISTEMA_CONSULTA)
    with db.conexion() as con:
        db.registrar_consulta(con, pregunta, respuesta, [f.como_dict() for f in fuentes])
    return respuesta, fuentes
