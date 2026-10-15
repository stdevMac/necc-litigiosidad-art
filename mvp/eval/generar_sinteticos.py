"""Genera los documentos sintéticos de prueba a partir de los ejemplos de 'Info NECC.docx'.

Cubren variantes que no aparecen en los 3 PDFs reales:
  A. cuadro escaneado (imagen) en una nota con texto  -> OCR
  B. cuadro comparativo 2026/2025 escaneado, en miles  -> OCR + unidad + año correcto
  C. prosa donde la reserva hay que restarle FFEP y reaseguro (caso Latitud Sur)

Uso:  uv run python eval/generar_sinteticos.py "../Info NECC.docx"
"""

from __future__ import annotations

import sys
import zipfile
from pathlib import Path

import pymupdf

DESTINO = Path(__file__).resolve().parents[1] / "data" / "muestras" / "sinteticos"
AVISO = "DOCUMENTO SINTÉTICO DE PRUEBA - construido con fragmentos de 'Info NECC.docx'"

TEXTO_C = (
    "NOTA 7: RECLAMACIONES JUDICIALES A.R.T. - RESOLUCIÓN N° 41.155/2017\n\n"
    "La Reserva por reclamaciones judiciales, en cumplimiento de las modificaciones introducidas por la "
    "Resolución SSN N° 41.155/2017, alcanzó la suma de $5.363.303.565siendo $227.572.305a cargo del fondo "
    "fiduciario de enfermedades profesionales y $34.558.258 a cargo del Reaseguro. Asimismo, el Pasivo Global "
    "Mínimo para los327 juicios abiertos por Riesgos del Trabajo, asciende ala suma De$323.334.248. De 327casos "
    "abiertos, 264 contienen pagos parciales por un total de$385.170.807, nuestro promedio de Reserva por caso es "
    "de $16.401.540. La aseguradora realiza sus reservas teniendo en cuenta el porcentaje de incapacidad, caso por "
    "caso, y los mecanismos de ajustes de reservas de la Ley de Riesgos del Trabajo."
)


def _pagina(doc: pymupdf.Document, encabezado: str) -> tuple[pymupdf.Page, float]:
    pagina = doc.new_page(width=595, height=842)
    pagina.insert_textbox(pymupdf.Rect(50, 40, 545, 160), encabezado, fontsize=10, fontname="helv", align=1)
    pagina.insert_textbox(pymupdf.Rect(50, 800, 545, 830), AVISO, fontsize=7, fontname="helv", align=1)
    return pagina, 170


def _con_imagen(destino: Path, encabezado: str, imagen: bytes) -> None:
    doc = pymupdf.open()
    pagina, y = _pagina(doc, encabezado)
    ancho_px, alto_px = pymupdf.Pixmap(imagen).width, pymupdf.Pixmap(imagen).height
    ancho = 495
    pagina.insert_image(pymupdf.Rect(50, y, 50 + ancho, y + ancho * alto_px / ancho_px), stream=imagen)
    doc.save(destino)


def main(docx: Path) -> None:
    DESTINO.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(docx) as z:
        img_a = z.read("word/media/image1.png")
        img_b = z.read("word/media/image2.png")

    _con_imagen(
        DESTINO / "sintetico_A_cuadro_en_imagen.pdf",
        "ASEGURADORA DE PRUEBA A ART S.A.\n"
        "NOTAS A LOS ESTADOS CONTABLES AL 31 DE MARZO DE 2026\n\n"
        "Nota 6 - Reclamaciones judiciales (Art. 33.4.1.6.1.9 y 30.1.1.3 d) RGAA)",
        img_a,
    )
    _con_imagen(
        DESTINO / "sintetico_B_comparativo_en_imagen.pdf",
        "MUTUAL DE PRUEBA B ART\n"
        "NOTAS A LOS ESTADOS CONTABLES AL 31 DE MARZO DE 2026\n"
        "(Cifras expresadas en miles de pesos)\n\n"
        "Nota 9 - Reclamaciones judiciales según punto 33.4.1.6.1.6 del R.G.A.A.",
        img_b,
    )
    doc = pymupdf.open()
    pagina, y = _pagina(doc, "LATITUD SUR ART S.A. (sintético)\nNOTAS A LOS ESTADOS CONTABLES AL 31 DE MARZO DE 2026")
    pagina.insert_textbox(pymupdf.Rect(50, y, 545, 780), TEXTO_C, fontsize=10, fontname="helv")
    doc.save(DESTINO / "sintetico_C_prosa_con_resta.pdf")
    for p in sorted(DESTINO.glob("*.pdf")):
        print(p)


if __name__ == "__main__":
    main(Path(sys.argv[1]))
