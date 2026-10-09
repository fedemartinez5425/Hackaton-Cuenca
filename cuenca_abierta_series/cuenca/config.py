"""Parámetros del generador de series de Cuenca Abierta.

Todo lo que es un supuesto está marcado con SUPUESTO y una nota de dónde salió.
Cambiar un número acá cambia las series; la semilla fija las hace reproducibles.
"""
from pathlib import Path

import pandas as pd

RAIZ = Path(__file__).resolve().parent.parent
REFERENCIA = RAIZ / "referencia"
SALIDA = RAIZ / "salida"

SEMILLA = 20251104  # fecha del evento de Cuesta del Viento, para recordarla
VERSION_GENERADOR = "cuenca-abierta-gen v1.0"
FUENTE_SIMULADA = "Generador Cuenca Abierta v1.0 (dato simulado)"

TZ_LOCAL = "America/Argentina/San_Juan"  # UTC-3 todo el año

# --------------------------------------------------------------------------
# Ventanas temporales
# --------------------------------------------------------------------------
CAUDAL_INICIO = "2001-03-01"      # primer mes medido en Piedras Pintadas
CAUDAL_FIN = "2026-12-31"         # se extiende para que el simulador en vivo tenga caudal
# El último mes medido de la tabla de Hidráulica es oct-2015; se detecta solo.
SENSORES_INICIO = "2024-07-01 00:00"   # UTC; comienzo del año hidrológico 2024/25
SENSORES_FIN = "2026-10-08 00:00"      # UTC; "hoy" al generar
PASO_SENSOR = "15min"

# --------------------------------------------------------------------------
# Caudal
# --------------------------------------------------------------------------
# Media histórica del derrame del río Jáchal: 326 hm3/año (Hidráulica SJ vía Diario Huarpe, 2023)
# => 10,33 m3/s. Años simulados anclados a referencias/anclas_caudal_anual.csv:
#   - pronósticos oficiales del Jáchal (2022/23, 2023/24, 2025/26)
#   - derrames observados del río San Juan (2018/19 a 2021/22), trasladados al Jáchal
#     con r_jachal = r_sanjuan ** EXPONENTE_SJ_JACHAL (SUPUESTO: el Jáchal varía menos;
#     0,8 sale de comparar los años en que hay dato de ambos ríos).
#   - años sin referencia: interpolación log-lineal entre vecinos + ruido.
DERRAME_MEDIO_JACHAL_HM3 = 326.0
CAUDAL_MEDIO_JACHAL_HIST = DERRAME_MEDIO_JACHAL_HM3 * 1e6 / (365.25 * 86400)
EXPONENTE_SJ_JACHAL = 0.8
SD_ANIO_SIN_ANCLA = 0.10
# SUPUESTO: PAC (Pachimoco) = k * caudal de PP suavizado por el embalse, con
# k = media histórica del Jáchal / media medida de PP (pérdidas, riego, evaporación).
TAU_EMBALSE_DIAS = 20
# Variabilidad interanual: AR(1) sobre log del factor anual (calibrado con 2001-2016 abajo)
AR_ANUAL_PHI = 0.55
AR_MENSUAL_PHI = 0.6
AR_MENSUAL_SD = 0.12
RUIDO_DIARIO_PHI = 0.8
RUIDO_DIARIO_SD = {"deshielo": 0.10, "resto": 0.05}   # deshielo = nov-feb
HUECO_CORTO_MESES = 2

# --------------------------------------------------------------------------
# Sensores: calibración por punto
# --------------------------------------------------------------------------
# Fuente principal de calibración química: Acosta Said (2018), tesis UNCuyo,
# muestreo nov-2016: río Jáchal pos-confluencia CE 869 µS/cm, pH 7,61; río Blanco
# CE 2105 µS/cm; La Palca CE 707 µS/cm; caudal del Jáchal en Pachimoco ese día 34 m3/s.
SENSORES = {
    "PP": {
        "altitud": 1920,  # oficial
        "variables": ["caudal", "ph", "conductividad", "temperatura", "oxigeno_disuelto", "turbidez"],
        "ce_ref": 870.0, "q_ref": 30.0, "ce_exp": -0.20,      # SUPUESTO exponente (dilución moderada); ancla = tesis
        "turb_a": 20.0, "turb_q0": 10.0, "turb_exp": 1.4,       # SUPUESTO: río de deshielo cargado de sedimento
        "ph_media": 7.6,                                       # tesis: 7,49-7,76
        "t_media": 10.0, "t_amp_anual": 6.0, "t_amp_diaria": 2.5,  # SUPUESTO
        "od_frac_sat": 0.97, "od_amp_diaria": 0.03,
    },
    "EMB": {
        "altitud": 1590,  # SUPUESTO aproximado (coordenadas A RELEVAR)
        "variables": ["ph", "conductividad", "temperatura", "oxigeno_disuelto", "turbidez"],
        "ce_tau_dias": 60, "ce_factor_evap": 1.05,
        "turb_base": 3.0, "turb_frac": 0.06, "turb_tau_dias": 7,
        "ph_media": 8.1, "ph_amp_verano": 0.15,
        "t_media": 13.5, "t_amp_anual": 7.0, "t_amp_diaria": 0.8,
        "od_frac_sat": 1.00, "od_amp_diaria": 0.07,
    },
    "PAC": {
        "altitud": 1170,  # SUPUESTO aproximado (coordenadas A RELEVAR)
        "variables": ["caudal", "ph", "conductividad", "temperatura", "oxigeno_disuelto", "turbidez"],
        "ce_tau_dias": 2, "ce_factor": 1.12,
        "turb_factor_emb": 1.5, "turb_q_a": 2.0, "turb_q0": 6.0, "turb_exp": 1.2,
        "ph_media": 7.9,
        "t_media": 14.0, "t_amp_anual": 6.5, "t_amp_diaria": 2.0,
        "od_frac_sat": 0.98, "od_amp_diaria": 0.04,
    },
}
DIA_PICO_TEMPERATURA = 25  # 25 de enero (día del año)

