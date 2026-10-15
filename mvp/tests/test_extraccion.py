"""Pruebas de la parte determinística: números, reglas, derivaciones y validaciones."""

import pymupdf
import pytest

from necc import llm
from necc import m2_procesamiento as m2
from necc import m5_almacenamiento as db
from necc.m3_estandarizacion import _verificar, estandarizar, extraer_por_reglas, metadatos_por_reglas, primer_numero
from necc.m4_preprocesamiento import preprocesar
from necc.modelos import Candidato, DocumentoProcesado, Estandarizado, Metadatos, Pagina
from necc.ontologia import obtener_ontologia
from necc.texto import parse_numero


@pytest.mark.parametrize(
    ("crudo", "esperado"),
    [
        ("4.260.085.575", 4260085575),
        ("$ 6.316.980.282", 6316980282),
        ("(11.351.361)", -11351361),
        ("0,116", 0.116),
        ("0,638980916", 0.638980916),
        ("37.69%", 0.3769),
        ("4112", 4112),
        ("4.268", 4268),
        ("1.234,56", 1234.56),
        ("0.3769", 0.3769),
        ("1.234.", 1234),
        ("$ (1.234)", -1234),
    ],
)
def test_parse_numero_formato_argentino(crudo, esperado):
    assert parse_numero(crudo) == pytest.approx(esperado)


@pytest.mark.parametrize(
    ("ventana", "tipo", "esperado"),
    [
        (" Resolución SSN N° 41.155/2017, alcanzó la suma de $5.363.303.565siendo", "monto", 5363303565),
        (" en los últimos DOCE (12) meses.\n449 casos", "conteo", 449),
        (" (incluidos casos COVID 19) | | 742 |", "conteo", 742),
        (" conforme al punto 30.1.1.3. inciso d) del R.G.A.A.   0,638980916", "ratio", 0.638980916),
        (" para los327 juicios abiertos, asciende ala suma De$323.334.248", "monto", 323334248),
    ],
)
def test_primer_numero_descarta_referencias(ventana, tipo, esperado):
    assert primer_numero(ventana, tipo)[1] == pytest.approx(esperado)


def _extraer(texto: str) -> dict[str, float]:
    doc = DocumentoProcesado([Pagina(1, texto, "texto")], [])
    return {c.concepto: c.valor for c in extraer_por_reglas(doc, [1], obtener_ontologia())}


def test_reglas_cuadro_con_texto_en_celda():
    texto = (
        'Monto de reserva que surge del\n procedimiento de "valuación de reservas      $4.260.085.575\n'
        ' por reclamaciones judiciales"\n Monto de reserva por el Pasivo Global        $893.865.934\n'
        " Cantidad de juicios abiertos, detallando    904 juicios, 512 casos con\n"
        "  los casos con pago parciales                pagos parciales.\n"
        " Total de pagos a la fecha de balance de          $481.312.426\n  los casos abiertos"
    )
    v = _extraer(texto)
    assert v["reserva_reclamaciones_bruta"] == 4260085575
    assert v["reserva_pasivo_global"] == 893865934
    assert v["juicios_abiertos"] == 904
    assert v["juicios_con_pagos_parciales"] == 512
    assert v["total_pagos_casos_abiertos"] == 481312426


def test_reglas_frase_mas_larga_gana():
    texto = (
        "III.- la cantidad de juicios abiertos es de 4112 casos;\n"
        "IV.- la cantidad de juicios abiertos con pagos parciales es de 2178 casos;"
    )
    v = _extraer(texto)
    assert v["juicios_abiertos"] == 4112
    assert v["juicios_con_pagos_parciales"] == 2178


