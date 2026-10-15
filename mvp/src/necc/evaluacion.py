"""Evaluación por componente contra el gold set (eval/gold.yaml).

Para cada documento se corre procesamiento + estandarización una sola vez y se
comparan tres estrategias sobre los mismos candidatos:
  - reglas:  solo ontología + regex
  - llm:     solo Gemini (con verificación de que el número existe)
  - híbrido: fusión (lo que usa el pipeline)
Métricas:
  - exactitud por campo (tolerancia 0,5 %; null correcto = abstención correcta),
  - recall de localización (las páginas del gold están entre las seleccionadas),
  - acierto de unidad.
No escribe en la base: es reproducible y aislado.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import yaml

from .config import obtener_config
from .m2_procesamiento import procesar
from .m3_estandarizacion import estandarizar
from .m4_preprocesamiento import preprocesar
from .modelos import Estandarizado
from .ontologia import obtener_ontologia

METODOS = ("reglas", "llm", "hibrido")


def _correcto(pred: float | None, gold: float | None, tipo: str) -> bool:
    if gold is None:
        return pred is None
    if pred is None:
        return False
    if tipo == "ratio":
        return abs(pred - gold) <= 0.0005
    return abs(pred - gold) <= 0.005 * abs(gold)


def _variante(est: Estandarizado, metodo: str) -> Estandarizado:
    if metodo == "hibrido":
        return est
    elegidos = {}
    for c in est.candidatos:
        if c.metodo == metodo and c.concepto not in elegidos:
            elegidos[c.concepto] = c
    meta = est.metadatos_por_metodo.get(metodo, est.metadatos)
    return Estandarizado(meta, elegidos, est.candidatos, est.paginas_seleccionadas)


def evaluar(gold_path: Path, usar_llm: bool = True) -> dict:
    onto = obtener_ontologia()
    tipos = {c.id: c.tipo for c in onto.campos}
    gold = yaml.safe_load(gold_path.read_text(encoding="utf-8"))
    raiz = obtener_config().raiz
    metodos = METODOS if usar_llm else ("reglas",)

    filas = []
    for g in gold["documentos"]:
        inicio = time.perf_counter()
        doc = procesar(raiz / g["archivo"])
        est = estandarizar(doc, onto, usar_llm=usar_llm)
        fila = {
            "archivo": Path(g["archivo"]).name,
            "variante": g["variante"],
            "localizacion_ok": set(g["paginas"]) <= set(est.paginas_seleccionadas),
            "paginas_seleccionadas": est.paginas_seleccionadas,
            "segundos": round(time.perf_counter() - inicio, 1),
            "metodos": {},
        }
        for m in metodos:
            pre = preprocesar(_variante(est, m), onto)
            pred = {v.campo: v.valor for v in pre.valores}
            campos = {
                campo: {"gold": esperado, "pred": pred.get(campo), "ok": _correcto(pred.get(campo), esperado, tipos[campo])}
                for campo, esperado in g["valores"].items()
            }
            fila["metodos"][m] = {
                "aciertos": sum(c["ok"] for c in campos.values()),
                "total": len(campos),
                "unidad_ok": pre.metadatos.unidad == g["unidad"],
                "unidad": pre.metadatos.unidad,
                "a_revisar": sum(v.estado == "revisar" for v in pre.valores),
                "campos": campos,
            }
        filas.append(fila)
        print(f"{fila['archivo']:<42} " + "  ".join(
            f"{m}: {fila['metodos'][m]['aciertos']}/{fila['metodos'][m]['total']}" for m in metodos
        ) + f"  localización: {'ok' if fila['localizacion_ok'] else 'FALLA'}")

    resumen = {
        m: {
            "aciertos": sum(f["metodos"][m]["aciertos"] for f in filas),
            "total": sum(f["metodos"][m]["total"] for f in filas),
            "documentos_perfectos": sum(f["metodos"][m]["aciertos"] == f["metodos"][m]["total"] for f in filas),
            "unidad_ok": sum(f["metodos"][m]["unidad_ok"] for f in filas),
        }
        for m in metodos
    }
    resultado = {"documentos": filas, "resumen": resumen,
                 "localizacion_ok": sum(f["localizacion_ok"] for f in filas), "n": len(filas)}
    destino = gold_path.parent
    (destino / "resultados.json").write_text(json.dumps(resultado, ensure_ascii=False, indent=2), encoding="utf-8")
    (destino / "resultados.md").write_text(_markdown(resultado, metodos, onto), encoding="utf-8")
    print(f"\nResultados en {destino / 'resultados.md'}")
    return resultado


def _markdown(r: dict, metodos: tuple[str, ...], onto) -> str:
    n = r["n"]
    lineas = [
        "# Resultados de evaluación",
        "",
        f"Documentos: {n} · localización correcta: {r['localizacion_ok']}/{n}",
        "",
        "| Método | Campos correctos | Exactitud | Documentos 100 % | Unidad correcta |",
        "|---|---:|---:|---:|---:|",
    ]
    for m in metodos:
        s = r["resumen"][m]
        lineas.append(f"| {m} | {s['aciertos']}/{s['total']} | {s['aciertos'] / s['total']:.1%} | "
                      f"{s['documentos_perfectos']}/{n} | {s['unidad_ok']}/{n} |")
    lineas += ["", "## Por documento", "", "| Documento | Variante | " + " | ".join(metodos) + " | Revisar (híbrido) |",
               "|---|---|" + "---:|" * len(metodos) + "---:|"]
    for f in r["documentos"]:
        celdas = " | ".join(f"{f['metodos'][m]['aciertos']}/{f['metodos'][m]['total']}" for m in metodos)
        revisar = f["metodos"].get("hibrido", f["metodos"][metodos[0]])["a_revisar"]
        lineas.append(f"| {f['archivo']} | {f['variante']} | {celdas} | {revisar} |")
    lineas += ["", "## Errores", ""]
    errores = [
        f"- **{f['archivo']}** · {m} · {onto.conceptos[c].nombre}: esperado `{d['gold']}`, obtenido `{d['pred']}`"
        for f in r["documentos"] for m in metodos for c, d in f["metodos"][m]["campos"].items() if not d["ok"]
    ]
    lineas += errores or ["Ninguno."]
    return "\n".join(lineas) + "\n"
