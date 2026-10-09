"""Muestreos de laboratorio: pocos puntos, metales y aniones.

Incluye:
  - datos REALES: tesis UNCuyo (nov-2016, 3 puntos) y cifras de prensa del análisis de nov-2025 (punto no publicado);
  - campañas SIMULADAS: oficiales trimestrales (mensuales en EMB y PAC), una campaña post-evento
    (5-nov-2025) y monitoreo participativo semestral.
La química simulada es coherente con la telemetría: los solutos conservativos (As, B, sulfato, cloruro, SDT)
escalan con la conductividad del día y los metales totales suben con la turbidez (van pegados al sedimento).
"""
import numpy as np
import pandas as pd

from . import config as C
from .sensores import _conductores_diarios
from .util import od_saturacion, rng_para

TESIS = ("Acosta Said (2018), tesis UNCuyo: muestreo primera semana nov-2016",
         "https://25.bdigital.uncu.edu.ar/objetos_digitales/10871/tesis-irnr-abraham-acosta-said-nahir-2018.pdf")
ONG = ("Diario de Cuyo: cifras del análisis encargado por Asamblea Jáchal No Se Toca a un laboratorio de la UNCuyo",
       "https://www.diariodecuyo.com.ar/cuyominero/desde-la-uncuyo-se-refirieron-al-estudio-que-una-ong-uso-para-denunciar-presunta-contaminacion-del-rio-en-jachal-no-avalan-esa-hipotesis-1806535.html")

UNIDAD = {"ph": "pH", "conductividad": "µS/cm", "temperatura": "°C", "oxigeno_disuelto": "mg/l"}
LD = {  # límites de detección SUPUESTOS (típicos de ICP-MS / métodos estándar)
    "arsenico": 0.005, "boro": 0.05, "aluminio": 0.01, "hierro": 0.01, "manganeso": 0.001,
    "cobre": 0.002, "cinc": 0.005, "plomo": 0.001, "cadmio": 0.0005, "mercurio": 0.0005,
    "cianuro_total": 0.005, "cromo_total": 0.001, "niquel": 0.002, "nitrato": 0.5,
    "sulfato": 1.0, "cloruro": 1.0, "solidos_disueltos_totales": 10.0,
}

# Química base por punto, a la conductividad de referencia `ce`.
# Fuente: tesis (BLA, PAL, JCO). SUPUESTO: resto, marcado en `calibracion`.
BASE = {
    "BLA": dict(ce=2105, ph=7.57, arsenico=0.12, boro=3.68, cinc=0.31, hierro_d=0.20, manganeso_d=0.0016, calib="tesis"),
    "PAL": dict(ce=707, ph=7.52, arsenico=0.04, boro=1.06, cinc=0.19, hierro_d=0.01, manganeso_d=0.010, calib="tesis", hg=True),
    "JCO": dict(ce=869, ph=7.61, arsenico=0.04, boro=1.16, cinc=0.27, hierro_d=0.06, manganeso_d=0.020, calib="tesis"),
    "TAG": dict(ce=600, ph=7.5, arsenico=0.03, boro=0.90, cinc=0.10, hierro_d=0.02, manganeso_d=0.010,
                calib="SUPUESTO: sin datos públicos; parecido a La Palca", hg=True),
    "IGL": dict(ce=1200, ph=7.7, arsenico=0.15, boro=2.0, cinc=0.10, hierro_d=0.05, manganeso_d=0.015,
                calib="SUPUESTO: la prensa menciona arsénico muy alto en el arroyo Iglesia, sin cifras"),
    "EMB": dict(ce=869, ph=8.1, arsenico=0.04, boro=1.16, cinc=0.05, hierro_d=0.03, manganeso_d=0.015,
                calib="química de JCO escalada con la conductividad del embalse"),
    "LAM": dict(ce=869, ph=8.1, arsenico=0.04, boro=1.16, cinc=0.05, hierro_d=0.03, manganeso_d=0.015,
                calib="ídem EMB"),
    "JAB": dict(ce=869, ph=7.9, arsenico=0.04, boro=1.16, cinc=0.06, hierro_d=0.05, manganeso_d=0.02,
                calib="química de JCO escalada con la conductividad aguas abajo del dique"),
    "PAC": dict(ce=869, ph=7.9, arsenico=0.04, boro=1.16, cinc=0.06, hierro_d=0.06, manganeso_d=0.03,
                calib="química de JCO escalada con la conductividad de Pachimoco"),
}
ALTITUD = {"BLA": 2700, "PAL": 2700, "JCO": 2500, "TAG": 3000, "IGL": 1900, "EMB": 1590, "LAM": 1590,
           "JAB": 1550, "PAC": 1170}  # SUPUESTO: solo para la saturación de OD
