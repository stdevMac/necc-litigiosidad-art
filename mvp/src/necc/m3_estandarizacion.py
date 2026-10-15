"""Módulo 3 · Estandarización: del documento heterogéneo al esquema de la ontología.

  1. Localización (el "R" de RAG): BM25 sobre las páginas con las anclas y los
     sinónimos de cada sección de la ontología. Solo las páginas relevantes
     pasan a la extracción (menos ruido, menos costo, menos alucinación).
  2. Extracción por reglas: sinónimos de la ontología + regex de números
     argentinos. Determinística, gratuita, explicable.
  3. Extracción por LLM (Gemini, temperatura 0, salida JSON validada): lee
     cuadros, listas y prosa; devuelve el número LITERAL, la página y la cita.
     No calcula: sumas/restas las hace el pre-procesamiento.
  4. Verificación (anti-alucinación): el número que devuelve el LLM tiene que
     existir literalmente en la página citada.
  5. Fusión: si reglas y LLM coinciden -> confianza alta; si discrepan -> se
     elige el valor verificado y se abre una incidencia para revisión humana.
"""

from __future__ import annotations

import logging
import math
import re
from datetime import date
from typing import Literal

from pydantic import BaseModel, Field
from rank_bm25 import BM25Okapi

from . import llm
from .modelos import Candidato, DocumentoProcesado, Estandarizado, Incidencia, Metadatos
from .ontologia import Concepto, Ontologia
from .texto import NUMERO_RE, compactar, normalizar, parse_numero, tokens

log = logging.getLogger(__name__)

PAGINAS_POR_SECCION = 2
VENTANA_NUMERO = 250
TOLERANCIA_ACUERDO = 0.005

MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre",
         "noviembre", "diciembre"]
_ANTES_INVALIDO = re.compile(
    r"\b(n[°ºo]\.?|nro\.?|punto|puntos|resolucion|res\.|ley|art\.?|articulo|inc\.?|inciso|circular|covid|covid-|"
    r"decreto|(" + "|".join(MESES) + r")\s+de)\s*$"
)
_DESPUES_INVALIDO = re.compile(r"^\s*(/|°|º|meses|dias|anos|de\s+(" + "|".join(MESES) + r"))")


# ------------------------------------------------------------- localización

def localizar(doc: DocumentoProcesado, onto: Ontologia) -> list[int]:
    """Páginas con mayor puntaje BM25 para cada sección de la ontología.

    Documentos cortos (hasta PAGINAS_POR_SECCION páginas por sección) se analizan
    completos: con tan pocas páginas el IDF de BM25 no discrimina.
    """
    if len(doc.paginas) <= PAGINAS_POR_SECCION * len(onto.secciones):
        return [p.numero for p in doc.paginas if p.texto.strip()]
    corpus = [tokens(p.texto) for p in doc.paginas]
    bm25 = BM25Okapi(corpus)
    elegidas: list[int] = []
    for sid, seccion in onto.secciones.items():
        consulta = tokens(" ".join(seccion.anclas))
        for c in onto.de_seccion(sid):
            consulta += tokens(" ".join(c.sinonimos))
        puntajes = bm25.get_scores(consulta)
        ranking = sorted(range(len(puntajes)), key=lambda i: -puntajes[i])
        for i in ranking[:PAGINAS_POR_SECCION]:
            if puntajes[i] > 0 and doc.paginas[i].numero not in elegidas:
                elegidas.append(doc.paginas[i].numero)
    return elegidas


# ------------------------------------------------------------------- reglas

def _numero_valido(crudo: str, valor: float, tipo: str) -> bool:
    if tipo == "conteo":
        return valor >= 0 and valor == int(valor) and valor < 10_000_000 and "$" not in crudo and "%" not in crudo
    if tipo == "monto":
        return abs(valor) >= 1000
    if tipo == "ratio":
        return "%" in crudo or (0 <= valor <= 100 and bool(re.search(r"\d[.,]\d", crudo)))
    return False


def primer_numero(ventana: str, tipo: str) -> tuple[str, float, int] | None:
    """Primer número de la ventana compatible con el tipo de concepto.

    Descarta referencias normativas (N° 41.155/2017, punto 30.1.1.3), fechas,
    plazos ("doce (12) meses") y etiquetas como "COVID 19".
    """
    norm = normalizar(ventana)
    for m in NUMERO_RE.finditer(ventana):
        crudo = m.group().strip().rstrip(".,;")
        if _ANTES_INVALIDO.search(norm[max(0, m.start() - 15) : m.start()]):
            continue
        if _DESPUES_INVALIDO.match(norm[m.end() : m.end() + 12]):
            continue
        if re.fullmatch(r"\(\d{1,2}\)", crudo):
            continue
        valor = parse_numero(crudo)
        if valor is not None and _numero_valido(crudo, valor, tipo):
            return crudo, valor, m.end()
    return None


