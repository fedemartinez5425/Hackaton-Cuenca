"""Gráficos de validación (PNG) en salida/graficos."""
import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.colors import ListedColormap

from . import config as C

AZUL, NARANJA, AGUA, AMARILLO, VIOLETA = "#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#4a3aa7"
TINTA, TINTA2, GRILLA = "#0b0b0b", "#52514e", "#e4e3df"
COLOR_ORIGEN = {"medido": AZUL, "rellenado": NARANJA, "simulado": AGUA}
COLOR_PUNTO = {"PP": AZUL, "EMB": NARANJA, "PAC": AGUA}
SEMAFORO = {"gris": "#b7b6b0", "verde": "#1f9d55", "amarillo": "#e8b200", "rojo": "#d63b3b"}
NOMBRE_PUNTO = {"PP": "Piedras Pintadas (río, aguas arriba)", "EMB": "Embalse Cuesta del Viento",
                "PAC": "Pachimoco (río Jáchal, aguas abajo)"}
ETQ = {"caudal": "Caudal (m³/s)", "ph": "pH", "conductividad": "Conductividad (µS/cm)",
       "temperatura": "Temperatura (°C)", "oxigeno_disuelto": "Oxígeno disuelto (mg/l)", "turbidez": "Turbidez (UNT)"}

plt.rcParams.update({
    "figure.facecolor": "#fcfcfb", "axes.facecolor": "#fcfcfb", "axes.edgecolor": GRILLA,
    "axes.labelcolor": TINTA2, "xtick.color": TINTA2, "ytick.color": TINTA2, "axes.grid": True,
    "grid.color": GRILLA, "grid.linewidth": 0.6, "axes.spines.top": False, "axes.spines.right": False,
    "font.size": 9, "axes.titlesize": 10, "axes.titleweight": "bold", "axes.titlecolor": TINTA,
    "legend.frameon": False, "figure.dpi": 110,
})


def _t(df):
    return pd.to_datetime(df["timestamp_utc"]).dt.tz_convert(C.TZ_LOCAL).dt.tz_localize(None)


def caudal(caudal_d, mensual, carpeta):
    fig, axs = plt.subplots(2, 1, figsize=(12, 6.5), sharex=True)
    pp = caudal_d[caudal_d.punto_id == "PP"]
    for o, g in pp.groupby("origen"):
        axs[0].scatter(pd.to_datetime(g.fecha), g.valor, s=1.2, color=COLOR_ORIGEN[o], label=f"diario – {o}", lw=0)
    m = mensual.copy()
    m["fecha"] = pd.to_datetime(m["fecha"]) + pd.Timedelta(days=14)
    real = m[m.origen == "medido"]
    axs[0].plot(real.fecha, real.valor, "o", ms=3, color=TINTA, label="media mensual medida (Hidráulica SJ)")
    axs[0].set_yscale("log")
    axs[0].set_ylabel("m³/s (escala log)")
    axs[0].set_title("Caudal diario en Piedras Pintadas (río Blanco), 2001–2026")
    axs[0].legend(loc="upper right", ncol=4, markerscale=4)
    pac = caudal_d[caudal_d.punto_id == "PAC"]
    axs[1].plot(pd.to_datetime(pac.fecha), pac.valor, lw=0.8, color=AGUA)
    obj = pd.read_csv(C.SALIDA / "caudal_objetivos_anuales_pac.csv")
    for r in obj.itertuples():
        a = int(r.anio_hidrologico[:4])
        x0, x1 = pd.Timestamp(f"{a}-10-01"), pd.Timestamp(f"{a + 1}-09-30")
        axs[1].hlines(r.q_pac, x0, x1, color=TINTA, lw=1.5)
    axs[1].axhline(C.CAUDAL_MEDIO_JACHAL_HIST, color=TINTA2, lw=0.8, ls="--")
    axs[1].text(pd.Timestamp("2001-06-01"), C.CAUDAL_MEDIO_JACHAL_HIST * 1.05, "media histórica Jáchal 10,3 m³/s",
                color=TINTA2, fontsize=8)
    axs[1].set_ylabel("m³/s")
    axs[1].set_title("Caudal diario simulado en Pachimoco (río Jáchal) — barras negras: media anual objetivo (pronósticos / anclas)")
    fig.tight_layout()
    fig.savefig(carpeta / "01_caudal_2001_2026.png")
    plt.close(fig)