# metales totales por unidad de turbidez (mg/l por UNT) — SUPUESTO; Al calibrado para que ~330 UNT
# den ~6,7 mg/l como la cifra de prensa de nov-2025
POR_UNT = {"aluminio": 0.02, "hierro": 0.03, "manganeso": 0.001, "plomo": 0.00005, "cromo_total": 0.0001,
           "niquel": 0.0001, "cobre": 0.0002, "cinc": 0.0005}


def _real() -> pd.DataFrame:
    filas = []
    tesis = {  # ppb -> mg/l; None = no detectado
        "BLA": {"ph": 7.57, "conductividad": 2105.33, "boro": 3680, "arsenico": 120, "cinc": 310, "hierro": 200,
                "bario": 50, "manganeso": 1.6, "plomo": None, "cromo_total": None, "plata": 0.24,
                "mercurio": None, "talio": None, "cobre": None},
        "PAL": {"ph": 7.52, "conductividad": 707.33, "boro": 1060, "arsenico": 40, "cinc": 190, "hierro": 10,
                "bario": 20, "manganeso": 10, "plomo": 0.08, "cromo_total": None, "plata": 0.08,
                "mercurio": 2.9, "talio": 0.04, "cobre": None},
        "JCO": {"ph": 7.61, "conductividad": 869.33, "boro": 1160, "arsenico": 40, "cinc": 270, "hierro": 60,
                "bario": 20, "manganeso": 20, "plomo": 1.10, "cromo_total": 4.9, "plata": None,
                "mercurio": None, "talio": 0.48, "cobre": None},
    }
    for p, vals in tesis.items():
        for v, x in vals.items():
            campo = v in ("ph", "conductividad")
            filas.append(dict(
                campana_id="TESIS-2016-11", punto_id=p, fecha_local="2016-11-03 12:00", fecha_precision="semana",
                variable=v, valor=(x if campo else (None if x is None else x / 1000)),
                unidad=UNIDAD.get(v, "mg/l"), bajo_ld=(x is None), limite_deteccion=np.nan,
                fraccion="no_informada", laboratorio="Laboratorio universitario (tesis UNCuyo)",
                origen="medido", metodo="laboratorio" if not campo else "medicion_campo",
                fuente=TESIS[0], fuente_url=TESIS[1],
                nota="Valor medio por río (la tesis no informa por sitio). pH y CE: media de 3 mediciones." if campo
                else "Elemento traza reportado en ppb; 'nd' = no detectado (límite no informado)"))
    for v, x in {"arsenico": 0.57, "aluminio": 6.7, "boro": 4.0}.items():
        filas.append(dict(
            campana_id="ONG-2025-11", punto_id="NN", fecha_local="2025-11-15 12:00", fecha_precision="mes",
            variable=v, valor=x, unidad="mg/l", bajo_ld=False, limite_deteccion=np.nan, fraccion="no_informada",
            laboratorio="Laboratorio UNCuyo (por encargo de una ONG)", origen="medido", metodo="laboratorio",
            fuente=ONG[0], fuente_url=ONG[1],
            nota="Cifra publicada en prensa. Punto, fecha exacta, fracción y método no publicados. La UNCuyo aclaró que no avala la interpretación de contaminación."))
    return pd.DataFrame(filas)


