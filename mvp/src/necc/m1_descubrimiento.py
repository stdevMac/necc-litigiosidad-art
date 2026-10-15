"""Módulo 1 · Descubrimiento de archivos.

Entradas posibles:
  - carpeta de entrada (data/inbox) o cualquier carpeta indicada: se escanea;
  - subida manual desde la interfaz web;
  - modo vigilancia: escaneo periódico de la carpeta de entrada.

Cada archivo se identifica por su hash SHA-256: el mismo balance subido dos
veces no se procesa dos veces. El original se copia a un almacén inmutable
(data/documentos) para garantizar trazabilidad.
"""

from __future__ import annotations

import hashlib
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable

import pymupdf

from . import m5_almacenamiento as db
from .config import obtener_config

log = logging.getLogger(__name__)

EXTENSIONES = {".pdf", ".png", ".jpg", ".jpeg"}


@dataclass
class Descubierto:
    documento_id: int
    nombre: str
    nuevo: bool


def _guardar_original(contenido: bytes, nombre: str, sha: str) -> Path:
    destino = obtener_config().documentos / f"{sha[:12]}_{Path(nombre).name}"
    if not destino.exists():
        destino.write_bytes(contenido)
    return destino


def validar(contenido: bytes, nombre: str) -> None:
    """ValueError si el archivo no tiene un formato admitido o no se puede abrir."""
    sufijo = Path(nombre).suffix.lower()
    if sufijo not in EXTENSIONES:
        raise ValueError(f"Formato no soportado: {nombre} (admitidos: {', '.join(sorted(EXTENSIONES))})")
    try:
        with pymupdf.open(stream=contenido, filetype=sufijo[1:]) as doc:
            paginas = doc.page_count
    except Exception as e:
        raise ValueError(
            f"No se pudo abrir {Path(nombre).name}: archivo dañado o no es un {sufijo[1:].upper()} válido"
        ) from e
    if paginas == 0:
        raise ValueError(f"{Path(nombre).name} no tiene páginas")


def registrar_bytes(contenido: bytes, nombre: str, origen: str) -> Descubierto:
    """Registra un archivo (subido o encontrado). Idempotente por hash."""
    validar(contenido, nombre)
    sha = hashlib.sha256(contenido).hexdigest()
    ruta = _guardar_original(contenido, nombre, sha)
    with db.conexion() as con:
        doc_id, nuevo = db.registrar_documento(con, sha, Path(nombre).name, str(ruta), origen)
        if nuevo:
            db.registrar_evento(con, doc_id, "descubrimiento", "ok", f"origen={origen} sha256={sha[:12]}")
    return Descubierto(doc_id, Path(nombre).name, nuevo)


def _archivos(directorios: Iterable[Path]) -> Iterable[Path]:
    for d in directorios:
        d = Path(d)
        if d.is_file() and d.suffix.lower() in EXTENSIONES:
            yield d
        elif d.is_dir():
            yield from sorted(p for p in d.rglob("*") if p.is_file() and p.suffix.lower() in EXTENSIONES)


def descubrir(rutas: Iterable[Path] | None = None) -> list[Descubierto]:
    """Escanea la carpeta de entrada (o las rutas indicadas) y registra los archivos nuevos.
    Los archivos dañados se informan y se saltean."""
    rutas = list(rutas) if rutas else [obtener_config().inbox]
    origen = "inbox" if rutas == [obtener_config().inbox] else "carpeta"
    encontrados = []
    for p in _archivos(rutas):
        try:
            encontrados.append(registrar_bytes(p.read_bytes(), p.name, origen))
        except ValueError as e:
            log.warning("%s", e)
    return encontrados


def vigilar(al_descubrir: Callable[[list[Descubierto]], None], intervalo_s: int = 10) -> None:
    """Escaneo periódico de la carpeta de entrada; llama al callback con los nuevos."""
    print(f"Vigilando {obtener_config().inbox} cada {intervalo_s}s (Ctrl+C para salir)")
    while True:
        nuevos = [d for d in descubrir() if d.nuevo]
        if nuevos:
            al_descubrir(nuevos)
        time.sleep(intervalo_s)