def _etiquetas(norm: str, conceptos: list[Concepto]) -> list[tuple[int, int, str]]:
    """Ocurrencias de sinónimos; ante solapamiento gana la frase más larga
    ('juicios abiertos con pagos parciales' le gana a 'juicios abiertos')."""
    hallazgos = [(m.start(), m.end(), c.id) for c in conceptos for rx in c.regex_sinonimos for m in rx.finditer(norm)]
    hallazgos.sort(key=lambda h: h[0] - h[1])
    elegidas: list[tuple[int, int, str]] = []
    for h in hallazgos:
        if all(h[1] <= e[0] or h[0] >= e[1] for e in elegidas):
            elegidas.append(h)
    return sorted(elegidas)


def extraer_por_reglas(doc: DocumentoProcesado, paginas: list[int], onto: Ontologia) -> list[Candidato]:
    conceptos = list(onto.conceptos.values())
    candidatos: dict[str, Candidato] = {}
    for numero in paginas:
        texto = doc.texto_pagina(numero)
        norm = normalizar(texto)
        etiquetas = _etiquetas(norm, conceptos)
        for i, (ini, fin, cid) in enumerate(etiquetas):
            if cid in candidatos:
                continue
            tipo = onto.conceptos[cid].tipo
            limite = etiquetas[i + 1][0] if i + 1 < len(etiquetas) else len(texto)
            confianza = 0.6
            hallado = primer_numero(texto[fin : min(limite, fin + VENTANA_NUMERO)], tipo)
            if hallado is None and limite < fin + VENTANA_NUMERO:
                # El valor puede venir después de otra etiqueta ("Pasivo Global Mínimo para los
                # 327 juicios abiertos ... asciende a $323.334.248"): se acepta con menor confianza.
                hallado = primer_numero(texto[fin : fin + VENTANA_NUMERO], tipo)
                confianza = 0.4
            if hallado:
                crudo, valor, fin_num = hallado
                candidatos[cid] = Candidato(
                    cid, "reglas", crudo, abs(valor) if tipo == "monto" else valor, numero,
                    " ".join(texto[ini : fin + fin_num].split()), confianza, True,
                )
        for c in conceptos:
            if c.id in candidatos:
                continue
            for rx in c.regex_patrones:
                m = rx.search(norm)
                if m:
                    crudo = texto[m.start("v") : m.end("v")].strip().rstrip(".,;")
                    valor = parse_numero(crudo)
                    if valor is not None and _numero_valido(crudo, valor, c.tipo):
                        evidencia = " ".join(texto[max(0, m.start() - 40) : m.end() + 40].split())
                        candidatos[c.id] = Candidato(c.id, "reglas", crudo, abs(valor), numero, evidencia, 0.6, True)
                        break
    return list(candidatos.values())


def metadatos_por_reglas(doc: DocumentoProcesado) -> Metadatos:
    cabecera = "\n".join(doc.encabezados) + "\n" + (doc.paginas[0].texto if doc.paginas else "")
    norm = normalizar(cabecera)
    meta = Metadatos()
    m = re.search(r"cifras\s+(?:expresadas|expuestas)\s+en\s+(miles de |millones de )?pesos", norm)
    if m:
        meta.unidad = f"{m.group(1)}pesos" if m.group(1) else "pesos"
        meta.evidencia_unidad = " ".join(cabecera[m.start() : m.end()].split())
    m = re.search(r"al\s+(\d{1,2})\s+de\s+(" + "|".join(MESES) + r")\s+de\s+(\d{4})", norm)
    if m:
        try:
            meta.fecha_balance = date(int(m.group(3)), MESES.index(m.group(2)) + 1, int(m.group(1))).isoformat()
        except ValueError:
            pass  # fecha inexistente (p.ej. error de OCR): se deja sin fecha
    for linea in cabecera.splitlines():
        if re.search(r"\b(seguros|aseguradora|a\.r\.t|art|mutual|cooperativa|caja)\b", normalizar(linea)) and (
            linea.strip().isupper()
        ):
            meta.entidad = " ".join(linea.split())
            break
    return meta


# ---------------------------------------------------------------------- LLM

class ValorLLM(BaseModel):
    concepto: str = Field(description="id del concepto de la ontología")
    valor_texto: str = Field(description="número copiado literalmente del documento")
    pagina: int
    evidencia: str = Field(description="fragmento literal (máx. 300 caracteres) que contiene el valor")
    confianza: float = Field(ge=0, le=1)


class RespuestaLLM(BaseModel):
    entidad: str | None = None
    fecha_balance: str | None = Field(None, description="YYYY-MM-DD")
    unidad_montos: Literal["pesos", "miles de pesos", "millones de pesos"]
    evidencia_unidad: str = ""
    valores: list[ValorLLM]


