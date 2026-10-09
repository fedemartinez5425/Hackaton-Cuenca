"""Semáforo por uso del agua + alerta de cambio inusual + índice CCME (estilo ACUMAR).

Colores:
  verde    dentro del nivel guía con margen
  amarillo dentro, pero cerca del límite (umbral_amarillo, o 10 % del límite si no hay uno)
  rojo     fuera del nivel guía
  gris     sin datos, solo datos rellenados, o no evaluable (límite de detección > nivel guía)
Aparte del nivel guía, `cambio_inusual` marca cuando la mediana del día se aparta mucho de los
30 días previos (z robusto). Sirve para variables sin nivel guía (turbidez, temperatura) y para
avisar antes de que algo cruce un límite.
"""
import numpy as np
import pandas as pd

from . import config as C

ORDEN = {"gris": 0, "verde": 1, "amarillo": 2, "rojo": 3}
USOS_SENSOR = {  # uso -> (uso en la tabla de niveles guía, variables evaluadas)
    "vida_acuatica": ("vida_acuatica", ["ph", "oxigeno_disuelto"]),
    "riego": ("riego", ["ph", "conductividad"]),
    "ganado": ("ganado", ["conductividad"]),
    "consumo_humano": ("agua_potable", ["ph", "conductividad"]),
}
NOMBRE_USO = {"vida_acuatica": "peces y vida acuática", "riego": "riego", "ganado": "bebida de animales",
              "consumo_humano": "consumo humano (siempre requiere potabilización)"}
FRASE = {  # el sensor NO mide metales: las frases lo dicen siempre
    "verde": "Sin alertas para {uso} en lo que mide el sensor ({vars}). Metales y arsénico: ver último análisis de laboratorio.",
    "amarillo": "Atención para {uso}: {detalle} cerca del límite o con un cambio inusual. Dato preliminar.",
    "rojo": "Fuera de nivel guía para {uso}: {detalle}. Dato preliminar, en revisión.",
    "gris": "Sin datos suficientes del sensor para {uso} en este momento.",
}
NOMBRE_VAR = {"ph": "pH", "conductividad": "conductividad (sales)", "oxigeno_disuelto": "oxígeno disuelto",
              "turbidez": "turbidez", "temperatura": "temperatura", "caudal": "caudal"}


def cargar_niveles() -> pd.DataFrame:
    n = pd.read_csv(C.REFERENCIA / "niveles_guia.csv")
    return n[n["estado"] != "dudoso"].copy()


def _amarillo(f) -> float:
    if pd.notna(f.umbral_amarillo):
        return float(f.umbral_amarillo)
    return f.limite * (0.9 if f.sentido == "max" else 1.1)


def evaluar(valores: np.ndarray, filas: pd.DataFrame) -> np.ndarray:
    """Color por valor contra todas las filas (p. ej. pH min y max): gana el peor."""
    valores = np.asarray(valores, dtype=float)
    peor = np.where(np.isnan(valores), 0, 1)
    for f in filas.itertuples():
        am = _amarillo(f)
        if f.sentido == "max":
            c = np.where(valores > f.limite, 3, np.where(valores > am, 2, 1))
        else:
            c = np.where(valores < f.limite, 3, np.where(valores < am, 2, 1))
        c = np.where(np.isnan(valores), 0, c)
        peor = np.maximum(peor, c)
    inv = {v: k for k, v in ORDEN.items()}
    return np.vectorize(inv.get)(peor)


def _z_robusto(s: pd.Series, ventana=30) -> pd.Series:
    prev = s.shift(1).rolling(ventana, min_periods=10)
    med = prev.median()
    mad = (s.shift(1) - med).abs().rolling(ventana, min_periods=10).median() * 1.4826
    return (s - med) / mad.clip(lower=1e-9)


