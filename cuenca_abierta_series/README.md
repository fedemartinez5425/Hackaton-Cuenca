# Cuenca Abierta: series de datos (v1.0)

Generador reproducible de las series del Desafío 01 (Hackeando la Minería 2026) para la cuenca del río Jáchal.
Mezcla **datos reales** (caudales de Hidráulica, análisis publicados) con **datos rellenados** y **simulados**.
Cada fila dice cuál de los tres es, y todo queda sellado con hashes encadenados.

```bash
pip install -r requirements.txt
python generar.py            # ~75 s: escribe todo en salida/
python verificar_sello.py    # recalcula el sello: ✓ íntegro
python verificar_sello.py --demo-alterar   # toca UNA lectura vieja y muestra cómo se rompe la cadena
python simular_en_vivo.py --repetir-desde 2025-10-30 --cada 1 [--url http://api/lecturas]
```
Semilla fija (`SEMILLA = 20251104` en `cuenca/config.py`): la misma versión siempre produce los mismos datos y el mismo hash de cabeza.

## Qué hay en `salida/`

| Archivo | Qué es | Filas aprox. |
|---|---|---|
| `caudal_mensual_pp.csv` | Piedras Pintadas mensual 2001–2026: 171 meses **medidos**, 5 **rellenados**, resto **simulado** | 310 |
| `caudal_diario.csv` | Caudal diario PP y PAC 2001-03 → 2026-12 (sellado) | 18.900 |
| `caudal_objetivos_anuales_pac.csv` | Caudal medio anual al que se ancló cada año simulado, con su procedencia | 12 |
| `lecturas_sensores.parquet` / `.csv.gz` | Telemetría cada 15 min, 3 puntos, jul-2024 → 7-oct-2026 (sellado) | 1,35 M |
| `muestreos_laboratorio.csv` | Metales, aniones y campo: real (tesis 2016, prensa 2025) + simulado 2024–2026 (sellado) | 3.300 |
| `cadena_lotes.csv`, `sello_publicado.json` | La cadena de 60.202 lotes y el hash de cabeza que se publica | |
| `anomalias.csv` | Eventos insertados a propósito y qué debería hacer la plataforma con cada uno | 7 |
| `semaforo_diario.csv` | Color por punto, uso y día + `cambio_inusual` + frase para el bot | |
| `semaforo_actual.json` | Último día, listo para el bot ("¿cómo está el agua en Pachimoco?") | |
| `semaforo_laboratorio.csv` | Cada resultado de laboratorio contra cada uso, con "no evaluable" y comparación aguas arriba | |
| `ica_ccme.csv` | Índice de calidad CCME (el método de ACUMAR) por punto, año y uso | |
| `muestra_lecturas_ultimas_48h.csv` | Recorte chico para mirar rápido o para tests | |
| `graficos/` | 9 PNG de validación | |

`referencia/` tiene las tablas de entrada: caudal real de Hidráulica, puntos de monitoreo, niveles guía por uso, anclas anuales de caudal y rangos de referencia.

## Esquema de una lectura (sensores y caudal)

```
punto_id, timestamp_utc, variable, valor, unidad, origen, metodo, fuente, [anomalia_id], lote_id, hash_lote
```
- `origen`: `medido` | `rellenado` | `simulado`. Regla: **un rellenado o simulado nunca se presenta ni se sella como medido** (el campo `origen` entra en el hash).
- `metodo`: `aforo`, `sensor`, `laboratorio`, `medicion_campo`, `interpolacion_lineal`, `interpolacion_perfil_diario`, `interpolacion_estacional`, `desagregacion_conservativa`, `generador_*`, `modelo_embalse(...)`.
- `anomalia_id`: la "respuesta" de la demo (qué evento se insertó). **No** se sella y no se muestra al público como diagnóstico.
- Timestamps en UTC (San Juan = UTC−3). Unidades: m3/s, pH, µS/cm, °C, mg/l, UNT.
- Laboratorio agrega: `muestra_id, campana_id, fecha_precision, bajo_ld, limite_deteccion, fraccion, laboratorio, fuente_url, nota`.

## Cómo se construyó cada serie

