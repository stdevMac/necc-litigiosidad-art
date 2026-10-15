"""Módulo 5 · Almacenamiento.

SQLite como base del POC (un archivo, sin servidor) y exportación al "Excel base".
Todas las escrituras de los demás módulos pasan por acá.

Tablas:
  documentos   registro de cada archivo (hash, estado del pipeline, metadatos)
  paginas      texto limpio por página (+ método: texto / ocr)
  fragmentos   chunks para la consulta (+ embedding)
  extracciones candidatos por método (reglas / llm) con evidencia: auditoría
  valores      valor estandarizado final por documento y campo (Excel base)
  incidencias  problemas de calidad detectados (reglas de la ontología)
  acciones     notificaciones / tareas / reportes emitidos
  eventos      bitácora de ejecución del pipeline
  consultas    registro de preguntas y respuestas (auditoría)
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Iterator

import numpy as np
import pandas as pd

from .config import obtener_config
from .modelos import DocumentoProcesado, Estandarizado, Preprocesado
from .ontologia import obtener_ontologia

ESQUEMA = """
CREATE TABLE IF NOT EXISTS documentos (
    id INTEGER PRIMARY KEY,
    sha256 TEXT UNIQUE NOT NULL,
    nombre_archivo TEXT NOT NULL,
    ruta TEXT NOT NULL,
    origen TEXT NOT NULL,
    estado TEXT NOT NULL DEFAULT 'descubierto',
    entidad TEXT,
    fecha_balance TEXT,
    unidad TEXT,
    evidencia_unidad TEXT,
    paginas INTEGER,
    paginas_seleccionadas TEXT,
    encabezados TEXT,
    error TEXT,
    creado_en TEXT NOT NULL,
    actualizado_en TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS paginas (
    documento_id INTEGER NOT NULL REFERENCES documentos(id) ON DELETE CASCADE,
    numero INTEGER NOT NULL,
    texto TEXT NOT NULL,
    metodo TEXT NOT NULL,
    PRIMARY KEY (documento_id, numero)
);
CREATE TABLE IF NOT EXISTS fragmentos (
    id INTEGER PRIMARY KEY,
    documento_id INTEGER NOT NULL REFERENCES documentos(id) ON DELETE CASCADE,
    pagina INTEGER NOT NULL,
    orden INTEGER NOT NULL,
    texto TEXT NOT NULL,
    embedding BLOB
);
CREATE TABLE IF NOT EXISTS extracciones (
    id INTEGER PRIMARY KEY,
    documento_id INTEGER NOT NULL REFERENCES documentos(id) ON DELETE CASCADE,
    concepto TEXT NOT NULL,
    metodo TEXT NOT NULL,
    valor_texto TEXT,
    valor REAL,
    pagina INTEGER,
    evidencia TEXT,
    confianza REAL,
    verificado INTEGER,
    elegido INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS valores (
    documento_id INTEGER NOT NULL REFERENCES documentos(id) ON DELETE CASCADE,
    campo TEXT NOT NULL,
    valor REAL,
    valor_origen REAL,
    unidad_origen TEXT,
    metodo TEXT,
    pagina INTEGER,
    evidencia TEXT,
    confianza REAL,
    estado TEXT NOT NULL,
    corregido_por TEXT,
    comentario TEXT,
    actualizado_en TEXT NOT NULL,
    PRIMARY KEY (documento_id, campo)
);
CREATE TABLE IF NOT EXISTS incidencias (
    id INTEGER PRIMARY KEY,
    documento_id INTEGER NOT NULL REFERENCES documentos(id) ON DELETE CASCADE,
    campo TEXT,
    regla TEXT NOT NULL,
    severidad TEXT NOT NULL,
    mensaje TEXT NOT NULL,
    estado TEXT NOT NULL DEFAULT 'abierta',
    responsable TEXT,
    resuelta_por TEXT,
    comentario TEXT,
    creado_en TEXT NOT NULL,
    resuelta_en TEXT
);
CREATE TABLE IF NOT EXISTS acciones (
    id INTEGER PRIMARY KEY,
    documento_id INTEGER REFERENCES documentos(id) ON DELETE CASCADE,
    incidencia_id INTEGER REFERENCES incidencias(id) ON DELETE SET NULL,
    tipo TEXT NOT NULL,
    canal TEXT NOT NULL,
    destinatario TEXT NOT NULL,
    asunto TEXT NOT NULL,
    cuerpo TEXT NOT NULL,
    estado TEXT NOT NULL,
    detalle TEXT,
    creado_en TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS eventos (
    id INTEGER PRIMARY KEY,
    documento_id INTEGER REFERENCES documentos(id) ON DELETE CASCADE,
    etapa TEXT NOT NULL,
    estado TEXT NOT NULL,
    detalle TEXT,
    duracion_ms INTEGER,
    creado_en TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS consultas (
    id INTEGER PRIMARY KEY,
    pregunta TEXT NOT NULL,
    respuesta TEXT NOT NULL,
    fuentes TEXT NOT NULL,
    creado_en TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_fragmentos_doc ON fragmentos(documento_id);
CREATE INDEX IF NOT EXISTS ix_incidencias_estado ON incidencias(estado);
"""


def ahora() -> str:
    return datetime.now().isoformat(timespec="seconds")


@contextmanager
def conexion(ruta: Path | None = None) -> Iterator[sqlite3.Connection]:
    con = sqlite3.connect(ruta or obtener_config().base_datos, timeout=30)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    con.execute("PRAGMA journal_mode = WAL")
    con.executescript(ESQUEMA)
    try:
        yield con
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


# ---------------------------------------------------------------- documentos

def registrar_documento(con, sha256: str, nombre: str, ruta: str, origen: str) -> tuple[int, bool]:
    """Devuelve (id, es_nuevo). Un mismo archivo (mismo hash) nunca se duplica."""
    fila = con.execute("SELECT id FROM documentos WHERE sha256 = ?", (sha256,)).fetchone()
    if fila:
        return fila["id"], False
    cur = con.execute(
        "INSERT INTO documentos (sha256, nombre_archivo, ruta, origen, creado_en, actualizado_en)"
        " VALUES (?, ?, ?, ?, ?, ?)",
        (sha256, nombre, ruta, origen, ahora(), ahora()),
    )
    return cur.lastrowid, True


def obtener_documento(con, documento_id: int) -> sqlite3.Row:
    fila = con.execute("SELECT * FROM documentos WHERE id = ?", (documento_id,)).fetchone()
    if fila is None:
        raise KeyError(f"Documento {documento_id} inexistente")
    return fila


def listar_documentos(con, estados: tuple[str, ...] | None = None) -> list[sqlite3.Row]:
    if estados:
        marcas = ",".join("?" * len(estados))
        return con.execute(f"SELECT * FROM documentos WHERE estado IN ({marcas}) ORDER BY id", estados).fetchall()
    return con.execute("SELECT * FROM documentos ORDER BY id").fetchall()


def actualizar_estado(con, documento_id: int, estado: str, error: str | None = None) -> None:
    con.execute(
        "UPDATE documentos SET estado = ?, error = ?, actualizado_en = ? WHERE id = ?",
        (estado, error, ahora(), documento_id),
    )


def registrar_evento(con, documento_id: int | None, etapa: str, estado: str, detalle: str = "", duracion_ms: int = 0):
    con.execute(
        "INSERT INTO eventos (documento_id, etapa, estado, detalle, duracion_ms, creado_en) VALUES (?, ?, ?, ?, ?, ?)",
        (documento_id, etapa, estado, detalle, duracion_ms, ahora()),
    )


# ------------------------------------------------------------ procesamiento

def guardar_procesado(con, documento_id: int, doc: DocumentoProcesado) -> None:
    con.execute("DELETE FROM paginas WHERE documento_id = ?", (documento_id,))
    con.execute("DELETE FROM fragmentos WHERE documento_id = ?", (documento_id,))
    con.executemany(
        "INSERT INTO paginas (documento_id, numero, texto, metodo) VALUES (?, ?, ?, ?)",
        [(documento_id, p.numero, p.texto, p.metodo) for p in doc.paginas],
    )
    con.executemany(
        "INSERT INTO fragmentos (documento_id, pagina, orden, texto) VALUES (?, ?, ?, ?)",
        [(documento_id, f.pagina, f.orden, f.texto) for f in doc.fragmentos],
    )
    con.execute(
        "UPDATE documentos SET paginas = ?, encabezados = ?, actualizado_en = ? WHERE id = ?",
        (len(doc.paginas), json.dumps(doc.encabezados, ensure_ascii=False), ahora(), documento_id),
    )


# ---------------------------------------------------------- estandarización

def guardar_estandarizado(con, documento_id: int, est: Estandarizado) -> None:
    con.execute("DELETE FROM extracciones WHERE documento_id = ?", (documento_id,))
    elegidos = {id(c) for c in est.valores.values()}
    con.executemany(
        "INSERT INTO extracciones (documento_id, concepto, metodo, valor_texto, valor, pagina, evidencia,"
        " confianza, verificado, elegido) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            (documento_id, c.concepto, c.metodo, c.valor_texto, c.valor, c.pagina, c.evidencia,
             c.confianza, int(c.verificado), int(id(c) in elegidos))
            for c in est.candidatos + [v for v in est.valores.values() if v.metodo == "reglas+llm"]
        ],
    )
    m = est.metadatos
    con.execute(
        "UPDATE documentos SET entidad = ?, fecha_balance = ?, unidad = ?, evidencia_unidad = ?,"
        " paginas_seleccionadas = ?, actualizado_en = ? WHERE id = ?",
        (m.entidad, m.fecha_balance, m.unidad, m.evidencia_unidad, json.dumps(est.paginas_seleccionadas),
         ahora(), documento_id),
    )


def listar_extracciones(con, documento_id: int) -> list[sqlite3.Row]:
    return con.execute(
        "SELECT * FROM extracciones WHERE documento_id = ? ORDER BY concepto, metodo", (documento_id,)
    ).fetchall()


# ----------------------------------------------------------- pre-procesado

def guardar_preprocesado(con, documento_id: int, pre: Preprocesado) -> None:
    """Persiste valores e incidencias. Las correcciones humanas se respetan al reprocesar;
    el resto de los valores del procesamiento anterior se reemplaza (incluidos componentes
    que esta vez no aparecieron)."""
    con.execute("UPDATE documentos SET unidad = ? WHERE id = ?", (pre.metadatos.unidad, documento_id))
    corregidos = {
        r["campo"]
        for r in con.execute(
            "SELECT campo FROM valores WHERE documento_id = ? AND estado = 'corregido'", (documento_id,)
        )
    }
    con.execute("DELETE FROM valores WHERE documento_id = ? AND estado != 'corregido'", (documento_id,))
    con.executemany(
        "INSERT INTO valores (documento_id, campo, valor, valor_origen, unidad_origen, metodo,"
        " pagina, evidencia, confianza, estado, actualizado_en) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            (documento_id, v.campo, v.valor, v.valor_origen, v.unidad_origen, v.metodo, v.pagina,
             v.evidencia, v.confianza, v.estado, ahora())
            for v in pre.valores
            if v.campo not in corregidos
        ],
    )
    con.execute("DELETE FROM incidencias WHERE documento_id = ? AND estado = 'abierta'", (documento_id,))
    con.executemany(
        "INSERT INTO incidencias (documento_id, campo, regla, severidad, mensaje, creado_en) VALUES (?, ?, ?, ?, ?, ?)",
        [
            (documento_id, i.campo, i.regla, i.severidad, i.mensaje, ahora())
            for i in pre.incidencias
            if i.campo not in corregidos
        ],
    )


def corregir_valor(con, documento_id: int, campo: str, valor: float, usuario: str, comentario: str = "") -> None:
    """Corrección humana (human-in-the-loop): queda auditada y cierra las incidencias del campo."""
    con.execute(
        "INSERT INTO valores (documento_id, campo, valor, metodo, estado, confianza, corregido_por, comentario,"
        " actualizado_en, unidad_origen, evidencia) VALUES (?, ?, ?, 'manual', 'corregido', 1.0, ?, ?, ?, 'pesos', '')"
        " ON CONFLICT(documento_id, campo) DO UPDATE SET valor = excluded.valor, metodo = 'manual',"
        " estado = 'corregido', confianza = 1.0, corregido_por = excluded.corregido_por,"
        " comentario = excluded.comentario, actualizado_en = excluded.actualizado_en",
        (documento_id, campo, valor, usuario, comentario, ahora()),
    )
    con.execute(
        "UPDATE incidencias SET estado = 'resuelta', resuelta_por = ?, comentario = ?, resuelta_en = ?"
        " WHERE documento_id = ? AND campo = ? AND estado = 'abierta'",
        (usuario, f"Valor corregido manualmente. {comentario}".strip(), ahora(), documento_id, campo),
    )
    registrar_evento(con, documento_id, "correccion_manual", "ok", f"{campo}={valor} por {usuario}")


def aprobar_valor(con, documento_id: int, campo: str, usuario: str, comentario: str = "") -> None:
    con.execute(
        "UPDATE valores SET estado = 'corregido', corregido_por = ?, comentario = ?, actualizado_en = ?"
        " WHERE documento_id = ? AND campo = ?",
        (usuario, comentario or "Valor validado", ahora(), documento_id, campo),
    )
    con.execute(
        "UPDATE incidencias SET estado = 'resuelta', resuelta_por = ?, comentario = ?, resuelta_en = ?"
        " WHERE documento_id = ? AND campo = ? AND estado = 'abierta'",
        (usuario, comentario or "Valor validado", ahora(), documento_id, campo),
    )
    registrar_evento(con, documento_id, "validacion_manual", "ok", f"{campo} aprobado por {usuario}")


def listar_valores(con, documento_id: int) -> list[sqlite3.Row]:
    return con.execute("SELECT * FROM valores WHERE documento_id = ?", (documento_id,)).fetchall()


# --------------------------------------------------------------- incidencias

def listar_incidencias(con, estado: str | None = "abierta", documento_id: int | None = None) -> list[sqlite3.Row]:
    sql = (
        "SELECT i.*, d.nombre_archivo, d.entidad FROM incidencias i JOIN documentos d ON d.id = i.documento_id"
        " WHERE 1=1"
    )
    params: list = []
    if estado:
        sql += " AND i.estado = ?"
        params.append(estado)
    if documento_id:
        sql += " AND i.documento_id = ?"
        params.append(documento_id)
    return con.execute(sql + " ORDER BY i.id", params).fetchall()


def obtener_incidencia(con, incidencia_id: int) -> sqlite3.Row:
    fila = con.execute(
        "SELECT i.*, d.nombre_archivo, d.entidad FROM incidencias i JOIN documentos d ON d.id = i.documento_id"
        " WHERE i.id = ?", (incidencia_id,)
    ).fetchone()
    if fila is None:
        raise KeyError(f"Incidencia {incidencia_id} inexistente")
    return fila


def resolver_incidencia(con, incidencia_id: int, estado: str, usuario: str, comentario: str = "") -> None:
    con.execute(
        "UPDATE incidencias SET estado = ?, resuelta_por = ?, comentario = ?, resuelta_en = ? WHERE id = ?",
        (estado, usuario, comentario, ahora(), incidencia_id),
    )


def asignar_incidencia(con, incidencia_id: int, responsable: str) -> None:
    con.execute("UPDATE incidencias SET responsable = ? WHERE id = ?", (responsable, incidencia_id))


# ------------------------------------------------------------------ acciones

def registrar_accion(con, *, documento_id, incidencia_id, tipo, canal, destinatario, asunto, cuerpo, estado,
                     detalle="") -> int:
    cur = con.execute(
        "INSERT INTO acciones (documento_id, incidencia_id, tipo, canal, destinatario, asunto, cuerpo, estado,"
        " detalle, creado_en) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (documento_id, incidencia_id, tipo, canal, destinatario, asunto, cuerpo, estado, detalle, ahora()),
    )
    return cur.lastrowid


def listar_acciones(con, documento_id: int | None = None) -> list[sqlite3.Row]:
    if documento_id:
        return con.execute("SELECT * FROM acciones WHERE documento_id = ? ORDER BY id DESC", (documento_id,)).fetchall()
    return con.execute("SELECT * FROM acciones ORDER BY id DESC").fetchall()


# ------------------------------------------------------------------ consulta

def guardar_embeddings(con, pares: list[tuple[int, np.ndarray]]) -> None:
    con.executemany(
        "UPDATE fragmentos SET embedding = ? WHERE id = ?",
        [(v.astype(np.float32).tobytes(), fid) for fid, v in pares],
    )


def fragmentos_para_consulta(con, documento_ids: list[int] | None = None) -> list[sqlite3.Row]:
    sql = (
        "SELECT f.id, f.documento_id, f.pagina, f.texto, f.embedding, d.entidad, d.nombre_archivo"
        " FROM fragmentos f JOIN documentos d ON d.id = f.documento_id"
    )
    if documento_ids:
        sql += f" WHERE f.documento_id IN ({','.join('?' * len(documento_ids))})"
        return con.execute(sql, documento_ids).fetchall()
    return con.execute(sql).fetchall()


def registrar_consulta(con, pregunta: str, respuesta: str, fuentes: list[dict]) -> None:
    con.execute(
        "INSERT INTO consultas (pregunta, respuesta, fuentes, creado_en) VALUES (?, ?, ?, ?)",
        (pregunta, respuesta, json.dumps(fuentes, ensure_ascii=False), ahora()),
    )


# ------------------------------------------------------------- Excel base

def tabla_base(con) -> pd.DataFrame:
    """Una fila por entidad y fecha de balance, una columna por campo (formato Excel base).

    Si una entidad presentó más de un documento para el mismo período, vale el
    último procesado (las re-presentaciones reemplazan a las anteriores). Los
    documentos sin entidad o sin fecha detectada no se agrupan: quedan todos.
    Los textos faltantes se devuelven como None (no NaN).
    """
    onto = obtener_ontologia()
    columnas = ["documento_id", "entidad", "fecha_balance", "nombre_archivo"] + [c.id for c in onto.campos]
    docs = pd.read_sql_query(
        "SELECT id AS documento_id, entidad, fecha_balance, nombre_archivo FROM documentos"
        " WHERE estado = 'completado' ORDER BY id", con
    )
    if docs.empty:
        return pd.DataFrame(columns=columnas)
    identificados = docs["entidad"].notna() & docs["fecha_balance"].notna()
    docs = pd.concat([
        docs[identificados].drop_duplicates(subset=["entidad", "fecha_balance"], keep="last"),
        docs[~identificados],
    ]).sort_values(["entidad", "documento_id"], na_position="last")
    for col in ("entidad", "fecha_balance", "nombre_archivo"):
        docs[col] = docs[col].astype(object).where(docs[col].notna(), None)
    vals = pd.read_sql_query("SELECT documento_id, campo, valor FROM valores", con)
    ancho = vals.pivot(index="documento_id", columns="campo", values="valor") if not vals.empty else pd.DataFrame()
    tabla = docs.merge(ancho, left_on="documento_id", right_index=True, how="left")
    for c in onto.campos:
        if c.id not in tabla.columns:
            tabla[c.id] = None
    return tabla[columnas]


def detalle_valores(con) -> pd.DataFrame:
    return pd.read_sql_query(
        "SELECT d.entidad, d.fecha_balance, d.nombre_archivo, v.* FROM valores v"
        " JOIN documentos d ON d.id = v.documento_id ORDER BY d.entidad, v.campo",
        con,
    )


def exportar_excel(con, destino: Path) -> Path:
    """Genera el Excel base: hoja 'Base' (formato NECC) + trazabilidad + incidencias."""
    onto = obtener_ontologia()
    base = tabla_base(con).rename(columns={c.id: c.nombre for c in onto.campos})
    detalle = detalle_valores(con)
    incid = pd.read_sql_query(
        "SELECT d.entidad, i.campo, i.regla, i.severidad, i.mensaje, i.estado, i.responsable, i.creado_en"
        " FROM incidencias i JOIN documentos d ON d.id = i.documento_id ORDER BY i.id",
        con,
    )
    destino.parent.mkdir(parents=True, exist_ok=True)
    with pd.ExcelWriter(destino, engine="openpyxl") as xl:
        base.to_excel(xl, sheet_name="Base", index=False)
        detalle.to_excel(xl, sheet_name="Trazabilidad", index=False)
        incid.to_excel(xl, sheet_name="Incidencias", index=False)
        for hoja in xl.sheets.values():
            for col in hoja.columns:
                ancho = max(len(str(c.value or "")) for c in col[:50])
                hoja.column_dimensions[col[0].column_letter].width = min(max(ancho + 2, 10), 60)
    return destino
