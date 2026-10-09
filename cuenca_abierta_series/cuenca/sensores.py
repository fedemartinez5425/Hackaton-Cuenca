"""Telemetría simulada cada 15 min: caudal, pH, conductividad, temperatura, OD y turbidez.

Modelo por variable = nivel base + ciclo anual + ciclo diario + ruido AR(1) + acople con caudal.
  - Más caudal => menos conductividad (dilución, ley potencia) y más turbidez (arrastre de sedimento).
  - OD = saturación(temperatura, altitud) x fracción con ciclo diario (fotosíntesis).
  - El embalse suaviza y retrasa la química de aguas arriba (media móvil exponencial).
Después se insertan anomalías etiquetadas, huecos de comunicación (rellenados y marcados)
y caídas largas de sensor (sin filas).
"""
import numpy as np
import pandas as pd

from . import config as C
from .caudal import factor_crecidas_diario
from .util import ar1, campana, dia_del_anio, hora_local, od_saturacion, pulso_crecida, rng_para

DOS_PI = 2 * np.pi


def _diario_a_15min(serie_diaria: pd.Series, t: pd.DatetimeIndex) -> np.ndarray:
    """Interpola linealmente valores diarios (centrados a las 12 h local) a la grilla de 15 min."""
    centros = (serie_diaria.index + pd.Timedelta(hours=12)).tz_localize(C.TZ_LOCAL).tz_convert("UTC")
    x = centros.asi8.astype(float)
    return np.interp(t.asi8.astype(float), x, serie_diaria.to_numpy())


def _ewm_dias(s: pd.Series, tau: float) -> pd.Series:
    return s.ewm(alpha=1 - np.exp(-1 / tau), adjust=False).mean()


def _conductores_diarios(caudal_d: pd.DataFrame, inicio, fin) -> pd.DataFrame:
    """Series diarias auxiliares (con 18 meses de arranque para las medias móviles)."""
    pp = caudal_d[caudal_d.punto_id == "PP"].set_index("fecha")["valor"]
    pac = caudal_d[caudal_d.punto_id == "PAC"].set_index("fecha")["valor"]
    pp.index = pd.DatetimeIndex(pp.index)
    pac.index = pd.DatetimeIndex(pac.index)
    desde = (inicio.tz_convert(C.TZ_LOCAL).tz_localize(None) - pd.Timedelta(days=540)).normalize()
    hasta = (fin.tz_convert(C.TZ_LOCAL).tz_localize(None) + pd.Timedelta(days=2)).normalize()
    pp, pac = pp[desde:hasta], pac[desde:hasta]
    base_pp = pp / factor_crecidas_diario(pp.index, "PP").to_numpy()  # quitar crecidas: se agregan a 15 min
    p, e, a = C.SENSORES["PP"], C.SENSORES["EMB"], C.SENSORES["PAC"]
    d = pd.DataFrame(index=pp.index)
    d["q_pp"] = base_pp
    d["q_pac"] = pac
    d["ce_pp"] = p["ce_ref"] * (base_pp / p["q_ref"]) ** p["ce_exp"]
    d["turb_pp"] = p["turb_a"] * (base_pp / p["turb_q0"]) ** p["turb_exp"]
    d["ce_emb"] = _ewm_dias(d["ce_pp"], e["ce_tau_dias"]) * e["ce_factor_evap"]
    d["turb_emb"] = e["turb_base"] + e["turb_frac"] * _ewm_dias(d["turb_pp"], e["turb_tau_dias"])
    d["ce_pac"] = _ewm_dias(d["ce_emb"], a["ce_tau_dias"]) * a["ce_factor"]
    return d


def _temperatura(t, prm, rng):
    doy = dia_del_anio(t)
    h = hora_local(t)
    verano = 0.5 + 0.5 * np.cos(DOS_PI * (doy - C.DIA_PICO_TEMPERATURA) / 365.25)
    temp = (prm["t_media"] + prm["t_amp_anual"] * np.cos(DOS_PI * (doy - C.DIA_PICO_TEMPERATURA) / 365.25)
            + prm["t_amp_diaria"] * (0.6 + 0.4 * verano) * np.cos(DOS_PI * (h - 16) / 24)
            + ar1(rng, len(t), 0.995, 0.5))
    return np.maximum(temp, 0.1), verano, h


