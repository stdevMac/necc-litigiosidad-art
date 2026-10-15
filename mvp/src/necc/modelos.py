"""Contratos de datos entre módulos del pipeline.

Cada etapa recibe y entrega estos objetos; la persistencia (m5) los traduce a
tablas SQLite. Mantenerlos acá evita dependencias cruzadas entre módulos.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Pagina:
    numero: int  # 1-based
    texto: str
    metodo: str  # texto | ocr | texto+ocr | ocr_fallido | texto+ocr_fallido


@dataclass
class Fragmento:
    pagina: int
    orden: int
    texto: str


@dataclass
class DocumentoProcesado:
    """Salida de m2 (procesamiento): texto limpio por página y fragmentos."""

    paginas: list[Pagina]
    fragmentos: list[Fragmento]
    # Líneas repetidas en todas las páginas (razón social, unidad). Se quitan del
    # cuerpo pero se conservan como metadato del documento.
    encabezados: list[str] = field(default_factory=list)

    def texto_pagina(self, numero: int) -> str:
        return next((p.texto for p in self.paginas if p.numero == numero), "")


@dataclass
class Candidato:
    """Un valor leído del documento para un concepto, por un método."""

    concepto: str
    metodo: str  # reglas | llm | reglas+llm
    valor_texto: str  # literal, como aparece en el documento
    valor: float  # en la unidad del documento (sin convertir)
    pagina: int | None
    evidencia: str
    confianza: float
    verificado: bool  # el número y la evidencia existen literalmente en la página


@dataclass
class Metadatos:
    entidad: str | None = None
    fecha_balance: str | None = None  # YYYY-MM-DD
    unidad: str = "pesos"  # pesos | miles de pesos | millones de pesos
    evidencia_unidad: str = ""


@dataclass
class Incidencia:
    regla: str
    severidad: str  # error | advertencia | info
    mensaje: str
    campo: str | None = None


@dataclass
class Estandarizado:
    """Salida de m3 (estandarización): documento mapeado al esquema de la ontología."""

    metadatos: Metadatos
    valores: dict[str, Candidato]  # concepto -> candidato elegido (campos y componentes)
    candidatos: list[Candidato]  # todos los candidatos, para auditoría y evaluación
    paginas_seleccionadas: list[int]
    incidencias: list[Incidencia] = field(default_factory=list)
    # Metadatos detectados por cada método (reglas / llm), para auditoría y evaluación.
    metadatos_por_metodo: dict[str, Metadatos] = field(default_factory=dict)


@dataclass
class ValorFinal:
    """Valor listo para persistir (m4): unidades normalizadas a pesos."""

    campo: str
    valor: float | None
    valor_origen: float | None
    unidad_origen: str
    metodo: str  # reglas | llm | reglas+llm | derivado | faltante
    pagina: int | None
    evidencia: str
    confianza: float
    estado: str  # ok | revisar | faltante


@dataclass
class Preprocesado:
    metadatos: Metadatos
    valores: list[ValorFinal]
    incidencias: list[Incidencia]