SISTEMA_LLM = """Rol: sos un analista contable experto en estados contables de aseguradoras argentinas \
(normativa SSN, RGAA).
Objetivo: extraer del texto provisto los conceptos listados, para cargar un Excel estandarizado.
Reglas estrictas:
1. Basate ÚNICAMENTE en el texto provisto. Si un concepto no aparece, NO lo incluyas. No inventes.
2. valor_texto: copiá el número EXACTAMENTE como aparece (puntos, comas, $, paréntesis, %).
3. No hagas cálculos. Si el documento informa partes por separado (por ejemplo juicios sin y con pagos \
parciales), extraé cada parte en su concepto componente.
4. En cuadros comparativos tomá la columna del período de la fecha de balance (la más reciente), nunca la del \
año anterior.
5. Respetá el criterio de cada concepto: hay conceptos parecidos (bruto / neto) que van en ids distintos.
6. pagina: el número N del marcador [PÁGINA N] donde está el valor. evidencia: cita literal.
7. unidad_montos: la unidad en que están expresados los importes de ESTA nota. Atención: algunas entidades \
declaran que los estados contables están en miles de pesos pero que las notas se exponen en pesos.
8. confianza: 0 a 1 según cuán inequívoca sea la lectura."""


def _prompt_llm(doc: DocumentoProcesado, paginas: list[int], onto: Ontologia) -> str:
    conceptos = "\n".join(
        f"- {c.id} ({c.tipo}{', componente' if c.es_componente else ''}): {c.nombre}. Criterio: {c.criterio} "
        f"Suele aparecer como: {'; '.join(c.sinonimos[:4]) or '—'}."
        for c in onto.conceptos.values()
    )
    cabecera = "\n".join(doc.encabezados[:8]) + "\n" + (doc.paginas[0].texto[:2000] if doc.paginas else "")
    cuerpo = "\n\n".join(f"[PÁGINA {n}]\n{doc.texto_pagina(n)}" for n in paginas)
    return (
        f"CONCEPTOS A EXTRAER:\n{conceptos}\n\n"
        f"ENCABEZADO DEL DOCUMENTO (para entidad, fecha de balance y unidad):\n{cabecera}\n\n"
        f"PÁGINAS RELEVANTES:\n{cuerpo}"
    )


def _magnitud(crudo: str) -> float | None:
    valor = parse_numero(crudo.replace("%", ""))
    return None if valor is None else abs(valor)


def _verificar(c: Candidato, doc: DocumentoProcesado, paginas: list[int]) -> Candidato:
    """El número debe existir literalmente en la página citada (o en otra seleccionada).

    Se compara el valor y no solo los dígitos: '1.234,5' no se verifica con un
    '12.345' de la página (mismos dígitos, otra magnitud).
    """
    objetivo = _magnitud(c.valor_texto)
    orden = ([c.pagina] if c.pagina in paginas else []) + [p for p in paginas if p != c.pagina]
    for numero in orden:
        texto = doc.texto_pagina(numero)
        if objetivo is not None and any(
            (m := _magnitud(t.group())) is not None and math.isclose(m, objetivo, rel_tol=1e-9)
            for t in NUMERO_RE.finditer(texto)
        ):
            c.pagina = numero
            c.verificado = True
            if compactar(c.evidencia)[:60] not in compactar(texto):
                c.confianza = min(c.confianza, 0.8)  # número real, cita parafraseada
            return c
    c.verificado = False
    return c


def _fecha_iso(texto: str | None) -> str | None:
    try:
        return date.fromisoformat(texto).isoformat() if texto else None
    except ValueError:
        return None


def extraer_por_llm(doc: DocumentoProcesado, paginas: list[int], onto: Ontologia) -> tuple[list[Candidato], Metadatos]:
    respuesta = llm.generar_json(_prompt_llm(doc, paginas, onto), RespuestaLLM, sistema=SISTEMA_LLM)
    meta = Metadatos(respuesta.entidad, _fecha_iso(respuesta.fecha_balance), respuesta.unidad_montos,
                     respuesta.evidencia_unidad)
    candidatos: dict[str, Candidato] = {}
    for v in respuesta.valores:
        concepto = onto.conceptos.get(v.concepto)
        valor = parse_numero(v.valor_texto)
        if concepto is None or valor is None or v.concepto in candidatos:
            continue
        valor = abs(valor) if concepto.tipo == "monto" else valor
        if concepto.tipo == "ratio" and valor > 1 and "%" not in v.valor_texto:
            valor /= 100
        c = Candidato(v.concepto, "llm", v.valor_texto, valor, v.pagina, v.evidencia[:400], v.confianza, False)
        candidatos[v.concepto] = _verificar(c, doc, paginas)
    return list(candidatos.values()), meta


