"""Módulo 8 · Acción: convertir problemas de calidad en tareas concretas para personas.

  - Ruteo: cada incidencia (error / advertencia) se asigna a un responsable según
    config/responsables.yaml (por regla o severidad).
  - Notificación: un mensaje por responsable y documento, con la acción concreta
    sugerida, la página y la evidencia. Canales: bandeja local (siempre),
    Slack (si SLACK_WEBHOOK_URL) y correo (si SMTP_HOST).
  - Etiquetado manual: desde la interfaz se puede asignar/mencionar a alguien en
    una incidencia con una nota.
  - Reportes: por documento (Markdown) y consolidado (Markdown + Excel base).
"""

from __future__ import annotations

import json
import re
import smtplib
import urllib.request
from collections import defaultdict
from datetime import datetime
from email.message import EmailMessage
from functools import lru_cache
from pathlib import Path

import pandas as pd
import yaml

from . import m5_almacenamiento as db
from .config import obtener_config
from .ontologia import obtener_ontologia


@lru_cache(maxsize=1)
def configuracion() -> dict:
    return yaml.safe_load(obtener_config().responsables.read_text(encoding="utf-8"))


def responsable_para(regla: str, severidad: str) -> str:
    for r in configuracion()["ruteo"]:
        if r.get("regla") == regla or (r.get("regla") is None and r.get("severidad") == severidad):
            return r["responsable"]
    return configuracion()["reportes_a"]


def accion_sugerida(regla: str) -> str:
    sugeridas = configuracion()["acciones_sugeridas"]
    return " ".join(str(sugeridas.get(regla, sugeridas["defecto"])).split())


# ------------------------------------------------------------------- canales

def _bandeja(destinatario: str, asunto: str, cuerpo: str) -> str:
    marca = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    slug = re.sub(r"\W+", "_", asunto)[:60]
    ruta = obtener_config().bandeja_salida / f"{marca}_{destinatario}_{slug}.md"
    ruta.write_text(f"Para: {destinatario}\nAsunto: {asunto}\n\n{cuerpo}\n", encoding="utf-8")
    return str(ruta)


def _slack(contacto: dict, asunto: str, cuerpo: str) -> str:
    texto = f"{contacto.get('slack', '')} *{asunto}*\n{cuerpo}"
    req = urllib.request.Request(
        obtener_config().slack_webhook_url, data=json.dumps({"text": texto}).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=10) as r:
        return f"HTTP {r.status}"


def _email(contacto: dict, asunto: str, cuerpo: str) -> str:
    cfg = obtener_config()
    msg = EmailMessage()
    msg["From"], msg["To"], msg["Subject"] = cfg.smtp_remitente, contacto["email"], asunto
    msg.set_content(cuerpo)
    with smtplib.SMTP(cfg.smtp_host, cfg.smtp_puerto, timeout=15) as s:
        s.starttls()
        if cfg.smtp_usuario:
            s.login(cfg.smtp_usuario, cfg.smtp_clave or "")
        s.send_message(msg)
    return "enviado"


def enviar(*, responsable: str, asunto: str, cuerpo: str, tipo: str, documento_id: int | None,
           incidencia_id: int | None = None) -> list[str]:
    """Envía por todos los canales configurados y registra cada envío en la tabla acciones.

    Abre su propia conexión después de enviar: los envíos por red (Slack, SMTP)
    no deben hacerse con una transacción de escritura abierta, porque bloquearían
    la base para el resto de la aplicación. Llamar fuera de `db.conexion()`.
    """
    contacto = configuracion()["responsables"][responsable]
    cfg = obtener_config()
    canales = [("bandeja", lambda: _bandeja(responsable, asunto, cuerpo))]
    if cfg.slack_webhook_url:
        canales.append(("slack", lambda: _slack(contacto, asunto, cuerpo)))
    if cfg.smtp_host and contacto.get("email"):
        canales.append(("email", lambda: _email(contacto, asunto, cuerpo)))
    resultados = []
    for canal, fn in canales:
        try:
            detalle, estado = fn(), "enviada"
        except Exception as e:  # un canal caído no debe frenar los demás
            detalle, estado = f"{type(e).__name__}: {e}", "fallida"
        resultados.append((canal, estado, detalle))
    with db.conexion() as con:
        for canal, estado, detalle in resultados:
            db.registrar_accion(
                con, documento_id=documento_id, incidencia_id=incidencia_id, tipo=tipo, canal=canal,
                destinatario=f"{contacto['nombre']} <{contacto.get('email', '')}>", asunto=asunto, cuerpo=cuerpo,
                estado=estado, detalle=detalle,
            )
    return [f"{canal}:{estado}" for canal, estado, _ in resultados]