def semaforo_diario(sensores: pd.DataFrame, z_umbral=4.0, cobertura_min=0.5) -> pd.DataFrame:
    niv = cargar_niveles()
    s = sensores[sensores["origen"] == "simulado"].copy()  # nunca se evalúa sobre datos rellenados
    s["fecha"] = pd.to_datetime(s["timestamp_utc"]).dt.tz_convert(C.TZ_LOCAL).dt.strftime("%Y-%m-%d")
    g = s.groupby(["punto_id", "variable", "fecha"])["valor"].agg(["median", "size"]).reset_index()
    g["cobertura"] = g["size"] / 96
    g.loc[g["cobertura"] < cobertura_min, "median"] = np.nan
    # completar días sin datos (sensor caído) para que aparezcan en gris
    fechas = pd.date_range(g["fecha"].min(), g["fecha"].max(), freq="D").strftime("%Y-%m-%d")
    idx = pd.MultiIndex.from_product([g["punto_id"].unique(), g["variable"].unique(), fechas],
                                     names=["punto_id", "variable", "fecha"])
    g = g.set_index(["punto_id", "variable", "fecha"]).reindex(idx).reset_index()
    g = g[g.apply(lambda r: r["variable"] in C.SENSORES[r["punto_id"]]["variables"], axis=1)]
    g["cobertura"] = g["cobertura"].fillna(0)
    g["z"] = g.groupby(["punto_id", "variable"])["median"].transform(_z_robusto)
    g["cambio_inusual"] = g["z"].abs() > z_umbral
    filas = []
    for uso, (uso_tabla, variables) in USOS_SENSOR.items():
        for v in variables:
            ref = niv[(niv["parametro"] == v) & (niv["uso"] == uso_tabla)]
            sub = g[g["variable"] == v].copy()
            sub["uso"] = uso
            sub["color"] = evaluar(sub["median"].to_numpy(), ref)
            sub["norma"] = "; ".join(sorted(ref["norma"].unique()))
            filas.append(sub)
    # variables sin nivel guía: solo cambio inusual
    sin = g[g["variable"].isin(["turbidez", "temperatura", "caudal"])].copy()
    sin["uso"] = "contexto"
    sin["color"] = np.where(sin["median"].isna(), "gris", np.where(sin["cambio_inusual"], "amarillo", "verde"))
    sin["norma"] = "sin nivel guía: solo cambio inusual"
    d = pd.concat(filas + [sin], ignore_index=True)
    # un cambio inusual sube un verde a amarillo
    d.loc[(d["color"] == "verde") & d["cambio_inusual"], "color"] = "amarillo"
    d = d.rename(columns={"median": "mediana_dia", "size": "n_lecturas"})
    # resumen por punto-uso-día
    d["rango"] = d["color"].map(ORDEN)
    res = []
    for (p, uso, f), grp in d[d["uso"] != "contexto"].groupby(["punto_id", "uso", "fecha"]):
        peor = grp["rango"].max()
        color = {v: k for k, v in ORDEN.items()}[peor]
        if (grp["color"] == "gris").all():
            color = "gris"
        malos = grp[grp["rango"] == peor]["variable"].map(NOMBRE_VAR).tolist()
        res.append(dict(punto_id=p, uso=uso, fecha=f, variable="_resumen", color=color,
                        frase=FRASE[color].format(uso=NOMBRE_USO[uso], detalle=", ".join(malos),
                                                 vars=", ".join(NOMBRE_VAR[v] for v in USOS_SENSOR[uso][1]))))
    res = pd.DataFrame(res)
    cols = ["fecha", "punto_id", "uso", "variable", "mediana_dia", "n_lecturas", "cobertura", "color",
            "z", "cambio_inusual", "norma"]
    out = pd.concat([d[cols], res], ignore_index=True)
    return out.sort_values(["fecha", "punto_id", "uso", "variable"]).reset_index(drop=True)


AGUAS_ARRIBA = ["TAG", "PAL", "BLA", "JCO", "IGL"]