def sensores_punto(sens, punto, carpeta, anomalias):
    s = sens[sens.punto_id == punto].copy()
    s["t"] = _t(s)
    vars_ = C.SENSORES[punto]["variables"]
    fig, axs = plt.subplots(len(vars_), 1, figsize=(12, 1.9 * len(vars_)), sharex=True)
    for ax, v in zip(axs, vars_):
        g = s[s.variable == v].set_index("t")["valor"]
        d = g.resample("D").agg(["min", "median", "max"])
        ax.fill_between(d.index, d["min"], d["max"], color=COLOR_PUNTO[punto], alpha=0.18, lw=0)
        ax.plot(d.index, d["median"], color=COLOR_PUNTO[punto], lw=1)
        for a in anomalias:
            if a["punto_id"] == punto and (a["variables"] == "todas" or v in a["variables"]):
                x0 = a["inicio"].tz_convert(C.TZ_LOCAL).tz_localize(None)
                x1 = a["fin"].tz_convert(C.TZ_LOCAL).tz_localize(None)
                ax.axvspan(x0, max(x1, x0 + pd.Timedelta(days=2)), color=VIOLETA, alpha=0.15, lw=0)
                ax.text(x0, ax.get_ylim()[1], a["anomalia_id"], fontsize=7, color=VIOLETA, va="top")
        ax.set_ylabel(ETQ[v], fontsize=8)
        if v == "turbidez" or (v == "caudal" and punto == "PP"):
            ax.set_yscale("log")
    axs[0].set_title(f"{NOMBRE_PUNTO[punto]} — mediana diaria y rango del día (15 min, simulado). Violeta = anomalía insertada")
    fig.tight_layout()
    fig.savefig(carpeta / f"02_sensores_{punto}.png")
    plt.close(fig)


def zoom(sens, punto, vars_, desde, hasta, titulo, nombre, carpeta):
    s = sens[(sens.punto_id == punto) & sens.variable.isin(vars_)].copy()
    s["t"] = _t(s)
    s = s[(s.t >= desde) & (s.t <= hasta)]
    fig, axs = plt.subplots(len(vars_), 1, figsize=(11, 2.2 * len(vars_)), sharex=True)
    for ax, v in zip(axs, vars_):
        g = s[s.variable == v]
        ax.plot(g.t, g.valor, lw=0.9, color=COLOR_PUNTO[punto])
        r = g[g.origen == "rellenado"]
        if len(r):
            ax.plot(r.t, r.valor, ".", ms=3, color=NARANJA, label="rellenado")
            ax.legend(loc="upper right")
        ax.set_ylabel(ETQ[v], fontsize=8)
        if v == "oxigeno_disuelto":
            ax.axhline(5.5, color=SEMAFORO["rojo"], lw=0.8, ls="--")
            ax.text(g.t.min(), 5.6, "nivel guía vida acuática (ref.) 5,5 mg/l", fontsize=7, color=TINTA2)
    axs[0].set_title(titulo)
    axs[-1].xaxis.set_major_formatter(mdates.DateFormatter("%d-%b"))
    fig.tight_layout()
    fig.savefig(carpeta / nombre)
    plt.close(fig)


def acople(sens, carpeta):
    s = sens[(sens.punto_id == "PP") & (sens.origen == "simulado") & (sens.anomalia_id == "")]
    w = s.pivot_table(index="timestamp_utc", columns="variable", values="valor").sample(8000, random_state=1)
    fig, axs = plt.subplots(1, 2, figsize=(10, 4))
    axs[0].scatter(w.caudal, w.conductividad, s=3, color=AZUL, alpha=0.4, lw=0)
    axs[0].set_xscale("log"); axs[0].set_yscale("log")
    axs[0].set_xlabel("Caudal (m³/s)"); axs[0].set_ylabel("Conductividad (µS/cm)")
    axs[0].scatter([34], [869], s=60, color=TINTA, marker="*", zorder=3)
    axs[0].annotate("tesis UNCuyo nov-2016\n(Jáchal pos-confluencia)", (34, 869), fontsize=7, color=TINTA2,
                    xytext=(-90, -25), textcoords="offset points")
    axs[0].set_title("Más caudal → menos sales (dilución)")
    axs[1].scatter(w.caudal, w.turbidez, s=3, color=AZUL, alpha=0.4, lw=0)
    axs[1].set_xscale("log"); axs[1].set_yscale("log")
    axs[1].set_xlabel("Caudal (m³/s)"); axs[1].set_ylabel("Turbidez (UNT)")
    axs[1].set_title("Más caudal → más turbidez (arrastre)")
    fig.suptitle("Acople con el caudal en Piedras Pintadas (simulado, sin anomalías)", fontweight="bold")
    fig.tight_layout()
    fig.savefig(carpeta / "05_acople_caudal.png")
    plt.close(fig)