**Caudal (Piedras Pintadas, PP).** Base real: medias mensuales de Hidráulica SJ (mar-2001 → oct-2015).
- Huecos internos (5 meses, camino cortado): interpolación de la anomalía logarítmica respecto de la climatología del mes → `rellenado`.
- Mensual → diario: interpolación PCHIP sobre el volumen acumulado (conserva exacta la media mensual medida; error máx. 0,0001 m³/s) + ruido AR(1), más fuerte en deshielo (nov–feb). Como no existe dato diario medido, **ningún valor diario es `medido`**: los de meses medidos son `rellenado` (`desagregacion_conservativa`) y `base_mensual` dice de qué mes vienen.
- Nov-2015 en adelante: `simulado`. Cada año hidrológico (oct–sep) está anclado a una referencia pública: pronósticos oficiales del Jáchal (2022/23: 205 hm³, 2023/24: 116 hm³, 2025/26: 190 hm³ ≈ 6 m³/s) y derrames observados del río San Juan 2018/19–2021/22 trasladados al Jáchal. Los años sin referencia se interpolan. Ver `referencia/anclas_caudal_anual.csv` y `salida/caudal_objetivos_anuales_pac.csv`.

**Caudal en Pachimoco (PAC).** Simulado: PP suavizado por el embalse (media móvil exponencial de 20 días) × k = 0,95 (= media histórica del Jáchal 326 hm³/año ÷ media medida de PP). En 2025/26 promedia 6,0 m³/s, como el pronóstico.

**Telemetría (cada 15 min).** Tres puntos: PP (río, aguas arriba), EMB (embalse Cuesta del Viento) y PAC (Pachimoco, donde existe la estación real del Observatorio Ambiental).
Cada variable = nivel + ciclo anual + ciclo diario + ruido AR(1) + acople:
- conductividad ∝ caudal^−0,2 (dilución), anclada a 869 µS/cm con 34 m³/s (tesis UNCuyo, nov-2016);
- turbidez ∝ caudal^1,4 (arrastre de sedimento); en una crecida la turbidez sube antes que el caudal;
- OD = saturación(temperatura, altitud) × fracción con ciclo diario;
- el embalse retrasa y suaviza la química de aguas arriba (60 días para la conductividad).

**Huecos de los sensores.** Cortes cortos de comunicación (~1 % de las lecturas): ≤ 1 h se rellenan con interpolación lineal; de 1 h a 6 h, con el perfil del día anterior. Todo eso queda como `rellenado` y **el semáforo no lo usa**. Cortes largos (sensor caído) quedan sin filas: gris.

**Anomalías insertadas** (`anomalias.csv`):

| id | Qué | Dónde y cuándo | Qué debería pasar |
|---|---|---|---|
| A01 | Hipoxia: OD de ~8,5 a ~2 mg/l, agua más cálida, pH −0,4 | EMB, 31-oct → 7-nov-2025 (tipo 4-nov-2025) | Rojo vida acuática + aviso |
| A02, A03 | Crecida estival: caudal ×4, turbidez ~390 UNT, conductividad −25 % | PP, 11-feb-2025 y 23-ene-2026 | Alerta de cambio inusual con contexto "crecida", no "contaminación" |
| A04 | Deriva del sensor de conductividad +18 % en 3 semanas | PAC, junio 2025 | Control de calidad; no alerta pública |
| A05, A06 | Sensor caído 4 días / 2 días | EMB mar-2026, PP jul-2025 | Gris |
| QC_ESPURIA | ~220 lecturas absurdas aisladas | todos | Filtrar en control de calidad |

**Laboratorio.**
- Real (`medido`): tesis Acosta Said 2018 (UNCuyo), muestreo de nov-2016 en río Blanco, La Palca y Jáchal pos-confluencia (pH, CE, B, As, Zn, Fe, Mn, Pb, Cr, Hg, Ag, Ba, Tl, Cu); cifras de prensa del análisis encargado por la ONG en nov-2025 (As 0,57; Al 6,7; B 4,0 mg/l; punto `NN` = no publicado).
- Simulado: campañas oficiales trimestrales en 9 puntos (mensuales en EMB y PAC), campaña post-evento el 5-nov-2025 y monitoreo participativo semestral. Los solutos conservativos (As, B, sulfato, cloruro, SDT) escalan con la conductividad del día; los metales **totales** suben con la turbidez (van pegados al sedimento). Por eso el aluminio total puede ser alto en agua turbia sin que cambie nada disuelto: ese es el argumento del comparador.
- **Cianuro y mercurio simulados están siempre bajo el límite de detección.** No inventamos detecciones de contaminantes sensibles: las únicas cifras de Hg son las reales de la tesis.

## Semáforo