def _oxigeno(temp, h, verano, prm, rng, amp_extra=1.0):
    frac = prm["od_frac_sat"] + prm["od_amp_diaria"] * amp_extra * np.cos(DOS_PI * (h - 15) / 24)
    return od_saturacion(temp, prm["altitud"]) * frac + ar1(rng, len(temp), 0.98, 0.15)


def _utc(x) -> pd.Timestamp:
    x = pd.Timestamp(x)
    return x.tz_localize("UTC") if x.tzinfo is None else x.tz_convert("UTC")


def generar_wide(caudal_d: pd.DataFrame, inicio=None, fin=None) -> dict:
    """Devuelve {punto: DataFrame ancho (t x variables)} y etiquetas de anomalía por celda."""
    inicio, fin = (_utc(x) for x in (inicio or C.SENSORES_INICIO, fin or C.SENSORES_FIN))
    t = pd.date_range(inicio, fin, freq=C.PASO_SENSOR, inclusive="left")
    n = len(t)
    dr = _conductores_diarios(caudal_d, inicio, fin)
    I = {c: _diario_a_15min(dr[c], t) for c in dr.columns}
    out, etiquetas = {}, {}

    # ---------------- PP: río aguas arriba ----------------
    p = C.SENSORES["PP"]
    r = lambda v: rng_para(f"PP:{v}")
    doy, h = dia_del_anio(t), hora_local(t)
    melt = np.where(pd.DatetimeIndex(t.tz_convert(C.TZ_LOCAL)).month.isin([11, 12, 1, 2]), 0.06, 0.015)
    m_crec = np.ones(n)
    m_turb_lead = np.ones(n)
    et_pp = np.full(n, "", dtype=object)
    for a in C.ANOMALIAS:
        if a["tipo"] == "crecida_turbidez" and a["punto_id"] == "PP":
            pulso = pulso_crecida(t, a["pico"])
            m_crec *= 1 + a["intensidad"] * pulso
            m_turb_lead *= 1 + 6 * pulso_crecida(t, a["pico"] - pd.Timedelta(hours=1), subida_h=1.0, recesion_h=5)
            et_pp[pulso > 0.02] = a["anomalia_id"]
    q = I["q_pp"] * (1 + melt * np.cos(DOS_PI * (h - 20) / 24)) * m_crec * np.exp(ar1(r("caudal"), n, 0.99, 0.01))
    temp, verano, _ = _temperatura(t, p, r("temperatura"))
    pp = pd.DataFrame(index=t)
    pp["caudal"] = q
    pp["conductividad"] = p["ce_ref"] * (q / p["q_ref"]) ** p["ce_exp"] * np.exp(ar1(r("conductividad"), n, 0.98, 0.02))
    pp["turbidez"] = (p["turb_a"] * (q / p["turb_q0"]) ** p["turb_exp"] * m_turb_lead
                      * np.exp(ar1(r("turbidez"), n, 0.97, 0.25)))
    pp["temperatura"] = temp
    pp["oxigeno_disuelto"] = _oxigeno(temp, h, verano, p, r("oxigeno_disuelto"))
    pp["ph"] = (p["ph_media"] - 0.08 * np.log(q / 10) + 0.05 * np.cos(DOS_PI * (h - 16) / 24)
                + ar1(r("ph"), n, 0.995, 0.05))
    et = pd.DataFrame("", index=t, columns=pp.columns)
    for v in ["caudal", "turbidez", "conductividad"]:
        et[v] = et_pp
    out["PP"], etiquetas["PP"] = pp, et

    # ---------------- EMB: embalse Cuesta del Viento ----------------
    e = C.SENSORES["EMB"]
    r = lambda v: rng_para(f"EMB:{v}")
    temp, verano, _ = _temperatura(t, e, r("temperatura"))
    emb = pd.DataFrame(index=t)
    emb["conductividad"] = I["ce_emb"] * np.exp(ar1(r("conductividad"), n, 0.99, 0.01))
    turb = I["turb_emb"].copy()
    et = pd.DataFrame("", index=t, columns=["ph", "conductividad", "temperatura", "oxigeno_disuelto", "turbidez"])
    for a in C.ANOMALIAS:  # la crecida llega atenuada y con un día de retraso
        if a["tipo"] == "crecida_turbidez":
            pulso = pulso_crecida(t, a["pico"] + pd.Timedelta(days=1), subida_h=6, recesion_h=36)
            turb = turb + 5 * a["intensidad"] / 3.5 * pulso
            et.loc[pulso > 0.02, "turbidez"] = a["anomalia_id"]
    emb["turbidez"] = turb * np.exp(ar1(r("turbidez"), n, 0.97, 0.15))
    emb["temperatura"] = temp
    emb["oxigeno_disuelto"] = _oxigeno(temp, h, verano, e, r("oxigeno_disuelto"), amp_extra=0.5 + verano)
    emb["ph"] = (e["ph_media"] + e["ph_amp_verano"] * (verano - 0.5) * 2
                 + 0.1 * (0.5 + 0.5 * verano) * np.cos(DOS_PI * (h - 16) / 24) + ar1(r("ph"), n, 0.995, 0.05))
    # A01: hipoxia
    for a in C.ANOMALIAS:
        if a["tipo"] == "hipoxia_embalse":
            g = campana(t, a["inicio"], a["pico"], a["fin"])
            emb["temperatura"] += 1.5 * g
            emb["oxigeno_disuelto"] = (od_saturacion(emb["temperatura"], e["altitud"])
                                       * (emb["oxigeno_disuelto"] / od_saturacion(temp, e["altitud"]))
                                       * (1 - a["intensidad"] * g))
            emb["ph"] -= 0.4 * g
            emb["turbidez"] += 4 * g
            for v in a["variables"].split(";"):
                et.loc[g > 0.02, v] = a["anomalia_id"]
    out["EMB"], etiquetas["EMB"] = emb, et[emb.columns]

    # ---------------- PAC: río Jáchal en Pachimoco ----------------
    a_ = C.SENSORES["PAC"]
    r = lambda v: rng_para(f"PAC:{v}")
    temp, verano, _ = _temperatura(t, a_, r("temperatura"))
    pac = pd.DataFrame(index=t)
    q = I["q_pac"] * np.exp(ar1(r("caudal"), n, 0.999, 0.03))
    pac["caudal"] = q
    pac["conductividad"] = I["ce_pac"] * np.exp(ar1(r("conductividad"), n, 0.98, 0.015))
    pac["turbidez"] = ((a_["turb_factor_emb"] * I["turb_emb"] + a_["turb_q_a"] * (q / a_["turb_q0"]) ** a_["turb_exp"])
                       * np.exp(ar1(r("turbidez"), n, 0.97, 0.2)))
    pac["temperatura"] = temp
    pac["oxigeno_disuelto"] = _oxigeno(temp, h, verano, a_, r("oxigeno_disuelto"))
    pac["ph"] = a_["ph_media"] + 0.05 * np.cos(DOS_PI * (h - 16) / 24) + ar1(r("ph"), n, 0.995, 0.05)
    et = pd.DataFrame("", index=t, columns=pac.columns)
    for a in C.ANOMALIAS:
        if a["tipo"] == "deriva_sensor" and a["punto_id"] == "PAC":
            x = np.asarray((t - a["inicio"]) / (a["fin"] - a["inicio"]), dtype=float)
            dentro = (x >= 0) & (x < 1)
            pac.loc[dentro, "conductividad"] *= 1 + a["intensidad"] * x[dentro]
            et.loc[dentro, "conductividad"] = a["anomalia_id"]
    out["PAC"], etiquetas["PAC"] = pac, et
    return out, etiquetas


