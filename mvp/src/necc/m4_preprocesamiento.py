"""Módulo 4 · Pre-procesamiento: deja los datos estandarizados listos para guardar y analizar.

  1. Derivaciones (determinísticas, definidas en la ontología): si la entidad
     informa componentes en lugar del campo final, se suman/restan
     (p.ej. juicios sin + con pagos parciales; reserva bruta - FFEP - reaseguro).
     Si informa ambos, se verifica la consistencia.
  2. Normalización de unidades: todos los montos a pesos (miles x1.000, millones x1.000.000).
  3. Validación con las reglas de negocio de la ontología -> incidencias.
  4. Estado por campo: ok / revisar / faltante, según incidencias y confianza.
"""

from __future__ import annotations

from dataclasses import replace

from .modelos import Candidato, Estandarizado, Incidencia, Preprocesado, ValorFinal
from .ontologia import Ontologia, Regla

FACTOR_UNIDAD = {"pesos": 1.0, "miles de pesos": 1_000.0, "millones de pesos": 1_000_000.0}
UMBRAL_CONFIANZA = 0.7
TOLERANCIA = 0.005


def _formato(valor: float) -> str:
    """Formato argentino: 4.260.085.575 / 0,3769 / 1.234,56."""
    if float(valor).is_integer():
        return f"{valor:,.0f}".replace(",", ".")
    return f"{valor:,.4f}".rstrip("0").rstrip(".").translate(str.maketrans(",.", ".,"))


def derivar(valores: dict[str, Candidato], onto: Ontologia) -> tuple[dict[str, Candidato], list[Incidencia]]:
    resultado = dict(valores)
    incidencias: list[Incidencia] = []
    for d in onto.derivaciones:
        requeridos = [t for t in d.terminos if not t.opcional]
        if not all(t.campo in resultado for t in requeridos):
            continue
        presentes = [t for t in d.terminos if t.campo in resultado]
        calculado = sum(t.signo * resultado[t.campo].valor for t in presentes)
        formula = " ".join(
            f"{'+' if t.signo > 0 else '-'} {resultado[t.campo].valor_texto} ({t.campo})" for t in presentes
        ).lstrip("+ ")
        nombre = onto.conceptos[d.objetivo].nombre
        actual = resultado.get(d.objetivo)
        if actual is None:
            terminos = [resultado[t.campo] for t in presentes]
            resultado[d.objetivo] = Candidato(
                d.objetivo, "derivado", _formato(calculado), calculado, terminos[0].pagina,
                f"Derivado: {formula}", min(c.confianza for c in terminos), all(c.verificado for c in terminos),
            )
        elif abs(actual.valor - calculado) > TOLERANCIA * max(abs(actual.valor), 1):
            incidencias.append(Incidencia(
                "M4_inconsistencia_componentes", "advertencia",
                f"{nombre}: el documento informa {actual.valor_texto} pero sus componentes dan "
                f"{_formato(calculado)} ({formula}).", d.objetivo,
            ))
    return resultado, incidencias


def _aplicar_regla(regla: Regla, valores: dict[str, float | None], onto: Ontologia) -> list[Incidencia]:
    def v(campo: str) -> float | None:
        return valores.get(campo)

    if regla.tipo == "no_negativo":
        return [
            Incidencia(regla.id, regla.severidad, f"{onto.conceptos[c].nombre}: {regla.mensaje}", c)
            for c, x in valores.items() if x is not None and x < 0
        ]
    if regla.tipo == "menor_igual":
        a, b = regla.campos
        if v(a) is not None and v(b) is not None and v(a) > v(b):
            return [Incidencia(regla.id, regla.severidad, f"{regla.mensaje} ({_formato(v(a))} > {_formato(v(b))})", a)]
    if regla.tipo == "rango_cociente":
        a, b = regla.campos
        if v(a) is not None and v(b):
            cociente = v(a) / v(b)
            if not regla.minimo <= cociente <= regla.maximo:
                return [Incidencia(regla.id, regla.severidad, f"{regla.mensaje} Valor: ARS {_formato(round(cociente))}.", a)]
    if regla.tipo == "rango":
        (a,) = regla.campos
        if v(a) is not None and not regla.minimo <= v(a) <= regla.maximo:
            return [Incidencia(regla.id, regla.severidad, f"{regla.mensaje} Valor: {_formato(v(a))}.", a)]
    return []