- **Por uso**, con la tabla `referencia/niveles_guia.csv` (93 filas): Decreto 831/93 Anexo II (bebida con tratamiento, vida acuática, riego, ganado), CAA art. 982 (agua de red), FAO-29 (salinidad para riego y ganado) y CCME (OD y pH para vida acuática, a verificar).
- verde / amarillo (a menos de 10 % del límite o con umbral propio) / rojo / gris (sin datos, solo rellenado, o límite de detección mayor que el nivel guía: "no evaluable").
- `cambio_inusual`: la mediana del día se aparta más de 4 desvíos robustos de los 30 días previos. Sirve para turbidez y temperatura, que no tienen nivel guía, y sube un verde a amarillo.
- Las frases del bot aclaran siempre que **el sensor no mide arsénico ni metales**.
- Lo que muestra la demo: el Jáchal da **amarillo para riego casi siempre** (conductividad > 700 µS/cm) y el boro y el arsénico superan niveles guía **también aguas arriba**. Con el contexto aguas arriba (`vs_aguas_arriba`), el número deja de servir para cualquier relato.

## Supuestos y pendientes (revisar con Juani)

- Las tablas del **Anexo IV de la Ley 24.585** no las encontré en texto; uso las del **Decreto 831/93**, que es la referencia habitual por uso. Están tomadas de una transcripción secundaria (ecofield.net): `estado = transcripcion_a_confirmar`. La fila de cinc para ganado (50 µg/l) parece un error de transcripción y queda fuera del semáforo hasta confirmarla.
- Vida acuática: los metales que dependen de la dureza usan la columna > 180 mg/l CaCO₃ (aguas duras, supuesto). OD mínimo 5,5 mg/l (CCME agua templada); para truchas sería 6,5.
- Coordenadas: solo PP es oficial; BLA, PAL y JCO son medias de los sitios de la tesis; el resto sigue **A RELEVAR** (no se inventaron). Las altitudes de EMB y PAC son aproximadas.
- La química de TAG e IGL no tiene datos públicos (supuesto declarado en la columna `nota`).
- 2026/27 repite el año 2025/26 hasta que se publique el pronóstico oficial: cargarlo en `referencia/anclas_caudal_anual.csv`.
- La serie satelital (Sentinel-2) queda para una v2: desde este entorno no se puede bajar de Copernicus.

## Para Mati (API y bot)

- Ingesta: `simular_en_vivo.py --url …` hace POST de bloques JSON (17 lecturas por bloque de 15 min). En modo `--repetir-desde 2025-10-30 --cada 1` el pitch muestra la hipoxia en ~10 minutos.
- El sellado de referencia está en `cuenca/sellado.py` (sin dependencias raras: hashlib + pandas). La especificación está en el docstring, así cualquiera puede reimplementar el verificador.
- `semaforo_actual.json` ya trae color y frase por punto y uso.

## Fuentes

- Hidráulica SJ, Piedras Pintadas: https://hidraulica.sanjuan.gob.ar/datos%20y%20estadisticas/pintadas2.html
- Acosta Said (2018), tesis UNCuyo: https://25.bdigital.uncu.edu.ar/objetos_digitales/10871/tesis-irnr-abraham-acosta-said-nahir-2018.pdf
- Pronósticos Jáchal 2022/23–2023/24 y media histórica: https://www.diariohuarpe.com/nota/el-pronostico-hidrico-en-san-juan-es-peor-que-el-del-2022-2023-y-sera-mas-seco-2023101211140
- Pronóstico 2025/26: https://www.diariodecuyo.com.ar/economia/pronostico-hidrico-oficial-para-el-periodo-octubre-2025-septiembre-2026-se-preve-que-sea-muy-seco-con-un-derrame-medio-de-apenas-950-hm3-1783078.html
- Derrames río San Juan: https://www.tiempodesanjuan.com/economia/san-juan-vive-otra-sequia-pero-la-mas-cruel-fue-hace-50-anos-canales-preparados-y-diques-n360893 y https://www.diariodecuyo.com.ar/suplementos/Este-es-el-ano-mas-seco-de-los-ultimos-30-en-el-rio-San-Juan-20191102-0016.html
- Decreto 831/93 Anexo II (transcripción): https://www.ecofield.net/Legales/Residuos_pel/ley24051-dec831-93/dec831-93_anexo%20II%20Tablas.htm
- CAA cap. XII art. 982: https://w3.fcq.unc.edu.ar/sites/default/files/biblioteca/CAPITULO_XII_Bebidas_Hidricas_Agua_y_agua_gasificada.pdf · arsénico 0,01 mg/l: https://e-legis-ar.msal.gov.ar/legisalud/migration/pdf/scsresc33_2023.pdf
- Estación Pachimoco: https://www.tiempodesanjuan.com/sanjuan/2021/7/27/por-primera-vez-se-instalo-un-monitoreo-del-agua-en-el-rio-jachal-318649.html
- Caso nov-2025: ver `LEEME_contexto` del traspaso.