# ------------------------------------------------------------------- fusión

def _coinciden(a: float, b: float) -> bool:
    return abs(a - b) <= TOLERANCIA_ACUERDO * max(abs(a), abs(b), 1e-9)


def fusionar(reglas: list[Candidato], llm_: list[Candidato], onto: Ontologia) -> tuple[dict[str, Candidato], list[Incidencia]]:
    por_reglas = {c.concepto: c for c in reglas}
    por_llm = {c.concepto: c for c in llm_}
    elegidos: dict[str, Candidato] = {}
    incidencias: list[Incidencia] = []
    for cid in onto.conceptos:
        r, l = por_reglas.get(cid), por_llm.get(cid)
        nombre = onto.conceptos[cid].nombre
        if r and l and _coinciden(r.valor, l.valor):
            elegidos[cid] = Candidato(cid, "reglas+llm", l.valor_texto, l.valor, l.pagina, l.evidencia,
                                      max(0.95, l.confianza), True)
        elif r and l:
            ganador = l if l.verificado else r
            ganador.confianza = 0.5
            elegidos[cid] = ganador
            incidencias.append(Incidencia(
                "M3_discrepancia_metodos", "advertencia",
                f"{nombre}: reglas leyeron {r.valor_texto} (pág. {r.pagina}) y el LLM {l.valor_texto} "
                f"(pág. {l.pagina}). Se tomó {ganador.valor_texto} ({ganador.metodo}).", cid,
            ))
        elif l:
            if not l.verificado:
                l.confianza = 0.3
                incidencias.append(Incidencia(
                    "M3_valor_no_verificado", "advertencia",
                    f"{nombre}: el LLM informó {l.valor_texto} pero ese número no aparece en las páginas analizadas.",
                    cid,
                ))
            else:
                l.confianza = min(l.confianza, 0.9)
            elegidos[cid] = l
        elif r:
            elegidos[cid] = r
    return elegidos, incidencias


# ---------------------------------------------------------------- principal

def estandarizar(doc: DocumentoProcesado, onto: Ontologia, usar_llm: bool = True) -> Estandarizado:
    paginas = localizar(doc, onto)
    reglas = extraer_por_reglas(doc, paginas, onto)
    meta_reglas = metadatos_por_reglas(doc)
    por_metodo = {"reglas": meta_reglas}
    incidencias: list[Incidencia] = []

    sin_ocr = [p.numero for p in doc.paginas if p.metodo.endswith("ocr_fallido")]
    if sin_ocr:
        incidencias.append(Incidencia(
            "M2_ocr_fallido", "advertencia",
            f"No se pudo transcribir por OCR la(s) página(s) {sin_ocr}: los datos que estén ahí no se leyeron. "
            "Reprocesar el documento cuando el servicio de OCR esté disponible.",
        ))

    llm_cands: list[Candidato] = []
    meta = meta_reglas
    if usar_llm and llm.disponible():
        try:
            llm_cands, meta_llm = extraer_por_llm(doc, paginas, onto)
        except Exception as e:  # el LLM es un segundo lector: si falla, quedan las reglas
            log.exception("Falló la extracción con el LLM")
            incidencias.append(Incidencia(
                "M3_llm_error", "advertencia",
                f"Falló la lectura con el LLM ({type(e).__name__}: {str(e)[:200]}); se usaron solo las reglas. "
                "Reprocesar el documento cuando el servicio esté disponible.",
            ))
        else:
            por_metodo["llm"] = meta_llm
            meta = Metadatos(
                entidad=meta_llm.entidad or meta_reglas.entidad,
                fecha_balance=meta_llm.fecha_balance or meta_reglas.fecha_balance,
                unidad=meta_llm.unidad,
                evidencia_unidad=meta_llm.evidencia_unidad or meta_reglas.evidencia_unidad,
            )
            if meta_reglas.evidencia_unidad and meta_reglas.unidad != meta_llm.unidad:
                incidencias.append(Incidencia(
                    "M3_unidad_ambigua", "advertencia",
                    f"El encabezado declara '{meta_reglas.unidad}' pero el LLM interpretó '{meta_llm.unidad}' para "
                    f"la nota ('{meta_llm.evidencia_unidad[:120]}'). Verificar la unidad de los montos.",
                ))
    else:
        incidencias.append(Incidencia(
            "M3_sin_llm", "info", "Estandarización solo por reglas (LLM desactivado o sin GEMINI_API_KEY).",
        ))

    elegidos, inc_fusion = fusionar(reglas, llm_cands, onto)
    return Estandarizado(
        metadatos=meta,
        valores=elegidos,
        candidatos=reglas + llm_cands,
        paginas_seleccionadas=paginas,
        incidencias=incidencias + inc_fusion,
        metadatos_por_metodo=por_metodo,
    )
