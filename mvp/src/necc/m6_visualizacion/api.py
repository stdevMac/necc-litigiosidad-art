"""Módulo 6 · Visualización — API HTTP para la interfaz web (React, carpeta `web/`).

La API solo traduce HTTP a los módulos del pipeline; no contiene lógica de negocio.
El procesamiento corre en segundo plano (un documento a la vez) y la interfaz
consulta su avance leyendo la bitácora de etapas.

Ejecutar con `uv run necc ui` (sirve también la interfaz compilada en web/dist).
"""

from __future__ import annotations

import json
import logging
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from pathlib import Path

import pymupdf
from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from necc import llm
from necc import m1_descubrimiento as m1
from necc import m5_almacenamiento as db
from necc import m7_consulta, m8_accion, pipeline
from necc.config import obtener_config
from necc.ontologia import obtener_ontologia

log = logging.getLogger(__name__)

ETAPAS = ["procesamiento", "estandarizacion", "preprocesamiento", "almacenamiento", "indexacion", "accion"]
WEB_DIST = obtener_config().raiz / "web" / "dist"

_cola = ThreadPoolExecutor(max_workers=1, thread_name_prefix="pipeline")
_esperando: set[int] = set()  # encolados que todavía no empezaron (evita encolar dos veces)
_candado = threading.Lock()


@asynccontextmanager
async def _ciclo_de_vida(_app: FastAPI):
    # Documentos que quedaron a mitad de camino si el servidor se detuvo: se reencolan.
    with db.conexion() as con:
        interrumpidos = [d["id"] for d in db.listar_documentos(con, ("en_cola", "procesando"))]
    _encolar(interrumpidos)
    yield
    _cola.shutdown(wait=False, cancel_futures=True)


app = FastAPI(title="NECC · Litigiosidad ART", lifespan=_ciclo_de_vida)

# Demo pública: solo lectura. Toda petición que no sea de lectura se rechaza acá, en un único
# lugar, salvo las que figuran en la lista de permitidas (la consulta en lenguaje natural).
METODOS_LECTURA = {"GET", "HEAD", "OPTIONS"}
PERMITIDAS_EN_DEMO = {("POST", "/api/consulta")}
MAX_PREGUNTA_DEMO = 500


@app.middleware("http")
async def _solo_lectura_en_demo(request: Request, call_next):
    if (
        obtener_config().demo
        and request.method not in METODOS_LECTURA
        and (request.method, request.url.path) not in PERMITIDAS_EN_DEMO
    ):
        return JSONResponse(
            {"detail": "Demo pública de solo lectura: esta acción está deshabilitada."}, status_code=403
        )
    return await call_next(request)


@app.get("/api/config")
def configuracion() -> dict:
    return {"demo": obtener_config().demo}


def _ejecutar(documento_id: int) -> None:
    with _candado:
        _esperando.discard(documento_id)
    try:
        pipeline.procesar_documento(documento_id)
    except Exception:
        log.exception("Falló el procesamiento del documento %s", documento_id)


def _encolar(ids: list[int]) -> None:
    with _candado:
        nuevos = [i for i in dict.fromkeys(ids) if i not in _esperando]
        _esperando.update(nuevos)
    with db.conexion() as con:
        for i in nuevos:
            db.actualizar_estado(con, i, "en_cola")
    for i in nuevos:
        _cola.submit(_ejecutar, i)


def _documento(con, documento_id: int):
    try:
        return db.obtener_documento(con, documento_id)
    except KeyError as e:
        raise HTTPException(404, f"Documento {documento_id} inexistente") from e


# ---------------------------------------------------------------- documentos

def _resumen_documento(con, d) -> dict:
    a_revisar = sum(i["severidad"] != "info" for i in db.listar_incidencias(con, "abierta", d["id"]))
    return {
        "id": d["id"], "archivo": d["nombre_archivo"], "entidad": d["entidad"], "estado": d["estado"],
        "fecha_balance": d["fecha_balance"], "unidad": d["unidad"], "paginas": d["paginas"], "origen": d["origen"],
        "a_revisar": a_revisar, "error": d["error"], "actualizado_en": d["actualizado_en"],
    }


@app.get("/api/documentos")
def listar_documentos() -> list[dict]:
    with db.conexion() as con:
        return [_resumen_documento(con, d) for d in reversed(db.listar_documentos(con))]


