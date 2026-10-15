"""Orquestador: ejecuta los módulos en orden para un documento y deja bitácora.

  m1 descubrimiento -> m2 procesamiento -> m3 estandarización -> m4 pre-procesamiento
  -> m5 almacenamiento -> m7 indexación para consulta -> m8 acción
  (m6 visualización lee lo que queda en la base)

Cada etapa registra un evento (estado y duración). Si una falla, el documento
queda en estado 'error' con el detalle y se notifica al responsable. Las fallas
del LLM o del OCR no detienen el documento: se sigue con las reglas y se abre
una incidencia. Sin embeddings, la consulta usa solo BM25.
"""

from __future__ import annotations

import time
import traceback
from contextlib import contextmanager
from pathlib import Path
from typing import Callable

from . import m5_almacenamiento as db
from . import m7_consulta, m8_accion
from .m2_procesamiento import procesar
from .m3_estandarizacion import estandarizar
from .m4_preprocesamiento import preprocesar
from .ontologia import obtener_ontologia

Progreso = Callable[[str, str], None]


@contextmanager
def _etapa(documento_id: int, nombre: str, progreso: Progreso | None):
    if progreso:
        progreso(nombre, "inicio")
    inicio = time.perf_counter()
    detalle: dict = {"texto": ""}
    try:
        yield detalle
    except Exception as e:
        with db.conexion() as con:
            db.registrar_evento(con, documento_id, nombre, "error", f"{type(e).__name__}: {e}",
                                int((time.perf_counter() - inicio) * 1000))
        raise
    ms = int((time.perf_counter() - inicio) * 1000)
    with db.conexion() as con:
        db.registrar_evento(con, documento_id, nombre, "ok", detalle["texto"], ms)
    if progreso:
        progreso(nombre, f"ok · {detalle['texto']} ({ms / 1000:.1f}s)")


def procesar_documento(documento_id: int, usar_llm: bool = True, progreso: Progreso | None = None) -> dict:
    onto = obtener_ontologia()
    with db.conexion() as con:
        doc = db.obtener_documento(con, documento_id)
        db.actualizar_estado(con, documento_id, "procesando")
        db.registrar_evento(con, documento_id, "pipeline", "inicio", f"usar_llm={usar_llm}")
    try:
        with _etapa(documento_id, "procesamiento", progreso) as d:
            procesado = procesar(Path(doc["ruta"]))
            ocr = sum(p.metodo != "texto" for p in procesado.paginas)
            fallidas = sum(p.metodo.endswith("ocr_fallido") for p in procesado.paginas)
            d["texto"] = (f"{len(procesado.paginas)} páginas ({ocr} con OCR"
                          f"{f', {fallidas} con OCR fallido' if fallidas else ''}), "
                          f"{len(procesado.fragmentos)} fragmentos")
            with db.conexion() as con:
                db.guardar_procesado(con, documento_id, procesado)

        with _etapa(documento_id, "estandarizacion", progreso) as d:
            est = estandarizar(procesado, onto, usar_llm=usar_llm)
            d["texto"] = (f"páginas {est.paginas_seleccionadas}, {len(est.valores)} conceptos "
                          f"({sum(c.metodo == 'reglas+llm' for c in est.valores.values())} con acuerdo reglas+LLM)")
            with db.conexion() as con:
                db.guardar_estandarizado(con, documento_id, est)

        with _etapa(documento_id, "preprocesamiento", progreso) as d:
            pre = preprocesar(est, onto)
            d["texto"] = (f"unidad '{pre.metadatos.unidad}', "
                          f"{sum(i.severidad != 'info' for i in pre.incidencias)} incidencias a revisar")

        with _etapa(documento_id, "almacenamiento", progreso) as d:
            with db.conexion() as con:
                db.guardar_preprocesado(con, documento_id, pre)
            d["texto"] = f"{sum(v.valor is not None for v in pre.valores)} valores guardados"

        with _etapa(documento_id, "indexacion", progreso) as d:
            try:
                d["texto"] = f"{m7_consulta.indexar(documento_id)} fragmentos con embeddings"
            except Exception as e:
                d["texto"] = f"sin embeddings ({type(e).__name__}); la consulta usará solo BM25"

        with db.conexion() as con:
            db.actualizar_estado(con, documento_id, "completado")

        with _etapa(documento_id, "accion", progreso) as d:
            mensajes = m8_accion.notificar_incidencias(documento_id)
            m8_accion.reporte_documento(documento_id)
            d["texto"] = f"{mensajes} notificación(es) + reporte"
        return {"documento_id": documento_id, "estado": "completado", "entidad": pre.metadatos.entidad}
    except Exception as e:
        with db.conexion() as con:
            db.actualizar_estado(con, documento_id, "error", f"{type(e).__name__}: {e}")
            db.registrar_evento(con, documento_id, "pipeline", "error", traceback.format_exc()[-2000:])
        m8_accion.enviar(
            responsable=m8_accion.responsable_para("pipeline_error", "error"),
            asunto=f"[NECC] Falló el procesamiento de {doc['nombre_archivo']}",
            cuerpo=f"Error: {type(e).__name__}: {e}\n\nReintentar con \"Reprocesar\" en la pantalla Documento o con "
                   f"`necc procesar {documento_id}`.",
            tipo="notificacion", documento_id=documento_id,
        )
        return {"documento_id": documento_id, "estado": "error", "error": str(e)}
