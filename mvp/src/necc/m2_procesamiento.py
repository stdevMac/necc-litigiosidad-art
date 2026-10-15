"""Módulo 2 · Procesamiento: parsing, OCR, limpieza y fragmentación.

  1. Parsing: texto nativo del PDF por página (PyMuPDF, orden de lectura por
     posición para respetar filas de tablas).
  2. OCR: si la página no tiene texto o contiene imágenes grandes (cuadros
     escaneados), se renderiza la región y se transcribe (Gemini visión o
     Tesseract local).
  3. Limpieza: viñetas de fuentes privadas, espacios duros, encabezados y pies
     repetidos en todas las páginas (razón social, firma del auditor).
  4. Fragmentación: párrafos agrupados en fragmentos de ~1000 caracteres sin
     cruzar páginas (cada fragmento conserva su página para citarla).
"""

from __future__ import annotations

import logging
import re
import shutil
import subprocess
from collections import Counter
from pathlib import Path

import pymupdf

from . import llm
from .config import obtener_config
from .modelos import DocumentoProcesado, Fragmento, Pagina

log = logging.getLogger(__name__)

MIN_TEXTO_PAGINA = 80  # menos caracteres => página escaneada
MIN_AREA_IMAGEN = 0.03  # fracción de la página para considerar una imagen "contenido"
DPI_OCR = 200
TAM_FRAGMENTO = 1000

INSTRUCCION_OCR = (
    "Transcribí fielmente todo el texto de esta imagen, que es parte de un estado contable argentino. "
    "Si hay tablas, devolvelas en formato Markdown conservando filas y columnas. "
    "Copiá los números exactamente como aparecen (puntos de miles, comas decimales, signos, paréntesis). "
    "No agregues comentarios ni texto que no esté en la imagen."
)


# ----------------------------------------------------------------------- OCR

def _ocr(png: bytes) -> str:
    motor = obtener_config().motor_ocr
    if motor == "tesseract":
        return _ocr_tesseract(png)
    return llm.transcribir_imagen(png, INSTRUCCION_OCR).strip()


def _ocr_o_nada(png: bytes) -> str | None:
    """OCR tolerante a fallas (sin clave, API caída, tesseract ausente): None si no se pudo."""
    try:
        return _ocr(png)
    except Exception:
        log.exception("Falló el OCR de una página")
        return None


def _ocr_tesseract(png: bytes) -> str:
    if not shutil.which("tesseract"):
        raise RuntimeError("NECC_MOTOR_OCR=tesseract pero tesseract no está instalado")
    idiomas = subprocess.run(["tesseract", "--list-langs"], capture_output=True, text=True).stdout
    lang = "spa" if "spa" in idiomas.split() else "eng"
    r = subprocess.run(
        ["tesseract", "stdin", "stdout", "-l", lang, "--psm", "6"], input=png, capture_output=True, check=True
    )
    return r.stdout.decode("utf-8", errors="replace").strip()


def _imagenes_contenido(doc: pymupdf.Document) -> dict[int, list[pymupdf.Rect]]:
    """Regiones de imagen relevantes por página (descarta logos repetidos y miniaturas)."""
    apariciones: Counter[int] = Counter()
    por_pagina: dict[int, list[tuple[int, pymupdf.Rect]]] = {}
    for pagina in doc:
        area = pagina.rect.width * pagina.rect.height
        vistas = set()
        for info in pagina.get_image_info(xrefs=True):
            rect = pymupdf.Rect(info["bbox"]) & pagina.rect
            if rect.is_empty or rect.width * rect.height / area < MIN_AREA_IMAGEN:
                continue
            xref = info.get("xref", 0)
            por_pagina.setdefault(pagina.number, []).append((xref, rect))
            if xref and xref not in vistas:
                apariciones[xref] += 1
                vistas.add(xref)
    repetidas = {x for x, n in apariciones.items() if len(doc) >= 3 and n / len(doc) > 0.5}
    return {p: [r for x, r in lst if x not in repetidas] for p, lst in por_pagina.items()}