@app.post("/api/documentos")
def subir_documentos(archivos: list[UploadFile] = File(...)) -> list[dict]:
    """Valida todo el lote antes de registrar: o entran todos, o ninguno."""
    lote = [(a.file.read(), a.filename or "documento.pdf") for a in archivos]
    try:
        for contenido, nombre in lote:
            m1.validar(contenido, nombre)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    resultados = []
    for contenido, nombre in lote:
        d = m1.registrar_bytes(contenido, nombre, "subida")
        resultados.append({"id": d.documento_id, "archivo": d.nombre, "nuevo": d.nuevo})
    _encolar([r["id"] for r in resultados if r["nuevo"]])
    return resultados


@app.post("/api/descubrir")
def descubrir_inbox() -> list[dict]:
    encontrados = m1.descubrir()
    _encolar([d.documento_id for d in encontrados if d.nuevo])
    return [{"id": d.documento_id, "archivo": d.nombre, "nuevo": d.nuevo} for d in encontrados]


@app.post("/api/documentos/{documento_id}/procesar")
def reprocesar(documento_id: int) -> dict:
    with db.conexion() as con:
        _documento(con, documento_id)
    _encolar([documento_id])
    return {"id": documento_id, "estado": "en_cola"}


def _progreso(con, documento_id: int) -> list[dict]:
    eventos = con.execute(
        "SELECT etapa, estado, detalle, duracion_ms FROM eventos WHERE documento_id = ? ORDER BY id", (documento_id,)
    ).fetchall()
    inicio = max((k for k, e in enumerate(eventos) if e["etapa"] == "pipeline" and e["estado"] == "inicio"),
                 default=-1)
    hechas = {e["etapa"]: e for e in eventos[inicio + 1 :] if e["etapa"] in ETAPAS}
    return [
        {"etapa": etapa, "estado": hechas[etapa]["estado"] if etapa in hechas else "pendiente",
         "detalle": hechas[etapa]["detalle"] if etapa in hechas else "",
         "segundos": round((hechas[etapa]["duracion_ms"] or 0) / 1000, 1) if etapa in hechas else None}
        for etapa in ETAPAS
    ]


@app.get("/api/documentos/{documento_id}")
def detalle_documento(documento_id: int) -> dict:
    onto = obtener_ontologia()
    with db.conexion() as con:
        d = _documento(con, documento_id)
        valores = {v["campo"]: dict(v) for v in db.listar_valores(con, documento_id)}
        lecturas: dict[str, list[dict]] = {}
        for e in db.listar_extracciones(con, documento_id):
            lecturas.setdefault(e["concepto"], []).append({
                "metodo": e["metodo"], "valor_texto": e["valor_texto"], "pagina": e["pagina"],
                "confianza": e["confianza"], "verificado": bool(e["verificado"]), "elegido": bool(e["elegido"]),
            })
        campos = []
        for c in onto.campos + onto.componentes:
            v = valores.get(c.id)
            if v is None and c.es_componente:
                continue
            campos.append({
                "campo": c.id, "nombre": c.nombre, "tipo": c.tipo, "requerido": c.requerido,
                "componente": c.es_componente, "norma": c.norma,
                "valor": v["valor"] if v else None, "valor_origen": v["valor_origen"] if v else None,
                "metodo": v["metodo"] if v else "faltante", "pagina": v["pagina"] if v else None,
                "evidencia": v["evidencia"] if v else "", "confianza": v["confianza"] if v else 0,
                "estado": v["estado"] if v else "faltante", "corregido_por": v["corregido_por"] if v else None,
                "comentario": v["comentario"] if v else None, "lecturas": lecturas.get(c.id, []),
            })
        incidencias = [
            {"id": i["id"], "campo": i["campo"], "regla": i["regla"], "severidad": i["severidad"],
             "mensaje": i["mensaje"], "estado": i["estado"], "responsable": i["responsable"],
             "accion_sugerida": m8_accion.accion_sugerida(i["regla"])}
            for i in db.listar_incidencias(con, None, documento_id)
        ]
        return {
            **_resumen_documento(con, d),
            "evidencia_unidad": d["evidencia_unidad"],
            "paginas_seleccionadas": json.loads(d["paginas_seleccionadas"] or "[]"),
            "campos": campos,
            "incidencias": incidencias,
            "progreso": _progreso(con, documento_id),
        }