def _calendario() -> list[tuple[str, str, str, list]]:
    """(campana_id, fecha_local, laboratorio, puntos)."""
    ev = []
    todos = list(BASE)
    for mes in pd.date_range(C.LAB_INICIO, C.LAB_FIN, freq="MS"):
        dia = mes + pd.Timedelta(days=11)
        if mes.month in (2, 5, 8, 11):
            ev.append((f"OF-{mes:%Y-%m}", f"{dia:%Y-%m-%d} 10:00", "Laboratorio oficial (simulado)", todos))
        else:
            ev.append((f"OF-{mes:%Y-%m}", f"{dia:%Y-%m-%d} 10:00", "Laboratorio oficial (simulado)", ["EMB", "PAC"]))
        if mes.month in (4, 10):
            ev.append((f"PART-{mes:%Y-%m}", f"{mes + pd.Timedelta(days=19):%Y-%m-%d} 09:00",
                       "Monitoreo participativo (simulado)", ["PAL", "EMB", "JAB", "PAC"]))
    ev.append(("OF-2025-11-EVENTO", "2025-11-05 11:00", "Laboratorio oficial (simulado)",
               ["TAG", "PAL", "BLA", "IGL", "EMB", "LAM", "JAB"]))
    return ev


def generar_laboratorio(caudal_d: pd.DataFrame, sensores: pd.DataFrame | None = None) -> pd.DataFrame:
    ini = pd.Timestamp(C.LAB_INICIO, tz=C.TZ_LOCAL).tz_convert("UTC")
    fin = pd.Timestamp(C.LAB_FIN, tz=C.TZ_LOCAL).tz_convert("UTC") + pd.Timedelta(days=2)
    dr = _conductores_diarios(caudal_d, ini, fin)
    rng = rng_para("laboratorio")
    p_pp = C.SENSORES["PP"]
    # mediana diaria de la telemetría para medir "en campo" donde hay sensor
    med_sensor = None
    if sensores is not None:
        s = sensores[sensores["origen"] == "simulado"].copy()
        s["dia"] = pd.to_datetime(s["timestamp_utc"]).dt.tz_convert(C.TZ_LOCAL).dt.strftime("%Y-%m-%d")
        med_sensor = s.groupby(["punto_id", "dia", "variable"])["valor"].median()

    filas = []
    for camp, fecha, lab, puntos in _calendario():
        f = pd.Timestamp(fecha)
        dia = f.normalize()
        qpp = float(dr["q_pp"].asof(dia))
        turb_rio = float(dr["turb_pp"].asof(dia))
        participativo = lab.startswith("Monitoreo participativo")
        for p in puntos:
            b = BASE[p]
            if p in ("EMB", "LAM"):
                ce = float(dr["ce_emb"].asof(dia)); turb = float(dr["turb_emb"].asof(dia))
            elif p == "JAB":
                ce = float(dr["ce_emb"].asof(dia)) * 1.03; turb = float(dr["turb_emb"].asof(dia)) * 1.3
            elif p == "PAC":
                ce = float(dr["ce_pac"].asof(dia)); turb = 1.5 * float(dr["turb_emb"].asof(dia)) + 2
            else:
                ce = b["ce"] * (qpp / p_pp["q_ref"]) ** p_pp["ce_exp"]; turb = turb_rio
            ce *= np.exp(rng.normal(0, 0.04))
            turb *= np.exp(rng.normal(0, 0.3))
            fc = ce / b["ce"]
            # temperatura / OD / pH de campo
            doy = f.dayofyear
            temp = 12 + 6 * np.cos(2 * np.pi * (doy - C.DIA_PICO_TEMPERATURA) / 365.25) + rng.normal(0, 1)
            od = od_saturacion(temp, ALTITUD[p]) * rng.uniform(0.92, 1.0)
            ph = b["ph"] + rng.normal(0, 0.12)
            if med_sensor is not None and p in ("EMB", "PAC"):
                k = f"{dia:%Y-%m-%d}"
                try:
                    temp = med_sensor[(p, k, "temperatura")]
                    od = med_sensor[(p, k, "oxigeno_disuelto")]
                    ph = med_sensor[(p, k, "ph")]
                except KeyError:
                    pass
            v = {"ph": ph, "conductividad": ce, "temperatura": temp, "oxigeno_disuelto": od}
            conserv = {"arsenico": b["arsenico"], "boro": b["boro"],
                       "sulfato": 0.23 * b["ce"], "cloruro": 0.08 * b["ce"],
                       "solidos_disueltos_totales": 0.65 * b["ce"]}
            for k_, x in conserv.items():
                v[k_] = x * fc * np.exp(rng.normal(0, 0.10))
            disuelto = {"aluminio": 0.03, "hierro": b["hierro_d"], "manganeso": b["manganeso_d"],
                        "plomo": 0.0003, "cromo_total": 0.0008, "niquel": 0.001, "cobre": 0.001, "cinc": b["cinc"]}
            for k_, x in disuelto.items():
                v[k_] = (x * np.exp(rng.normal(0, 0.25))) + POR_UNT[k_] * turb * np.exp(rng.normal(0, 0.3))
            v["cadmio"] = 0.0003 * np.exp(rng.normal(0, 0.5))
            # Cianuro y mercurio: SIEMPRE bajo el límite de detección en lo simulado. No inventamos
            # detecciones de contaminantes sensibles; las únicas cifras de Hg son las reales de la tesis.
            v["cianuro_total"] = 0.001
            v["mercurio"] = 0.0002
            v["nitrato"] = 2.0 * np.exp(rng.normal(0, 0.4))
            if participativo:  # kit acotado: campo + As + B, enviados a laboratorio acreditado
                v = {k_: x for k_, x in v.items() if k_ in ("ph", "conductividad", "temperatura",
                                                              "oxigeno_disuelto", "arsenico", "boro")}
            muestra = f"{camp}-{p}"
            for k_, x in v.items():
                campo = k_ in UNIDAD
                ld = LD.get(k_, np.nan)
                bajo = (not campo) and x < ld
                dec = {"ph": 2, "conductividad": 0, "temperatura": 1, "oxigeno_disuelto": 2}.get(k_)
                valor = round(float(x), dec) if campo else (None if bajo else float(f"{x:.3g}"))
                filas.append(dict(
                    campana_id=camp, punto_id=p, fecha_local=fecha, fecha_precision="hora",
                    variable=k_, valor=valor, unidad=UNIDAD.get(k_, "mg/l"), bajo_ld=bajo,
                    limite_deteccion=(np.nan if campo else ld), fraccion=("campo" if campo else "total"),
                    laboratorio=lab, origen="simulado",
                    metodo="medicion_campo" if campo else "laboratorio",
                    fuente=C.FUENTE_SIMULADA, fuente_url="",
                    nota=f"calibración: {b['calib']}", muestra_id=muestra))
    sim = pd.DataFrame(filas)
    real = _real()
    real["muestra_id"] = real["campana_id"] + "-" + real["punto_id"]
    d = pd.concat([real, sim], ignore_index=True)
    d["timestamp_utc"] = (pd.to_datetime(d["fecha_local"]).dt.tz_localize(C.TZ_LOCAL).dt.tz_convert("UTC")
                          .dt.strftime("%Y-%m-%dT%H:%M:%SZ"))
    cols = ["muestra_id", "campana_id", "punto_id", "timestamp_utc", "fecha_precision", "variable", "valor",
            "unidad", "bajo_ld", "limite_deteccion", "fraccion", "laboratorio", "origen", "metodo", "fuente",
            "fuente_url", "nota"]
    return d[cols].sort_values(["timestamp_utc", "punto_id", "variable"]).reset_index(drop=True)