def _render(pagina: pymupdf.Page, clip: pymupdf.Rect | None = None) -> bytes:
    return pagina.get_pixmap(dpi=DPI_OCR, clip=clip).tobytes("png")


# ------------------------------------------------------------------- limpieza

def limpiar(texto: str) -> str:
    texto = re.sub(r"[\uf000-\uf8ff]", "•", texto)  # viñetas de fuentes Symbol/Wingdings
    texto = texto.replace("\u00a0", " ").replace("\u200b", "")
    texto = re.sub(r"[ \t]+\n", "\n", texto)
    texto = re.sub(r"\n{3,}", "\n\n", texto)
    return texto.strip()


def quitar_repetidos(paginas: list[str]) -> tuple[list[str], list[str]]:
    """Elimina líneas que se repiten en la mayoría de las páginas (encabezados/pies).

    Devuelve (páginas limpias, líneas repetidas). La primera página se conserva
    intacta: su encabezado suele declarar la entidad y la unidad de medida.
    """
    if len(paginas) < 3:
        return paginas, []
    conteo: Counter[str] = Counter()
    for t in paginas:
        conteo.update({ln.strip() for ln in t.splitlines() if len(ln.strip()) >= 4})
    umbral = len(paginas) * 0.6
    repetidas = [ln for ln, n in conteo.most_common() if n >= umbral]
    limpias = [paginas[0]] + [
        re.sub(r"\n{3,}", "\n\n", "\n".join(ln for ln in t.splitlines() if ln.strip() not in repetidas)).strip()
        for t in paginas[1:]
    ]
    return limpias, repetidas


def fragmentar(paginas: list[Pagina], tam: int = TAM_FRAGMENTO) -> list[Fragmento]:
    fragmentos: list[Fragmento] = []
    for p in paginas:
        actual = ""
        for parrafo in re.split(r"\n\s*\n", p.texto):
            parrafo = parrafo.strip()
            if not parrafo:
                continue
            if actual and len(actual) + len(parrafo) > tam:
                fragmentos.append(Fragmento(p.numero, len(fragmentos), actual))
                actual = ""
            actual = f"{actual}\n\n{parrafo}" if actual else parrafo
        if actual:
            fragmentos.append(Fragmento(p.numero, len(fragmentos), actual))
    return fragmentos


# ------------------------------------------------------------------ principal

def procesar(ruta: Path) -> DocumentoProcesado:
    """Texto limpio por página. Si el OCR falla en una página, se conserva el texto
    nativo que tenga y se marca el método como '...ocr_fallido' (la estandarización
    lo convierte en incidencia)."""
    textos: list[str] = []
    metodos: list[str] = []
    with pymupdf.open(ruta) as doc:
        imagenes = _imagenes_contenido(doc) if doc.is_pdf else {}
        for pagina in doc:
            texto = pagina.get_text(sort=True) if doc.is_pdf else ""
            if len(texto.strip()) < MIN_TEXTO_PAGINA:
                transcripcion = _ocr_o_nada(_render(pagina))
                textos.append(texto if transcripcion is None else transcripcion)
                metodos.append("ocr_fallido" if transcripcion is None else "ocr")
                continue
            regiones = imagenes.get(pagina.number, [])
            if regiones:
                transcripciones = [_ocr_o_nada(_render(pagina, r)) for r in regiones]
                texto += "\n\n" + "\n\n".join(f"[Imagen transcripta por OCR]\n{t}" for t in transcripciones if t)
                metodos.append("texto+ocr_fallido" if None in transcripciones else "texto+ocr")
            else:
                metodos.append("texto")
            textos.append(texto)

    textos, encabezados = quitar_repetidos([limpiar(t) for t in textos])
    paginas = [Pagina(i + 1, t, m) for i, (t, m) in enumerate(zip(textos, metodos))]
    return DocumentoProcesado(paginas, fragmentar(paginas), encabezados)