@app.get("/api/documentos/{documento_id}/paginas/{numero}")
def imagen_pagina(documento_id: int, numero: int, resaltar: str | None = None, recorte: bool = False) -> Response:
    """Página renderizada como PNG, con el valor resaltado si aparece como texto.

    Con `recorte=true` devuelve solo la franja de la página alrededor del valor
    (para leerlo de un vistazo); si el valor no se encuentra, la página entera.
    """
    with db.conexion() as con:
        ruta = Path(_documento(con, documento_id)["ruta"])
    if not ruta.is_file():
        raise HTTPException(404, "El archivo original ya no está en el almacén de documentos")
    with pymupdf.open(ruta) as doc:
        if not 1 <= numero <= len(doc):
            raise HTTPException(404, "Página inexistente")
        pagina = doc[numero - 1]
        buscado = resaltar.strip().lstrip("$").strip() if resaltar else ""
        hallados = pagina.search_for(buscado) if buscado else []
        for rect in hallados:
            pagina.add_highlight_annot(rect)
        clip = None
        if recorte and hallados:
            r = hallados[0]
            clip = pymupdf.Rect(max(pagina.rect.x0, r.x0 - 300), max(pagina.rect.y0, r.y0 - 90),
                                min(pagina.rect.x1, r.x1 + 120), min(pagina.rect.y1, r.y1 + 90))
        png = pagina.get_pixmap(dpi=170 if clip else 130, clip=clip).tobytes("png")
    return Response(png, media_type="image/png")


@app.get("/api/documentos/{documento_id}/archivo")
def archivo_original(documento_id: int) -> FileResponse:
    with db.conexion() as con:
        d = _documento(con, documento_id)
    if not Path(d["ruta"]).is_file():
        raise HTTPException(404, "El archivo original ya no está en el almacén de documentos")
    return FileResponse(d["ruta"], filename=d["nombre_archivo"])


class Revision(BaseModel):
    usuario: str
    comentario: str = ""
    valor: float | None = None


def _validar_campo(con, documento_id: int, campo: str) -> None:
    _documento(con, documento_id)
    if campo not in obtener_ontologia().conceptos:
        raise HTTPException(404, f"Campo inexistente: {campo}")


@app.post("/api/documentos/{documento_id}/valores/{campo}/aprobar")
def aprobar(documento_id: int, campo: str, r: Revision) -> dict:
    with db.conexion() as con:
        _validar_campo(con, documento_id, campo)
        db.aprobar_valor(con, documento_id, campo, r.usuario, r.comentario)
    return {"ok": True}


@app.post("/api/documentos/{documento_id}/valores/{campo}/corregir")
def corregir(documento_id: int, campo: str, r: Revision) -> dict:
    if r.valor is None:
        raise HTTPException(400, "Falta el valor corregido")
    with db.conexion() as con:
        _validar_campo(con, documento_id, campo)
        db.corregir_valor(con, documento_id, campo, r.valor, r.usuario, r.comentario)
    return {"ok": True}


# ------------------------------------------------------------------- tablero

def _numero(x) -> float | None:
    return None if x is None or x != x else float(x)  # NaN -> None


@app.get("/api/tablero")
def tablero() -> dict:
    onto = obtener_ontologia()
    with db.conexion() as con:
        base = db.tabla_base(con)
        a_revisar = sum(i["severidad"] != "info" for i in db.listar_incidencias(con, "abierta"))
    filas = []
    for _, r in base.iterrows():
        v = {c.id: _numero(r[c.id]) for c in onto.campos}
        juicios, reserva = v["juicios_abiertos"], v["reserva_reclamaciones_judiciales"]
        filas.append({
            "documento_id": int(r["documento_id"]), "entidad": r["entidad"], "fecha_balance": r["fecha_balance"],
            "valores": v,
            "reserva_por_juicio": reserva / juicios if reserva and juicios else None,
            "pct_con_pagos_parciales": (v["juicios_con_pagos_parciales"] / juicios
                                        if v["juicios_con_pagos_parciales"] is not None and juicios else None),
        })
    return {
        "campos": [{"campo": c.id, "nombre": c.nombre, "tipo": c.tipo, "requerido": c.requerido} for c in onto.campos],
        "filas": filas,
        "kpis": {
            "entidades": len(filas),
            "juicios_abiertos": sum(f["valores"]["juicios_abiertos"] or 0 for f in filas),
            "reserva_total": sum(f["valores"]["reserva_reclamaciones_judiciales"] or 0 for f in filas),
            "a_revisar": a_revisar,
        },
    }


@app.get("/api/exportar")
def exportar() -> Response:
    with tempfile.TemporaryDirectory() as tmp, db.conexion() as con:
        datos = db.exportar_excel(con, Path(tmp) / "excel_base.xlsx").read_bytes()
    return Response(
        datos, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="excel_base.xlsx"'},
    )


# ------------------------------------------------------------------- consulta

