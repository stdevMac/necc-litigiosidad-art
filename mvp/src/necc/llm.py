"""Cliente LLM (Gemini) compartido por estandarización, OCR y consulta.

Aislar el proveedor acá permite reemplazarlo (p.ej. Ollama local para datos
sensibles) sin tocar los módulos del pipeline.
"""

from __future__ import annotations

from functools import lru_cache
from typing import TypeVar

import numpy as np
from google import genai
from google.genai import types
from pydantic import BaseModel

from .config import obtener_config

M = TypeVar("M", bound=BaseModel)


class LLMNoConfigurado(RuntimeError):
    pass


@lru_cache(maxsize=1)
def _cliente() -> genai.Client:
    cfg = obtener_config()
    if not cfg.gemini_api_key:
        raise LLMNoConfigurado("Falta GEMINI_API_KEY (definila en el entorno o en mvp/.env).")
    return genai.Client(
        api_key=cfg.gemini_api_key,
        http_options=types.HttpOptions(
            timeout=180_000,
            retry_options=types.HttpRetryOptions(attempts=5, initial_delay=2.0, http_status_codes=[429, 500, 503]),
        ),
    )


def disponible() -> bool:
    return bool(obtener_config().gemini_api_key)


def generar_json(prompt: str, esquema: type[M], sistema: str | None = None) -> M:
    """Salida estructurada validada contra un modelo Pydantic (temperatura 0)."""
    respuesta = _cliente().models.generate_content(
        model=obtener_config().modelo_llm,
        contents=prompt,
        config=types.GenerateContentConfig(
            system_instruction=sistema,
            temperature=0,
            response_mime_type="application/json",
            response_schema=esquema,
        ),
    )
    if respuesta.parsed is not None:
        return respuesta.parsed
    return esquema.model_validate_json(respuesta.text)


def generar_texto(prompt: str, sistema: str | None = None, temperatura: float = 0.2) -> str:
    respuesta = _cliente().models.generate_content(
        model=obtener_config().modelo_llm,
        contents=prompt,
        config=types.GenerateContentConfig(system_instruction=sistema, temperature=temperatura),
    )
    return respuesta.text or ""


def transcribir_imagen(png: bytes, instruccion: str) -> str:
    respuesta = _cliente().models.generate_content(
        model=obtener_config().modelo_llm,
        contents=[types.Part.from_bytes(data=png, mime_type="image/png"), instruccion],
        config=types.GenerateContentConfig(temperature=0),
    )
    return respuesta.text or ""


def embeddings(textos: list[str], tarea: str) -> np.ndarray:
    """Vectores normalizados (norma 1) para similitud coseno por producto interno.

    tarea: RETRIEVAL_DOCUMENT para indexar, RETRIEVAL_QUERY para preguntas.
    """
    cfg = obtener_config()
    vectores: list[list[float]] = []
    for i in range(0, len(textos), 100):
        lote = textos[i : i + 100]
        r = _cliente().models.embed_content(
            model=cfg.modelo_embeddings,
            contents=lote,
            config=types.EmbedContentConfig(task_type=tarea, output_dimensionality=cfg.dimension_embeddings),
        )
        vectores.extend(e.values for e in r.embeddings)
    matriz = np.asarray(vectores, dtype=np.float32)
    normas = np.linalg.norm(matriz, axis=1, keepdims=True)
    return matriz / np.where(normas == 0, 1, normas)