def test_reglas_comparativo_toma_periodo_actual_y_componentes():
    texto = (
        "                                                  2026          2025\n"
        "Saldo a recuperar FFEP – Casos COVID-19     (11.351.361)   (12.064.773)\n"
        "Cantidad de juicios abiertos, sin pagos parciales     5.664     3.451\n"
        "Cantidad de juicios abiertos, con pagos parciales    27.830    26.369\n"
        "Pasivo global por reclamaciones judiciales, neto  33.118.524  36.951.134"
    )
    v = _extraer(texto)
    assert v["reserva_a_cargo_ffep"] == 11351361
    assert v["juicios_abiertos_sin_pagos_parciales"] == 5664
    assert v["juicios_con_pagos_parciales"] == 27830
    assert v["pasivo_global_neto"] == 33118524
    assert "juicios_abiertos" not in v


def test_metadatos_unidad_ignora_mencion_de_estados_en_miles():
    texto = (
        "NOTAS A LOS ESTADOS CONTABLES AL 31 DE MARZO DE 2026\n"
        "expondrán las cifras que los componen en miles de pesos, no obstante las notas e informes se exponen "
        "con la información que surge del sumas y saldos"
    )
    meta = metadatos_por_reglas(DocumentoProcesado([Pagina(1, texto, "texto")], []))
    assert meta.unidad == "pesos"
    assert meta.fecha_balance == "2026-03-31"


def test_metadatos_fecha_inexistente_no_rompe():
    texto = "ESTADOS CONTABLES AL 31 DE JUNIO DE 2026"
    meta = metadatos_por_reglas(DocumentoProcesado([Pagina(1, texto, "texto")], []))
    assert meta.fecha_balance is None


def test_verificacion_exige_misma_magnitud_no_solo_mismos_digitos():
    doc = DocumentoProcesado([Pagina(1, "Total de pagos $ 12.345", "texto")], [])
    otra_magnitud = Candidato("total_pagos_casos_abiertos", "llm", "1.234,5", 1234.5, 1, "", 0.9, False)
    assert not _verificar(otra_magnitud, doc, [1]).verificado
    misma = Candidato("total_pagos_casos_abiertos", "llm", "$12.345", 12345, 1, "", 0.9, False)
    assert _verificar(misma, doc, [1]).verificado


def test_falla_del_llm_degrada_a_reglas_con_incidencia(monkeypatch):
    def falla(*_a, **_k):
        raise RuntimeError("503 UNAVAILABLE")

    monkeypatch.setattr(llm, "disponible", lambda: True)
    monkeypatch.setattr(llm, "generar_json", falla)
    doc = DocumentoProcesado([Pagina(1, "la cantidad de juicios abiertos es de 4112 casos;", "texto")], [])
    est = estandarizar(doc, obtener_ontologia())
    assert est.valores["juicios_abiertos"].valor == 4112
    assert any(i.regla == "M3_llm_error" for i in est.incidencias)


def test_falla_de_ocr_degrada_y_avisa(monkeypatch, tmp_path):
    def falla(_png):
        raise RuntimeError("sin OCR")

    ruta = tmp_path / "escaneado.pdf"
    with pymupdf.open() as pdf:
        pdf.new_page()
        pdf.save(ruta)
    monkeypatch.setattr(m2, "_ocr", falla)
    doc = m2.procesar(ruta)
    assert doc.paginas[0].metodo == "ocr_fallido"
    est = estandarizar(doc, obtener_ontologia(), usar_llm=False)
    assert any(i.regla == "M2_ocr_fallido" for i in est.incidencias)


def test_excel_base_conserva_documentos_sin_entidad(tmp_path):
    with db.conexion(tmp_path / "necc.db") as con:
        for sha, entidad in (("a", None), ("b", None), ("c", "ART X"), ("d", "ART X")):
            doc_id, _ = db.registrar_documento(con, sha, f"{sha}.pdf", f"/tmp/{sha}.pdf", "carpeta")
            con.execute("UPDATE documentos SET estado = 'completado', entidad = ?, fecha_balance = ? WHERE id = ?",
                        (entidad, "2026-03-31" if entidad else None, doc_id))
        tabla = db.tabla_base(con)
    assert sorted(tabla["nombre_archivo"]) == ["a.pdf", "b.pdf", "d.pdf"]
    assert tabla["entidad"].tolist().count(None) == 2