# ------------------------------------------------------- acciones automáticas

def _linea_incidencia(i, valor) -> str:
    onto = obtener_ontologia()
    campo = onto.conceptos[i["campo"]].nombre if i["campo"] in onto.conceptos else "Documento"
    lineas = [f"[{i['severidad'].upper()}] {campo}: {i['mensaje']}"]
    if valor is not None and valor["pagina"]:
        lineas.append(f"   Página {valor['pagina']} · evidencia: \"{(valor['evidencia'] or '')[:200]}\"")
    lineas.append(f"   ➜ Acción: {accion_sugerida(i['regla'])}")
    return "\n".join(lineas)


def notificar_incidencias(documento_id: int) -> int:
    """Asigna y notifica las incidencias abiertas aún no asignadas. Devuelve cuántos mensajes se enviaron."""
    severidades = set(configuracion()["notificar"])
    with db.conexion() as con:
        doc = db.obtener_documento(con, documento_id)
        valores = {v["campo"]: v for v in db.listar_valores(con, documento_id)}
        pendientes = [
            i for i in db.listar_incidencias(con, "abierta", documento_id)
            if i["responsable"] is None and i["severidad"] in severidades
        ]
        por_responsable = defaultdict(list)
        for i in pendientes:
            resp = responsable_para(i["regla"], i["severidad"])
            db.asignar_incidencia(con, i["id"], resp)
            por_responsable[resp].append(i)

    entidad = doc["entidad"] or doc["nombre_archivo"]
    for resp, incidencias in por_responsable.items():
        asunto = f"[NECC] {len(incidencias)} punto(s) a revisar · {entidad} · {doc['fecha_balance'] or ''}"
        cuerpo = (
            f"Hola {configuracion()['responsables'][resp]['nombre']},\n\n"
            f"El procesamiento automático de '{doc['nombre_archivo']}' (documento #{documento_id}) "
            f"detectó lo siguiente:\n\n"
            + "\n\n".join(_linea_incidencia(i, valores.get(i["campo"])) for i in incidencias)
            + "\n\nRevisalo en la interfaz web → Documento / Acciones."
        )
        enviar(responsable=resp, asunto=asunto, cuerpo=cuerpo, tipo="notificacion",
               documento_id=documento_id, incidencia_id=incidencias[0]["id"] if len(incidencias) == 1 else None)
    return len(por_responsable)


def etiquetar(incidencia_id: int, responsable: str, nota: str, autor: str) -> list[str]:
    """Mención manual: asigna la incidencia a alguien y le envía el pedido."""
    if responsable not in configuracion()["responsables"]:
        raise ValueError(f"Responsable desconocido: {responsable}")
    with db.conexion() as con:
        i = db.obtener_incidencia(con, incidencia_id)
        db.asignar_incidencia(con, incidencia_id, responsable)
        valor = next((v for v in db.listar_valores(con, i["documento_id"]) if v["campo"] == i["campo"]), None)
    asunto = f"[NECC] {autor} te etiquetó · {i['entidad'] or i['nombre_archivo']}"
    cuerpo = f"{autor} escribió: {nota}\n\n{_linea_incidencia(i, valor)}"
    return enviar(responsable=responsable, asunto=asunto, cuerpo=cuerpo, tipo="etiqueta",
                  documento_id=i["documento_id"], incidencia_id=incidencia_id)