class Pregunta(BaseModel):
    pregunta: str
    documento_ids: list[int] | None = None


@app.post("/api/consulta")
def consultar(p: Pregunta) -> dict:
    if not p.pregunta.strip():
        raise HTTPException(400, "La pregunta está vacía.")
    if obtener_config().demo and len(p.pregunta) > MAX_PREGUNTA_DEMO:
        raise HTTPException(400, f"En la demo pública la pregunta puede tener hasta {MAX_PREGUNTA_DEMO} caracteres.")
    if not llm.disponible():
        raise HTTPException(503, "Falta GEMINI_API_KEY: la consulta necesita el LLM.")
    try:
        respuesta, fuentes = m7_consulta.responder(p.pregunta.strip(), p.documento_ids or None)
    except Exception as e:
        log.exception("Falló la consulta")
        raise HTTPException(502, f"El LLM no respondió ({type(e).__name__}). Reintentar en unos segundos.") from e
    return {"respuesta": respuesta, "fuentes": [f.como_dict() for f in fuentes]}


# ------------------------------------------------------------------- acciones

@app.get("/api/responsables")
def responsables() -> list[dict]:
    return [{"id": k, **v} for k, v in m8_accion.configuracion()["responsables"].items()]


@app.get("/api/incidencias")
def incidencias(estado: str = "abierta") -> list[dict]:
    onto = obtener_ontologia()
    with db.conexion() as con:
        filas = db.listar_incidencias(con, estado or None)
    return [
        {"id": i["id"], "documento_id": i["documento_id"], "entidad": i["entidad"] or i["nombre_archivo"],
         "campo": i["campo"], "campo_nombre": onto.conceptos[i["campo"]].nombre if i["campo"] in onto.conceptos else None,
         "regla": i["regla"], "severidad": i["severidad"], "mensaje": i["mensaje"], "estado": i["estado"],
         "responsable": i["responsable"], "accion_sugerida": m8_accion.accion_sugerida(i["regla"]),
         "creado_en": i["creado_en"]}
        for i in filas if i["severidad"] != "info"
    ]


class Etiqueta(BaseModel):
    responsable: str
    nota: str
    autor: str


@app.post("/api/incidencias/{incidencia_id}/etiquetar")
def etiquetar(incidencia_id: int, e: Etiqueta) -> dict:
    try:
        return {"canales": m8_accion.etiquetar(incidencia_id, e.responsable, e.nota, e.autor)}
    except KeyError as err:
        raise HTTPException(404, f"Incidencia {incidencia_id} inexistente") from err
    except ValueError as err:
        raise HTTPException(400, str(err)) from err


class Cierre(BaseModel):
    estado: str  # resuelta | descartada
    usuario: str
    comentario: str = ""


@app.post("/api/incidencias/{incidencia_id}/resolver")
def resolver(incidencia_id: int, c: Cierre) -> dict:
    if c.estado not in ("resuelta", "descartada"):
        raise HTTPException(400, "estado debe ser 'resuelta' o 'descartada'")
    with db.conexion() as con:
        try:
            db.obtener_incidencia(con, incidencia_id)
        except KeyError as e:
            raise HTTPException(404, f"Incidencia {incidencia_id} inexistente") from e
        db.resolver_incidencia(con, incidencia_id, c.estado, c.usuario, c.comentario)
    return {"ok": True}


@app.get("/api/acciones")
def acciones() -> list[dict]:
    with db.conexion() as con:
        return [
            {k: a[k] for k in ("id", "documento_id", "tipo", "canal", "destinatario", "asunto", "cuerpo", "estado",
                               "creado_en")}
            for a in db.listar_acciones(con)[:100]
        ]


@app.post("/api/reportes/consolidado")
def reporte_consolidado() -> dict:
    md, _ = m8_accion.reporte_consolidado()
    return {"markdown": md.read_text(encoding="utf-8")}


# ------------------------------------------------------- interfaz compilada

if WEB_DIST.exists():
    app.mount("/assets", StaticFiles(directory=WEB_DIST / "assets"), name="assets")
    _RAIZ_WEB = WEB_DIST.resolve()

    @app.get("/{ruta:path}", include_in_schema=False)
    def spa(ruta: str) -> FileResponse:
        if ruta.startswith("api/"):
            raise HTTPException(404, "Ruta de API inexistente")
        archivo = (_RAIZ_WEB / ruta).resolve()
        if ruta and archivo.is_file() and archivo.is_relative_to(_RAIZ_WEB):
            return FileResponse(archivo)
        return FileResponse(_RAIZ_WEB / "index.html")