def _rellenar(col: np.ndarray, faltan: np.ndarray, por_dia: int = 96):
    """Rellena runs de NaN marcados en `faltan`. Devuelve (valores, metodo por celda)."""
    y = col.copy()
    metodo = np.full(len(y), "", dtype=object)
    idx = np.flatnonzero(faltan)
    if not len(idx):
        return y, metodo
    cortes = np.flatnonzero(np.diff(idx) > 1)
    for run in np.split(idx, cortes + 1):
        a, b = run[0] - 1, run[-1] + 1
        if a < 0 or b >= len(y) or np.isnan(y[a]) or np.isnan(y[b]):
            continue
        L = len(run)
        w = (run - a) / (b - a)
        lin = y[a] + w * (y[b] - y[a])
        if L <= C.RELLENO_LINEAL_MAX:
            y[run], metodo[run] = lin, "interpolacion_lineal"
        elif L <= C.RELLENO_DIURNO_MAX and a - por_dia >= 0:
            prev = y[run - por_dia]
            lin_prev = y[a - por_dia] + w * (y[b - por_dia] - y[a - por_dia])
            if np.all(np.isfinite(prev)) and np.isfinite(lin_prev).all():
                y[run], metodo[run] = lin + (prev - lin_prev), "interpolacion_perfil_diario"
            else:
                y[run], metodo[run] = lin, "interpolacion_lineal"
    return y, metodo