# ----------------------------------------------------------------- reportes

def _monto(v: float | None, tipo: str) -> str:
    if v is None:
        return "—"
    if tipo == "ratio":
        return f"{v:.4f}"
    return f"{v:,.0f}".replace(",", ".")


def reporte_documento(documento_id: int, notificar: bool = True) -> Path:
    onto = obtener_ontologia()
    with db.conexion() as con:
        doc = db.obtener_documento(con, documento_id)
        valores = {v["campo"]: v for v in db.listar_valores(con, documento_id)}
        a_revisar = [i for i in db.listar_incidencias(con, "abierta", documento_id) if i["severidad"] != "info"]
    filas = []
    for c in onto.campos:
        v = valores.get(c.id)
        filas.append(
            f"| {c.nombre} | {_monto(v['valor'] if v else None, c.tipo)} | {v['estado'] if v else 'faltante'} "
            f"| {v['metodo'] if v else '—'} | {v['pagina'] if v and v['pagina'] else '—'} "
            f"| {v['confianza'] if v else '—'} |"
        )
    texto = "\n".join([
        f"# Reporte de extracción · {doc['entidad'] or doc['nombre_archivo']}",
        "",
        f"- Archivo: `{doc['nombre_archivo']}` (documento #{documento_id})",
        f"- Fecha de balance: {doc['fecha_balance'] or '—'}",
        f"- Unidad de origen: {doc['unidad'] or '—'} · montos expresados en **pesos**",
        f"- Páginas analizadas: {doc['paginas_seleccionadas'] or '—'} de {doc['paginas']}",
        "",
        "| Campo | Valor | Estado | Método | Pág. | Confianza |",
        "|---|---:|---|---|---:|---:|",
        *filas,
        "",
        f"## Incidencias a revisar ({len(a_revisar)})",
        "",
        *([f"- **{i['severidad']}** · {i['mensaje']} (responsable: {i['responsable'] or 'sin asignar'})"
           for i in a_revisar] or ["Ninguna."]),
        "",
        f"_Generado {db.ahora()}_",
    ])
    ruta = obtener_config().reportes / f"reporte_doc{documento_id}.md"
    ruta.write_text(texto, encoding="utf-8")
    if notificar:
        enviar(responsable=configuracion()["reportes_a"],
               asunto=f"[NECC] Reporte · {doc['entidad'] or doc['nombre_archivo']}",
               cuerpo=texto, tipo="reporte", documento_id=documento_id)
    return ruta


def reporte_consolidado(notificar: bool = True) -> tuple[Path, Path]:
    """Resumen de todas las entidades + Excel base; se envía al responsable de reportes."""
    onto = obtener_ontologia()
    requeridos = [c for c in onto.campos if c.requerido]
    with db.conexion() as con:
        base = db.tabla_base(con)
        excel = db.exportar_excel(con, obtener_config().reportes / "excel_base.xlsx")
        a_revisar = sum(i["severidad"] != "info" for i in db.listar_incidencias(con, "abierta"))
    filas = [
        f"| {r['entidad'] or r['nombre_archivo']} | "
        + " | ".join(_monto(None if pd.isna(r[c.id]) else r[c.id], c.tipo) for c in requeridos)
        + " |"
        for _, r in base.iterrows()
    ]
    texto = "\n".join([
        "# Reporte consolidado · Litigiosidad ART",
        "",
        f"Documentos completados: {len(base)} · incidencias a revisar: {a_revisar}",
        "",
        "| Entidad | " + " | ".join(c.nombre for c in requeridos) + " |",
        "|---|" + "---:|" * len(requeridos),
        *filas,
        "",
        f"Excel base adjunto: `{excel.name}`",
    ])
    ruta = obtener_config().reportes / "reporte_consolidado.md"
    ruta.write_text(texto, encoding="utf-8")
    if notificar:
        enviar(responsable=configuracion()["reportes_a"], asunto="[NECC] Reporte consolidado",
               cuerpo=texto, tipo="reporte", documento_id=None)
    return ruta, excel
