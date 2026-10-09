"""Caudal diario 2001-2026.

PP (río Blanco en Piedras Pintadas):
  1. Mensual real de Hidráulica (medido).
  2. Huecos internos: interpolación estacional de la anomalía logarítmica (rellenado).
  3. Desde feb-2016: simulación AR(1) anual + mensual sobre la climatología real (simulado),
     anclada al pronóstico 2025/26.
  4. Desagregación a diario conservando el volumen mensual + ruido AR(1).
PAC (río Jáchal en Pachimoco): PP suavizado por el embalse * k (todo simulado).
"""
import numpy as np
import pandas as pd
from scipy.interpolate import PchipInterpolator
from scipy.signal import lfilter

from . import config as C
from .util import rng_para, pulso_crecida


def leer_mensual_real() -> pd.DataFrame:
    d = pd.read_csv(C.REFERENCIA / "caudal_piedras_pintadas_mensual.csv", parse_dates=["fecha"])
    return d[["fecha", "valor", "estado"]].set_index("fecha")


def anio_oct_sep(fechas) -> pd.Index:
    f = pd.DatetimeIndex(fechas)
    y = np.where(f.month >= 10, f.year, f.year - 1)
    return pd.Index([f"{a}/{str(a + 1)[2:]}" for a in y])


def caudal_mensual_pp() -> pd.DataFrame:
    real = leer_mensual_real()
    meses = pd.date_range(C.CAUDAL_INICIO, C.CAUDAL_FIN, freq="MS")
    df = pd.DataFrame(index=meses)
    df["valor"] = real["valor"].reindex(meses)
    df["estado_fuente"] = real["estado"].reindex(meses).fillna("fuera_de_tabla")
    med = df["estado_fuente"].eq("medido")

    logq = np.log(df.loc[med, "valor"])
    clim_log = logq.groupby(logq.index.month).mean()          # climatología geométrica
    df["clim"] = np.exp(df.index.month.map(clim_log))
    anom = np.log(df["valor"] / df["clim"])                   # anomalía log (NaN en huecos)

    df["origen"] = np.where(med, "medido", None)
    df["metodo"] = np.where(med, "aforo", None)

    # --- huecos internos (dentro del período real) -> interpolación estacional
    ultimo_real = df.index[med].max()   # último mes medido (oct-2015)
    interno = (~med) & (df.index <= ultimo_real)
    anom_int = anom.copy()
    anom_int[df.index <= ultimo_real] = anom[df.index <= ultimo_real].interpolate(limit_area="inside")
    df.loc[interno, "valor"] = (df["clim"] * np.exp(anom_int))[interno]
    df.loc[interno, "origen"] = "rellenado"
    df.loc[interno, "metodo"] = "interpolacion_estacional"

    # --- simulación posterior al último mes real
    rng = rng_para("caudal_mensual_pp")
    fut = df.index > ultimo_real
    anom_hist = np.log(df.loc[df.index <= ultimo_real, "valor"] / df.loc[df.index <= ultimo_real, "clim"])
    anual_hist = anom_hist.groupby(anio_oct_sep(anom_hist.index)).mean()
    anual_hist = anual_hist[anom_hist.groupby(anio_oct_sep(anom_hist.index)).size() >= 10]
    sd_anual = float(anual_hist.std())
    anios = pd.Index(anio_oct_sep(df.index[fut])).unique()
    # Estado inicial: anomalía media de los últimos 4 meses medidos
    ult = anom_hist[med[df.index <= ultimo_real].to_numpy()].iloc[-4:].mean()
    log_f = {}
    prev = ult
    sd_innov = sd_anual * np.sqrt(1 - C.AR_ANUAL_PHI ** 2)
    for a in anios:
        if a == "2015/16":
            log_f[a] = ult
        else:
            log_f[a] = C.AR_ANUAL_PHI * prev + rng.normal(0, sd_innov)
        prev = log_f[a]
    e = lfilter([1.0], [1.0, -C.AR_MENSUAL_PHI],
                rng.normal(0, C.AR_MENSUAL_SD * np.sqrt(1 - C.AR_MENSUAL_PHI ** 2), fut.sum()))
    a_fut = np.array([log_f[a] for a in anio_oct_sep(df.index[fut])]) + e
    df.loc[fut, "valor"] = df.loc[fut, "clim"].to_numpy() * np.exp(a_fut)
    df.loc[fut, "origen"] = "simulado"
    df.loc[fut, "metodo"] = "generador_ar1_estacional"
    df.attrs["sd_anual_log"] = sd_anual
    return df


