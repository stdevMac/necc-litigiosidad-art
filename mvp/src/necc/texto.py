"""Utilidades de texto compartidas: normalización y lectura de números argentinos."""

from __future__ import annotations

import re
import unicodedata

# Número tal como aparece en notas contables argentinas:
#   4.260.085.575 | $ 6.316.980.282 | (11.351.361) | 0,116 | 37.69% | 4112
NUMERO_RE = re.compile(
    r"(?<![\w.,/])\(?-?\$?\s?(?:\d{1,3}(?:\.\d{3})+(?:,\d+)?|\d+(?:[.,]\d+)?)(?![.,]?\d)\)?(?:\s?%)?"
)


def normalizar(texto: str) -> str:
    """Minúsculas y sin acentos, preservando la longitud (1 carácter -> 1 carácter).

    Mantener la longitud permite usar los offsets del texto normalizado sobre el
    texto original (para citar evidencia literal).
    """
    salida = []
    for c in texto:
        base = unicodedata.normalize("NFKD", c)
        base = "".join(ch for ch in base if not unicodedata.combining(ch)) or c
        salida.append(base[0].lower() if base else c)
    return "".join(salida)


def compactar(texto: str) -> str:
    """Normaliza y colapsa espacios: útil para comparar evidencia con el texto fuente."""
    return re.sub(r"\s+", " ", normalizar(texto)).strip()


def patron_frase(frase: str) -> str:
    """Convierte una frase de la ontología en regex tolerante a saltos de línea,
    comillas y puntuación entre palabras."""
    palabras = [re.escape(p) for p in re.findall(r"\w+", normalizar(frase))]
    return r"\b" + r"[\W_]+".join(palabras) + r"\b"


def parse_numero(crudo: str) -> float | None:
    """Convierte un número en formato argentino a float.

    Reglas: paréntesis o '-' => negativo; '%' => fracción (/100);
    con '.' y ',' el último separador es el decimal; solo '.', con grupos de
    3 dígitos => miles (salvo que empiece con 0: '0.116' es decimal);
    solo ',' => decimal (salvo varios grupos de 3 dígitos).
    """
    if crudo is None:
        return None
    s = crudo.strip()
    porcentaje = s.endswith("%")
    nucleo = s.rstrip("% ").replace("$", "").strip()
    negativo = (nucleo.startswith("(") and nucleo.endswith(")")) or nucleo.startswith("-")
    s = re.sub(r"[^\d.,]", "", s).rstrip(".,")
    if not s or not any(ch.isdigit() for ch in s):
        return None

    if "." in s and "," in s:
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    elif "." in s:
        grupos = s.split(".")
        if all(len(g) == 3 for g in grupos[1:]) and 1 <= len(grupos[0]) <= 3 and not grupos[0].startswith("0"):
            s = s.replace(".", "")
    elif "," in s:
        grupos = s.split(",")
        if len(grupos) > 2 and all(len(g) == 3 for g in grupos[1:]):
            s = s.replace(",", "")
        else:
            s = s.replace(",", ".")
    try:
        valor = float(s)
    except ValueError:
        return None
    if porcentaje:
        valor /= 100
    return -valor if negativo else valor


_TOKEN = re.compile(r"[a-z]+|\d+(?:\.\d+)*")


def tokens(texto: str) -> list[str]:
    """Tokens para BM25: palabras normalizadas y números (incluye '33.4.1.6.1.6')."""
    return _TOKEN.findall(normalizar(texto))