def semaforo_laboratorio(lab: pd.DataFrame) -> pd.DataFrame:
    niv = cargar_niveles()
    usos = ["bebida_fuente", "agua_potable", "vida_acuatica", "riego", "ganado"]
    ref = lab[lab["punto_id"].isin(AGUAS_ARRIBA) & lab["valor"].notna()]
    p95 = ref.groupby("variable")["valor"].quantile(0.95)
    filas = []
    for uso in usos:
        n_uso = niv[niv["uso"] == uso]
        for v, grp in lab.groupby("variable"):
            r = n_uso[n_uso["parametro"] == v]
            if r.empty:
                continue
            x = grp.copy()
            x["uso"] = uso
            x["color"] = evaluar(x["valor"].to_numpy(), r)
            lim = r["limite"].min() if (r["sentido"] == "max").all() else np.nan
            x["limite"] = lim if (r["sentido"] == "max").all() else "; ".join(f"{a} {b}" for a, b in zip(r["sentido"], r["limite"]))
            x["norma"] = " – ".join(str(t) for t in (r["norma"].iat[0], r["tabla"].iat[0]) if pd.notna(t) and t)
            nd = x["bajo_ld"].astype(bool)
            evaluable = nd & x["limite_deteccion"].notna() & (x["limite_deteccion"] <= lim if pd.notna(lim) else False)
            x.loc[nd, "color"] = "gris"
            x.loc[evaluable, "color"] = "verde"
            x["detalle"] = np.where(~nd, "",
                           np.where(evaluable, "no detectado (límite de detección por debajo del nivel guía)",
                           np.where(x["limite_deteccion"].isna(), "no detectado; límite de detección no informado",
                                    "no evaluable: el límite de detección es mayor que el nivel guía")))
            x["vs_aguas_arriba"] = np.where(
                x["valor"].isna() | (v not in p95.index), "",
                np.where(x["valor"] <= p95.get(v, np.inf), "dentro del rango de los puntos aguas arriba (P95)",
                         "por encima de lo observado aguas arriba (P95)"))
            filas.append(x)
    d = pd.concat(filas, ignore_index=True)
    cols = ["muestra_id", "campana_id", "punto_id", "timestamp_utc", "variable", "valor", "unidad", "bajo_ld",
            "limite_deteccion", "origen", "laboratorio", "uso", "limite", "norma", "color", "detalle", "vs_aguas_arriba"]
    return d[cols]


def ica_ccme(lab: pd.DataFrame) -> pd.DataFrame:
    """Índice CCME (el que usa ACUMAR): F1 alcance, F2 frecuencia, F3 amplitud. Por punto, año y uso."""
    niv = cargar_niveles()
    lab = lab[lab["valor"].notna() & ~lab["bajo_ld"].astype(bool)].copy()
    lab["anio"] = lab["timestamp_utc"].str.slice(0, 4)
    out = []
    for uso in ["bebida_fuente", "vida_acuatica", "riego", "ganado"]:
        n_uso = niv[niv["uso"] == uso]
        x = lab.merge(n_uso[["parametro", "sentido", "limite"]], left_on="variable", right_on="parametro")
        for (p, a), g in x.groupby(["punto_id", "anio"]):
            if g["muestra_id"].nunique() < 3 or g["variable"].nunique() < 4:
                continue
            falla = np.where(g["sentido"] == "max", g["valor"] > g["limite"], g["valor"] < g["limite"])
            exc = np.where(g["sentido"] == "max", g["valor"] / g["limite"] - 1, g["limite"] / g["valor"] - 1)
            exc = np.where(falla, exc, 0.0)
            f1 = 100 * g.loc[falla, "variable"].nunique() / g["variable"].nunique()
            f2 = 100 * falla.sum() / len(g)
            nse = exc.sum() / len(g)
            f3 = nse / (0.01 * nse + 0.01)
            ica = 100 - np.sqrt(f1 ** 2 + f2 ** 2 + f3 ** 2) / 1.732
            cat = ("Excelente" if ica >= 95 else "Buena" if ica >= 80 else "Regular" if ica >= 65
                   else "Marginal" if ica >= 45 else "Mala")
            out.append(dict(punto_id=p, anio=a, uso=uso, n_muestras=g["muestra_id"].nunique(),
                            n_parametros=g["variable"].nunique(), F1=round(f1, 1), F2=round(f2, 1), F3=round(f3, 1),
                            ica=round(ica, 1), categoria=cat,
                            parametros_que_fallan="; ".join(sorted(g.loc[falla, "variable"].unique()))))
    return pd.DataFrame(out)
