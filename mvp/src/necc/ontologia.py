"""Carga de la ontología del dominio (config/ontologia.yaml).

La ontología es la fuente única de verdad sobre QUÉ se extrae: campos del Excel
base, sinónimos con que aparecen en las notas, componentes, derivaciones y reglas.
Agregar una variante nueva de redacción = editar el YAML, no el código.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml

from .config import obtener_config
from .texto import patron_frase


@dataclass(frozen=True)
class Concepto:
    id: str
    nombre: str
    tipo: str  # conteo | monto | ratio
    seccion: str
    criterio: str
    requerido: bool = False
    es_componente: bool = False
    norma: str = ""
    sinonimos: tuple[str, ...] = ()
    patrones: tuple[str, ...] = ()

    @property
    def regex_sinonimos(self) -> list[re.Pattern[str]]:
        return [re.compile(patron_frase(s)) for s in self.sinonimos]

    @property
    def regex_patrones(self) -> list[re.Pattern[str]]:
        return [re.compile(p) for p in self.patrones]


@dataclass(frozen=True)
class Termino:
    campo: str
    signo: int
    opcional: bool = False


@dataclass(frozen=True)
class Derivacion:
    objetivo: str
    terminos: tuple[Termino, ...]


@dataclass(frozen=True)
class Regla:
    id: str
    tipo: str
    severidad: str
    mensaje: str
    campos: tuple[str, ...] = ()
    minimo: float | None = None
    maximo: float | None = None


@dataclass(frozen=True)
class Seccion:
    id: str
    nombre: str
    anclas: tuple[str, ...]


@dataclass
class Ontologia:
    secciones: dict[str, Seccion]
    conceptos: dict[str, Concepto]
    derivaciones: list[Derivacion]
    reglas: list[Regla]

    @property
    def campos(self) -> list[Concepto]:
        """Campos finales (columnas del Excel base), en el orden del YAML."""
        return [c for c in self.conceptos.values() if not c.es_componente]

    @property
    def componentes(self) -> list[Concepto]:
        return [c for c in self.conceptos.values() if c.es_componente]

    def de_seccion(self, seccion: str) -> list[Concepto]:
        return [c for c in self.conceptos.values() if c.seccion == seccion]


def _concepto(cid: str, d: dict, es_componente: bool) -> Concepto:
    return Concepto(
        id=cid,
        nombre=d["nombre"],
        tipo=d["tipo"],
        seccion=d["seccion"],
        criterio=" ".join(str(d.get("criterio", "")).split()),
        requerido=bool(d.get("requerido", False)),
        es_componente=es_componente,
        norma=d.get("norma", ""),
        sinonimos=tuple(d.get("sinonimos") or ()),
        patrones=tuple(d.get("patrones") or ()),
    )


def cargar_ontologia(ruta: Path) -> Ontologia:
    datos = yaml.safe_load(ruta.read_text(encoding="utf-8"))
    conceptos: dict[str, Concepto] = {}
    for cid, d in datos["campos"].items():
        conceptos[cid] = _concepto(cid, d, es_componente=False)
    for cid, d in (datos.get("componentes") or {}).items():
        conceptos[cid] = _concepto(cid, d, es_componente=True)

    derivaciones = [
        Derivacion(
            objetivo=d["objetivo"],
            terminos=tuple(Termino(t["campo"], int(t["signo"]), bool(t.get("opcional", False))) for t in d["terminos"]),
        )
        for d in datos.get("derivaciones") or []
    ]
    reglas = [
        Regla(
            id=r["id"],
            tipo=r["tipo"],
            severidad=r["severidad"],
            mensaje=r["mensaje"],
            campos=tuple(r.get("campos") or ()),
            minimo=r.get("minimo"),
            maximo=r.get("maximo"),
        )
        for r in datos.get("reglas") or []
    ]
    secciones = {
        sid: Seccion(sid, s["nombre"], tuple(s.get("anclas") or ())) for sid, s in datos["secciones"].items()
    }

    referenciados = {d.objetivo for d in derivaciones} | {t.campo for d in derivaciones for t in d.terminos}
    referenciados |= {c for r in reglas for c in r.campos}
    desconocidos = referenciados - conceptos.keys()
    if desconocidos:
        raise ValueError(f"La ontología referencia conceptos inexistentes: {sorted(desconocidos)}")
    return Ontologia(secciones, conceptos, derivaciones, reglas)


@lru_cache(maxsize=1)
def obtener_ontologia() -> Ontologia:
    return cargar_ontologia(obtener_config().ontologia)