def _cand(concepto, valor):
    return Candidato(concepto, "llm", str(valor), valor, 1, "", 0.95, True)


def _pre(valores: dict[str, float], unidad="pesos", alternativas: dict[str, Metadatos] | None = None):
    est = Estandarizado(Metadatos(unidad=unidad), {k: _cand(k, v) for k, v in valores.items()}, [], [1],
                        metadatos_por_metodo=alternativas or {})
    pre = preprocesar(est, obtener_ontologia())
    return {v.campo: v for v in pre.valores}, pre.incidencias


def test_unidad_inverosimil_se_corrige_con_la_de_otro_metodo_y_se_avisa():
    valores, incidencias = _pre(BASE, unidad="millones de pesos", alternativas={"reglas": Metadatos(unidad="pesos")})
    assert valores["reserva_pasivo_global"].valor == 893865934
    assert valores["reserva_pasivo_global"].estado == "revisar"
    assert any(i.regla == "M4_unidad_corregida" for i in incidencias)
    assert not any(i.regla == "R03_reserva_por_juicio_plausible" for i in incidencias)


BASE = {
    "juicios_abiertos": 904,
    "juicios_con_pagos_parciales": 512,
    "total_pagos_casos_abiertos": 481312426,
    "reserva_pasivo_global": 893865934,
    "reserva_reclamaciones_judiciales": 4260085575,
}


def test_derivaciones_suman_y_restan_componentes():
    valores, _ = _pre({
        "juicios_abiertos_sin_pagos_parciales": 5664,
        "juicios_con_pagos_parciales": 27830,
        "reserva_reclamaciones_bruta": 5363303565,
        "reserva_a_cargo_ffep": 227572305,
        "reserva_a_cargo_reaseguro": 34558258,
        "pasivo_global_neto": 33118524,
        "total_pagos_casos_abiertos": 17833051,
    })
    assert valores["juicios_abiertos"].valor == 33494
    assert valores["juicios_abiertos"].metodo == "derivado"
    assert valores["reserva_reclamaciones_judiciales"].valor == 5101173002
    assert valores["reserva_pasivo_global"].valor == 50951575


def test_inconsistencia_entre_total_y_componentes_genera_incidencia():
    _, incidencias = _pre({**BASE, "juicios_abiertos_sin_pagos_parciales": 100})
    assert any(i.regla == "M4_inconsistencia_componentes" and i.campo == "juicios_abiertos" for i in incidencias)


def test_conversion_de_miles_a_pesos_solo_en_montos():
    valores, _ = _pre(BASE, unidad="miles de pesos")
    assert valores["reserva_pasivo_global"].valor == 893865934000
    assert valores["juicios_abiertos"].valor == 904


def test_unidad_erronea_dispara_alerta_de_reserva_por_juicio():
    _, incidencias = _pre(BASE, unidad="millones de pesos")
    assert any(i.regla == "R03_reserva_por_juicio_plausible" for i in incidencias)
    _, incidencias = _pre(BASE)
    assert not any(i.regla == "R03_reserva_por_juicio_plausible" for i in incidencias)


def test_mas_pagos_parciales_que_juicios_es_error():
    valores, incidencias = _pre({**BASE, "juicios_con_pagos_parciales": 1000})
    assert any(i.regla == "R01_pagos_parciales_menor_total" and i.severidad == "error" for i in incidencias)
    assert valores["juicios_con_pagos_parciales"].estado == "revisar"


def test_campo_requerido_faltante_es_error():
    valores, incidencias = _pre({k: v for k, v in BASE.items() if k != "reserva_pasivo_global"})
    assert valores["reserva_pasivo_global"].estado == "faltante"
    assert any(i.regla == "M4_campo_requerido_faltante" and i.campo == "reserva_pasivo_global" for i in incidencias)