def _desagregar(mensual: pd.Series, rng, ventana_deshielo=(11, 12, 1, 2)) -> pd.Series:
    """Mensual -> diario conservando volumen (PCHIP sobre el volumen acumulado) + ruido AR(1)."""
    meses = mensual.index
    bordes = list(meses) + [meses[-1] + pd.offsets.MonthBegin(1)]
    dias_mes = np.array([(bordes[i + 1] - bordes[i]).days for i in range(len(meses))])
    t_bordes = np.array([(b - bordes[0]).days for b in bordes], dtype=float)
    vol = np.concatenate([[0.0], np.cumsum(mensual.to_numpy() * dias_mes)])
    f = PchipInterpolator(t_bordes, vol)
    dias = pd.date_range(bordes[0], bordes[-1] - pd.Timedelta(days=1), freq="D")
    t = np.arange(len(dias) + 1, dtype=float)
    base = np.diff(f(t))
    sd = np.where(dias.month.isin(ventana_deshielo), C.RUIDO_DIARIO_SD["deshielo"], C.RUIDO_DIARIO_SD["resto"])
    z = lfilter([1.0], [1.0, -C.RUIDO_DIARIO_PHI], rng.normal(0, 1, len(dias))) * np.sqrt(1 - C.RUIDO_DIARIO_PHI ** 2)
    q = pd.Series(base * np.exp(sd * z), index=dias)
    # Reescalar cada mes para conservar exactamente la media mensual
    ratio = mensual / q.groupby(q.index.to_period("M").to_timestamp()).mean()
    q = q * ratio.reindex(q.index.to_period("M").to_timestamp()).to_numpy()
    return q


def factor_crecidas_diario(dias: pd.DatetimeIndex, punto: str) -> pd.Series:
    """Media diaria del multiplicador de crecida (1 = sin crecida)."""
    t = pd.date_range(dias[0], dias[-1] + pd.Timedelta(days=1), freq=C.PASO_SENSOR, tz="UTC", inclusive="left")
    m = np.ones(len(t))
    for a in C.ANOMALIAS:
        if a["tipo"] == "crecida_turbidez" and a["punto_id"] == punto:
            m *= 1 + a["intensidad"] * pulso_crecida(t, a["pico"])
    s = pd.Series(m, index=t.tz_convert(None)).resample("D").mean()
    return s.reindex(dias).fillna(1.0)


def objetivos_anuales_pac(men: pd.DataFrame) -> dict:
    """Caudal medio objetivo de PAC (m3/s) por año oct-sep simulado, con su procedencia."""
    an = pd.read_csv(C.REFERENCIA / "anclas_caudal_anual.csv")
    r = {}
    for _, f in an.iterrows():
        ratio = f["derrame_hm3"] / f["media_historica_hm3"]
        if f["rio"] != "Jáchal":
            ratio = ratio ** C.EXPONENTE_SJ_JACHAL
        r[f["anio_hidrologico"]] = (ratio, f"{f['tipo']} río {f['rio']}: {f['derrame_hm3']} hm3")
    med = men[men["origen"] != "simulado"]
    media_pp = men.loc[men["origen"] == "medido", "valor"].mean()
    q1415 = med[anio_oct_sep(med.index) == "2014/15"]["valor"].mean()
    r["2014/15"] = (q1415 / media_pp, "dato real PP")
    anios_sim = list(pd.Index(anio_oct_sep(men.index[men["origen"] == "simulado"])).unique())
    rng = rng_para("anclas_anuales")
    todos = sorted(set(anios_sim) | set(r))
    conocidos = [a for a in todos if a in r]
    salida = {}
    for a in anios_sim:
        if a in r:
            ratio, proc = r[a]
        else:
            antes = [c for c in conocidos if c < a]
            despues = [c for c in conocidos if c > a]
            if antes and despues:
                a0, a1 = antes[-1], despues[0]
                i, i0, i1 = todos.index(a), todos.index(a0), todos.index(a1)
                w = (i - i0) / (i1 - i0)
                lr = (1 - w) * np.log(r[a0][0]) + w * np.log(r[a1][0]) + rng.normal(0, C.SD_ANIO_SIN_ANCLA)
                proc = f"interpolado entre {a0} y {a1} + ruido"
            else:
                a0 = antes[-1]
                lr = np.log(r[a0][0])
                proc = f"persistencia de {a0} (cargar el pronóstico oficial cuando se publique)"
            ratio = float(np.exp(lr))
        salida[a] = {"ratio": ratio, "q_pac": ratio * C.CAUDAL_MEDIO_JACHAL_HIST, "procedencia": proc}
    return salida


