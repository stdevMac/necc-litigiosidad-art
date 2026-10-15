# Resultados de evaluación

Documentos: 6 · localización correcta: 6/6

| Método | Campos correctos | Exactitud | Documentos 100 % | Unidad correcta |
|---|---:|---:|---:|---:|
| reglas | 54/54 | 100.0% | 6/6 | 6/6 |
| llm | 51/54 | 94.4% | 5/6 | 5/6 |
| hibrido | 54/54 | 100.0% | 6/6 | 6/6 |

## Por documento

| Documento | Variante | reglas | llm | hibrido | Revisar (híbrido) |
|---|---|---:|---:|---:|---:|
| doc_1.pdf | Cuadro de 2 columnas con texto libre en celda | 9/9 | 9/9 | 9/9 | 0 |
| doc_2.pdf | Lista con numerales romanos en prosa; EECC en miles pero notas en pesos | 9/9 | 9/9 | 9/9 | 0 |
| doc_3.pdf | Cuadro comparativo 2026/2025 en miles; juicios por separado; reserva neta de FFEP | 9/9 | 9/9 | 9/9 | 0 |
| sintetico_A_cuadro_en_imagen.pdf | Cuadro escaneado (imagen) — requiere OCR | 9/9 | 6/9 | 9/9 | 4 |
| sintetico_B_comparativo_en_imagen.pdf | Cuadro comparativo 2026/2025 escaneado, en miles — requiere OCR | 9/9 | 9/9 | 9/9 | 0 |
| sintetico_C_prosa_con_resta.pdf | Prosa; la reserva hay que restarle FFEP y reaseguro | 9/9 | 9/9 | 9/9 | 0 |

## Errores

- **sintetico_A_cuadro_en_imagen.pdf** · llm · Total de pagos de los casos abiertos con juicios: esperado `6197244842`, obtenido `6197244842000000.0`
- **sintetico_A_cuadro_en_imagen.pdf** · llm · Reserva por Pasivo Global: esperado `836104837`, obtenido `836104837000000.0`
- **sintetico_A_cuadro_en_imagen.pdf** · llm · Reserva por reclamaciones judiciales (a cargo de la entidad): esperado `4651156507`, obtenido `4651156507000000.0`
