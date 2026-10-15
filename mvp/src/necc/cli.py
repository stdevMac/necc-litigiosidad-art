"""Línea de comandos: `uv run necc <comando>`."""

from __future__ import annotations

import argparse
from pathlib import Path

from . import llm
from . import m1_descubrimiento as m1
from . import m5_almacenamiento as db
from . import m7_consulta, m8_accion, pipeline
from .config import obtener_config


def _progreso(etapa: str, estado: str) -> None:
    if estado != "inicio":
        print(f"   · {etapa:<17} {estado}")


def _procesar(ids: list[int], usar_llm: bool) -> None:
    for i in ids:
        print(f"▶ Documento #{i}")
        try:
            r = pipeline.procesar_documento(i, usar_llm, _progreso)
        except KeyError as e:
            print(f"   = {e.args[0]}")
            continue
        print(f"   = {r['estado']} {r.get('entidad') or r.get('error') or ''}")


def cmd_descubrir(a) -> list[m1.Descubierto]:
    faltantes = [r for r in a.rutas if not Path(r).exists()]
    if faltantes:
        raise SystemExit(f"No existe: {', '.join(faltantes)}")
    encontrados = m1.descubrir([Path(r) for r in a.rutas] or None)
    for d in encontrados:
        print(f"{'nuevo  ' if d.nuevo else 'ya existía'} #{d.documento_id} {d.nombre}")
    return encontrados


def cmd_ejecutar(a) -> None:
    encontrados = cmd_descubrir(a)
    ids = [d.documento_id for d in encontrados if d.nuevo or a.reprocesar]
    _procesar(ids, not a.sin_llm)


def cmd_procesar(a) -> None:
    if a.todos:
        with db.conexion() as con:
            ids = [d["id"] for d in db.listar_documentos(con)]
    elif a.ids:
        ids = a.ids
    else:
        with db.conexion() as con:
            ids = [d["id"] for d in db.listar_documentos(con, ("descubierto", "error"))]
    _procesar(ids, not a.sin_llm)


def cmd_vigilar(a) -> None:
    m1.vigilar(lambda nuevos: _procesar([d.documento_id for d in nuevos], True), a.intervalo)


def cmd_estado(_a) -> None:
    with db.conexion() as con:
        for d in db.listar_documentos(con):
            abiertas = sum(i["severidad"] != "info" for i in db.listar_incidencias(con, "abierta", d["id"]))
            print(f"#{d['id']:<3} {d['estado']:<11} {d['entidad'] or '—':<55} {d['fecha_balance'] or '':<11} "
                  f"a revisar: {abiertas}  ({d['nombre_archivo']})")


def cmd_consultar(a) -> None:
    if not llm.disponible():
        raise SystemExit("Falta GEMINI_API_KEY: la consulta necesita el LLM (definila en el entorno o en mvp/.env).")
    respuesta, fuentes = m7_consulta.responder(a.pregunta)
    print(respuesta)
    print("\nFuentes:")
    for f in fuentes:
        print(f"  - {f.entidad}, pág. {f.pagina}")


def cmd_exportar(a) -> None:
    with db.conexion() as con:
        print(db.exportar_excel(con, Path(a.salida)))


def cmd_reporte(_a) -> None:
    md, xlsx = m8_accion.reporte_consolidado()
    print(md)
    print(xlsx)


def cmd_evaluar(a) -> None:
    from .evaluacion import evaluar

    evaluar(Path(a.gold), usar_llm=not a.sin_llm)


def cmd_ui(a) -> None:
    import uvicorn

    if not (obtener_config().raiz / "web" / "dist").exists():
        print("Falta compilar la interfaz: npm --prefix web install && npm --prefix web run build")
    print(f"Interfaz web en http://localhost:{a.puerto}")
    uvicorn.run("necc.m6_visualizacion.api:app", host=a.host, port=a.puerto)


def main() -> None:
    p = argparse.ArgumentParser(prog="necc", description="Pipeline de estandarización de notas contables ART")
    sub = p.add_subparsers(dest="comando", required=True)
    ayuda_rutas = "Archivos o carpetas (PDF, PNG, JPG); por defecto, la carpeta de entrada data/inbox"
    ayuda_sin_llm = "Solo reglas (sin Gemini)"

    s = sub.add_parser("descubrir", help="Registrar archivos de la carpeta de entrada o de las rutas dadas")
    s.add_argument("rutas", nargs="*", help=ayuda_rutas)
    s.set_defaults(fn=cmd_descubrir)

    s = sub.add_parser("ejecutar", help="Descubrir + procesar de punta a punta")
    s.add_argument("rutas", nargs="*", help=ayuda_rutas)
    s.add_argument("--sin-llm", action="store_true", help=ayuda_sin_llm)
    s.add_argument("--reprocesar", action="store_true", help="Reprocesar también los ya registrados")
    s.set_defaults(fn=cmd_ejecutar)

    s = sub.add_parser("procesar", help="Procesar documentos registrados (por defecto: pendientes)")
    s.add_argument("ids", nargs="*", type=int, help="Ids de documento (ver `necc estado`)")
    s.add_argument("--todos", action="store_true", help="Reprocesar todos los documentos registrados")
    s.add_argument("--sin-llm", action="store_true", help=ayuda_sin_llm)
    s.set_defaults(fn=cmd_procesar)

    s = sub.add_parser("vigilar", help="Vigilar la carpeta de entrada y procesar lo nuevo")
    s.add_argument("--intervalo", type=int, default=10, help="Segundos entre escaneos (por defecto: 10)")
    s.set_defaults(fn=cmd_vigilar)

    sub.add_parser("estado", help="Listar documentos").set_defaults(fn=cmd_estado)

    s = sub.add_parser("consultar", help="Pregunta en lenguaje natural")
    s.add_argument("pregunta", help="Entre comillas, p.ej. \"¿Qué entidad tiene más juicios abiertos?\"")
    s.set_defaults(fn=cmd_consultar)

    s = sub.add_parser("exportar", help="Exportar el Excel base")
    s.add_argument("--salida", default=str(obtener_config().reportes / "excel_base.xlsx"),
                   help="Ruta del .xlsx (por defecto: data/reportes/excel_base.xlsx)")
    s.set_defaults(fn=cmd_exportar)

    sub.add_parser("reporte", help="Reporte consolidado + notificación").set_defaults(fn=cmd_reporte)

    s = sub.add_parser("evaluar", help="Comparar reglas vs LLM vs híbrido contra el gold set")
    s.add_argument("--gold", default=str(obtener_config().raiz / "eval" / "gold.yaml"),
                   help="Gold set YAML (por defecto: eval/gold.yaml); los resultados se escriben a su lado")
    s.add_argument("--sin-llm", action="store_true", help="Evaluar solo las reglas")
    s.set_defaults(fn=cmd_evaluar)

    s = sub.add_parser("ui", help="Servir la API y la interfaz web (React)")
    s.add_argument("--puerto", type=int, default=8000, help="Puerto HTTP (por defecto: 8000)")
    s.add_argument("--host", default="127.0.0.1", help="Interfaz de red (por defecto: solo esta máquina)")
    s.set_defaults(fn=cmd_ui)

    a = p.parse_args()
    a.fn(a)