def caudal_diario() -> tuple[pd.DataFrame, pd.DataFrame]:
    """Devuelve (diario_largo, mensual_pp)."""
    men = caudal_mensual_pp()

    def construir(men_valores):
        q = _desagregar(men_valores, rng_para("caudal_diario_pp"))
        return q * factor_crecidas_diario(q.index, "PP").to_numpy()

    k = C.CAUDAL_MEDIO_JACHAL_HIST / men.loc[men["origen"] == "medido", "valor"].mean()
    alpha = 1 - np.exp(-1 / C.TAU_EMBALSE_DIAS)
    objetivos = objetivos_anuales_pac(men)
    men.attrs["objetivos_pac"] = objetivos

    # Escalar cada año simulado de PP hasta que PAC promedie el objetivo del año
    men_aj = men["valor"].copy()
    sim = (men["origen"] == "simulado").to_numpy()
    for _ in range(6):
        q_pp = _desagregar(men_aj, rng_para("caudal_diario_pp"))
        q_pac = k * q_pp.ewm(alpha=alpha, adjust=False).mean()
        anio_d = anio_oct_sep(q_pac.index)
        anio_m = anio_oct_sep(men_aj.index)
        for anio, obj in objetivos.items():
            sel = anio_d == anio
            if sel.sum() < 300:   # año incompleto al final: climatología mensual x ratio del año
                medidos = men[men["origen"] == "medido"]["valor"]
                clim_arit = medidos.groupby(medidos.index.month).mean()
                m = (anio_m == anio) & sim
                men_aj[m] = clim_arit.reindex(men_aj.index[m].month).to_numpy() * obj["ratio"]
                continue
            men_aj[(anio_m == anio) & sim] *= obj["q_pac"] / q_pac[sel].mean()
    men["valor_ajustado"] = men_aj
    q_pp = construir(men_aj)
    # el embalse lamina las crecidas: PAC usa la base sin crecidas
    q_pp_sin = _desagregar(men_aj, rng_para("caudal_diario_pp"))
    q_pac = k * q_pp_sin.ewm(alpha=alpha, adjust=False).mean()

    base_mes = men["origen"].reindex(q_pp.index.to_period("M").to_timestamp()).to_numpy()
    pp = pd.DataFrame({
        "punto_id": "PP", "fecha": q_pp.index, "valor": q_pp.round(3).to_numpy(),
        "base_mensual": base_mes,
    })
    pp["origen"] = np.where(pp["base_mensual"] == "simulado", "simulado", "rellenado")
    pp["metodo"] = np.select(
        [pp["base_mensual"] == "medido", pp["base_mensual"] == "rellenado"],
        ["desagregacion_conservativa", "interpolacion_estacional+desagregacion"],
        "generador_ar1_estacional+desagregacion")
    pp["fuente"] = np.where(pp["base_mensual"] == "simulado", C.FUENTE_SIMULADA,
                            "Departamento de Hidráulica de San Juan (media mensual) + desagregación Cuenca Abierta")
    pac = pd.DataFrame({
        "punto_id": "PAC", "fecha": q_pac.index, "valor": q_pac.round(3).to_numpy(),
        "base_mensual": "simulado", "origen": "simulado",
        "metodo": f"modelo_embalse(ewm {C.TAU_EMBALSE_DIAS} d de PP x k={k:.3f})",
        "fuente": C.FUENTE_SIMULADA,
    })
    d = pd.concat([pp, pac], ignore_index=True)
    d["variable"] = "caudal_medio_diario"
    d["unidad"] = "m3/s"
    d["timestamp_utc"] = (pd.to_datetime(d["fecha"]) + pd.Timedelta(hours=3)).dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    d.attrs["k_pac"] = k
    men.attrs["k_pac"] = k
    return d, men