def laboratorio(lab, carpeta):
    niv = pd.read_csv(C.REFERENCIA / "niveles_guia.csv")
    orden = ["TAG", "PAL", "BLA", "JCO", "IGL", "EMB", "LAM", "JAB", "PAC", "NN"]
    fig, axs = plt.subplots(1, 3, figsize=(13, 4.2))
    for ax, v in zip(axs, ["arsenico", "boro", "aluminio"]):
        g = lab[(lab.variable == v) & lab.valor.notna()]
        for i, p in enumerate(orden):
            x = g[g.punto_id == p]
            for o, xx in x.groupby("origen"):
                jit = np.random.default_rng(i).uniform(-0.18, 0.18, len(xx))
                ax.scatter(np.full(len(xx), i) + jit, xx.valor, s=14 if o == "medido" else 8,
                           color=COLOR_ORIGEN[o], marker="D" if o == "medido" else "o",
                           alpha=1 if o == "medido" else 0.6, lw=0, label=o if i == 0 or p in ("NN", "BLA") else None)
        for uso, ls in [("bebida_fuente", "--"), ("riego", ":"), ("vida_acuatica", "-.")]:
            r = niv[(niv.parametro == v) & (niv.uso == uso)]
            if len(r):
                ax.axhline(r.limite.iat[0], color=TINTA2, lw=0.8, ls=ls)
                ax.text(len(orden) - 0.5, r.limite.iat[0], f" {uso.replace('_', ' ')}", fontsize=7, color=TINTA2, va="center")
        ax.set_yscale("log")
        ax.set_xticks(range(len(orden)), orden, fontsize=8)
        ax.set_title({"arsenico": "Arsénico", "boro": "Boro", "aluminio": "Aluminio"}[v] + " total (mg/l)")
        h, l = ax.get_legend_handles_labels()
        ax.legend(dict(zip(l, h)).values(), dict(zip(l, h)).keys(), fontsize=7, loc="lower left")
    fig.suptitle("Laboratorio: de aguas arriba (izq.) a aguas abajo (der.). NN = cifras de prensa nov-2025 (punto no publicado). "
                 "Líneas: niveles guía Dec. 831/93", fontsize=9)
    fig.tight_layout()
    fig.savefig(carpeta / "06_laboratorio_as_b_al.png")
    plt.close(fig)


def semaforo(sd, carpeta):
    r = sd[sd.variable == "_resumen"].copy()
    r["fila"] = r.punto_id + " · " + r.uso
    tab = r.pivot(index="fila", columns="fecha", values="color").fillna("gris")
    cod = {"gris": 0, "verde": 1, "amarillo": 2, "rojo": 3}
    cmap = ListedColormap([SEMAFORO[k] for k in cod])
    fig, ax = plt.subplots(figsize=(13, 4.2))
    fechas = pd.to_datetime(tab.columns)
    ax.imshow(tab.replace(cod).to_numpy(dtype=int), aspect="auto", cmap=cmap, vmin=0, vmax=3, interpolation="nearest",
              extent=[mdates.date2num(fechas[0]), mdates.date2num(fechas[-1]), len(tab) - 0.5, -0.5])
    ax.xaxis_date()
    ax.set_yticks(range(len(tab)), tab.index, fontsize=8)
    ax.grid(False)
    ax.set_title("Semáforo diario por punto y uso (verde / amarillo / rojo / gris = sin datos)")
    for k, c in SEMAFORO.items():
        ax.plot([], [], "s", color=c, label=k)
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.08), ncol=4)
    fig.tight_layout()
    fig.savefig(carpeta / "07_semaforo_diario.png")
    plt.close(fig)


def todos(caudal_d, mensual, sens, lab, sd):
    carpeta = C.SALIDA / "graficos"
    carpeta.mkdir(exist_ok=True)
    caudal(caudal_d, mensual, carpeta)
    for p in ["PP", "EMB", "PAC"]:
        sensores_punto(sens, p, carpeta, C.ANOMALIAS)
    zoom(sens, "EMB", ["oxigeno_disuelto", "temperatura", "ph", "turbidez"], pd.Timestamp("2025-10-26"),
         pd.Timestamp("2025-11-12"), "A01 — Hipoxia en el embalse (escenario tipo 4-nov-2025, simulado)",
         "03_zoom_hipoxia_nov2025.png", carpeta)
    zoom(sens, "PP", ["caudal", "turbidez", "conductividad"], pd.Timestamp("2025-02-09"),
         pd.Timestamp("2025-02-16"), "A02 — Crecida estival en Piedras Pintadas (simulado)",
         "04_zoom_crecida_feb2025.png", carpeta)
    acople(sens, carpeta)
    laboratorio(lab, carpeta)
    semaforo(sd, carpeta)