def elegir_unidad(est: Estandarizado, valores: dict[str, Candidato], onto: Ontologia) -> tuple[str, list[Incidencia]]:
    """Barandilla de la ontología sobre la unidad interpretada.

    Si con la unidad declarada la reserva promedio por juicio es inverosímil y con
    la unidad detectada por otro método es razonable, se usa esta última y se
    deja una advertencia para que una persona lo confirme.
    """
    declarada = est.metadatos.unidad
    regla = next((r for r in onto.reglas if r.tipo == "rango_cociente"), None)
    if regla is None or not all(c in valores for c in regla.campos) or not valores[regla.campos[1]].valor:
        return declarada, []
    monto, cantidad = (valores[c].valor for c in regla.campos)

    def plausible(unidad: str) -> bool:
        return regla.minimo <= monto * FACTOR_UNIDAD[unidad] / cantidad <= regla.maximo

    if plausible(declarada):
        return declarada, []
    for meta in est.metadatos_por_metodo.values():
        if meta.unidad != declarada and plausible(meta.unidad):
            return meta.unidad, [Incidencia(
                "M4_unidad_corregida", "advertencia",
                f"Con la unidad '{declarada}' la reserva promedio por juicio es inverosímil "
                f"(ARS {_formato(round(monto * FACTOR_UNIDAD[declarada] / cantidad))}); se usó '{meta.unidad}'. "
                f"Evidencia de la unidad declarada: '{est.metadatos.evidencia_unidad[:120]}'.",
            )]
    return declarada, []


def preprocesar(est: Estandarizado, onto: Ontologia) -> Preprocesado:
    valores, incidencias = derivar(est.valores, onto)
    unidad, inc_unidad = elegir_unidad(est, valores, onto)
    factor = FACTOR_UNIDAD[unidad]
    incidencias = list(est.incidencias) + incidencias + inc_unidad

    en_pesos: dict[str, float | None] = {}
    for cid, concepto in onto.conceptos.items():
        c = valores.get(cid)
        en_pesos[cid] = None if c is None else c.valor * (factor if concepto.tipo == "monto" else 1)

    for c in onto.campos:
        if c.requerido and en_pesos[c.id] is None:
            incidencias.append(Incidencia(
                "M4_campo_requerido_faltante", "error",
                f"No se encontró '{c.nombre}' ({c.norma}) en el documento.", c.id,
            ))
        elif not c.requerido and en_pesos[c.id] is None:
            incidencias.append(Incidencia(
                "M4_campo_opcional_faltante", "info", f"No se informa '{c.nombre}' ({c.norma}).", c.id,
            ))
    for regla in onto.reglas:
        incidencias.extend(_aplicar_regla(regla, en_pesos, onto))

    con_problemas = {i.campo for i in incidencias if i.severidad in ("error", "advertencia") and i.campo}
    finales: list[ValorFinal] = []
    for cid, concepto in onto.conceptos.items():
        c = valores.get(cid)
        if c is None:
            if not concepto.es_componente:
                finales.append(ValorFinal(cid, None, None, unidad, "faltante", None, "", 0.0, "faltante"))
            continue
        revisar = (cid in con_problemas or c.confianza < UMBRAL_CONFIANZA or not c.verificado
                   or (bool(inc_unidad) and concepto.tipo == "monto"))
        finales.append(ValorFinal(
            cid, en_pesos[cid], c.valor, unidad, c.metodo, c.pagina, c.evidencia,
            round(c.confianza, 2), "revisar" if revisar else "ok",
        ))
    metadatos = replace(est.metadatos, unidad=unidad)
    return Preprocesado(metadatos, finales, incidencias)