UNIDADES = {
    "caudal": "m3/s", "ph": "pH", "conductividad": "µS/cm", "temperatura": "°C",
    "oxigeno_disuelto": "mg/l", "turbidez": "UNT",
}
DECIMALES = {
    "caudal": 3, "ph": 2, "conductividad": 0, "temperatura": 2,
    "oxigeno_disuelto": 2, "turbidez": 1,
}

# Huecos de comunicación aleatorios y su relleno
PROB_INICIO_HUECO = 0.0015       # por punto y por intervalo de 15 min
HUECO_MAX_INTERVALOS = 12        # 3 h
RELLENO_LINEAL_MAX = 4           # <= 1 h: interpolación lineal
RELLENO_DIURNO_MAX = 24          # <= 6 h: interpolación con el perfil del día anterior
# Huecos más largos NO se rellenan: quedan sin filas (sensor caído => gris en el semáforo)
PROB_ESPURIA = 0.0002            # lecturas espurias aisladas (para probar el control de calidad)


def ts(s: str) -> pd.Timestamp:
    """Fecha/hora local de San Juan -> Timestamp UTC."""
    return pd.Timestamp(s, tz=TZ_LOCAL).tz_convert("UTC")


# --------------------------------------------------------------------------
# Anomalías insertadas a propósito (todas SIMULADAS)
# --------------------------------------------------------------------------
ANOMALIAS = [
    dict(anomalia_id="A01", tipo="hipoxia_embalse", punto_id="EMB",
         variables="oxigeno_disuelto;temperatura;ph;turbidez",
         inicio=ts("2025-10-31 00:00"), pico=ts("2025-11-03 14:00"), fin=ts("2025-11-07 00:00"),
         intensidad=0.75,
         descripcion="Caída de oxígeno disuelto a ~2 mg/l con agua más cálida y baja de pH, como en una floración/estratificación.",
         inspiracion="Mortandad de peces en Cuesta del Viento, 4-nov-2025 (hipótesis oficial: falta de oxígeno). Valores SIMULADOS.",
         esperado="Rojo para vida acuática en EMB; alerta de cambio inusual; aviso a suscriptores de la zona."),
    dict(anomalia_id="A02", tipo="crecida_turbidez", punto_id="PP",
         variables="caudal;turbidez;conductividad",
         inicio=ts("2025-02-11 15:00"), pico=ts("2025-02-11 19:00"), fin=ts("2025-02-14 00:00"),
         intensidad=3.5,
         descripcion="Crecida estival por tormenta: el caudal se multiplica ~4x, la turbidez sube antes que el caudal y la conductividad baja por dilución.",
         inspiracion="Crecidas aluvionales de verano en la cuenca (caso genérico).",
         esperado="Alerta de cambio inusual en turbidez; NO es contaminación: contexto 'crecida'."),
    dict(anomalia_id="A03", tipo="crecida_turbidez", punto_id="PP",
         variables="caudal;turbidez;conductividad",
         inicio=ts("2026-01-23 17:00"), pico=ts("2026-01-23 21:00"), fin=ts("2026-01-26 00:00"),
         intensidad=2.5,
         descripcion="Segunda crecida estival, menor.",
         inspiracion="Caso genérico.",
         esperado="Igual que A02."),
    dict(anomalia_id="A04", tipo="deriva_sensor", punto_id="PAC",
         variables="conductividad",
         inicio=ts("2025-06-02 00:00"), pico=ts("2025-06-23 10:00"), fin=ts("2025-06-23 10:00"),
         intensidad=0.18,
         descripcion="El sensor de conductividad se descalibra y sube linealmente hasta +18 % en 3 semanas; vuelve al valor real tras la recalibración.",
         inspiracion="Falla instrumental típica (ensuciamiento de la celda).",
         esperado="El control de calidad debería marcarla (salto al recalibrar, desacople con aguas arriba). No debe disparar alerta pública."),
    dict(anomalia_id="A05", tipo="sensor_caido", punto_id="EMB",
         variables="todas",
         inicio=ts("2026-03-10 14:00"), pico=None, fin=ts("2026-03-14 10:00"),
         intensidad=None,
         descripcion="Sin transmisión ~4 días (corte de energía/módem). No hay filas en ese lapso.",
         inspiracion="Falla operativa típica.",
         esperado="Semáforo gris 'sin datos'; no rellenar para el público."),
    dict(anomalia_id="A06", tipo="sensor_caido", punto_id="PP",
         variables="todas",
         inicio=ts("2025-07-18 06:00"), pico=None, fin=ts("2025-07-20 13:00"),
         intensidad=None,
         descripcion="Sin transmisión ~2 días en invierno (congelamiento).",
         inspiracion="Falla operativa típica en alta montaña.",
         esperado="Semáforo gris."),
]

# --------------------------------------------------------------------------
# Laboratorio
# --------------------------------------------------------------------------
LAB_INICIO = "2024-01-01"
LAB_FIN = "2026-09-30"