def generar_sensores(caudal_d: pd.DataFrame, inicio=None, fin=None) -> pd.DataFrame:
    """Lecturas largas listas para ingesta/sellado."""
    wide, etiq = generar_wide(caudal_d, inicio, fin)
    partes = []
    for punto, df in wide.items():
        t = df.index
        n = len(t)
        et = etiq[punto]
        # 1) caídas largas de sensor: sin datos
        caido = np.zeros(n, bool)
        for a in C.ANOMALIAS:
            if a["tipo"] == "sensor_caido" and a["punto_id"] == punto:
                caido |= (t >= a["inicio"]) & (t < a["fin"])
        # 2) huecos cortos de comunicación (todas las variables del punto a la vez)
        # rngs separados: alargar la ventana no cambia los valores ya publicados
        inicios = rng_para(f"{punto}:huecos_inicio").random(n) < C.PROB_INICIO_HUECO
        largos = rng_para(f"{punto}:huecos_largo").integers(1, C.HUECO_MAX_INTERVALOS + 1, n)
        hueco = np.zeros(n, bool)
        for i in np.flatnonzero(inicios):
            hueco[i:i + largos[i]] = True
        hueco &= ~caido
        origen = pd.DataFrame("simulado", index=t, columns=df.columns)
        metodo = pd.DataFrame("sensor", index=t, columns=df.columns)
        for v in df.columns:
            col = df[v].to_numpy(dtype=float).copy()
            col[hueco | caido] = np.nan
            col, met = _rellenar(col, hueco)
            relleno = met != ""
            origen.loc[relleno, v] = "rellenado"
            metodo.loc[relleno, v] = met[relleno]
            # 3) lecturas espurias aisladas (solo en celdas simuladas, no en caudal)
            if v != "caudal":
                rs = rng_para(f"{punto}:{v}:espurias_signo")
                esp = (rng_para(f"{punto}:{v}:espurias").random(n) < C.PROB_ESPURIA) & ~relleno & np.isfinite(col)
                k = esp.sum()
                if k:
                    if v == "ph":
                        col[esp] += rs.choice([-1.2, 1.2], k)
                    elif v == "temperatura":
                        col[esp] += 8
                    elif v == "oxigeno_disuelto":
                        col[esp] *= 0.4
                    else:
                        col[esp] *= rs.choice([1.5, 8.0], k) if v == "turbidez" else 1.5
                    et.loc[esp, v] = np.where(et.loc[esp, v] == "", "QC_ESPURIA", et.loc[esp, v])
            df[v] = np.round(np.maximum(col, 0) if v != "temperatura" else col, C.DECIMALES[v])
        largo = df.stack(future_stack=True).rename("valor").reset_index()
        largo.columns = ["t", "variable", "valor"]
        largo["origen"] = origen.stack(future_stack=True).to_numpy()
        largo["metodo"] = metodo.stack(future_stack=True).to_numpy()
        largo["anomalia_id"] = et[df.columns].stack(future_stack=True).to_numpy()
        largo["punto_id"] = punto
        partes.append(largo.dropna(subset=["valor"]))
    d = pd.concat(partes, ignore_index=True)
    d["timestamp_utc"] = d["t"].dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    d["unidad"] = d["variable"].map(C.UNIDADES)
    d["fuente"] = C.FUENTE_SIMULADA
    d = d.sort_values(["t", "punto_id", "variable"]).reset_index(drop=True)
    return d[["punto_id", "timestamp_utc", "variable", "valor", "unidad", "origen", "metodo", "fuente", "anomalia_id"]]
