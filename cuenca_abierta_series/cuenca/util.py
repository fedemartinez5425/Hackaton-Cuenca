import hashlib

import numpy as np
import pandas as pd
from scipy.signal import lfilter

from . import config as C


def rng_para(nombre: str) -> np.random.Generator:
    """Generador reproducible e independiente para cada serie (semilla global + nombre)."""
    h = int.from_bytes(hashlib.sha256(f"{C.SEMILLA}:{nombre}".encode()).digest()[:8], "big")
    return np.random.default_rng(h)


def ar1(rng, n: int, phi: float, sd: float) -> np.ndarray:
    """Ruido AR(1) estacionario con desvío `sd`. Causal: alargar n no cambia los valores previos."""
    e = rng.normal(0.0, 1.0, n)
    e[1:] *= sd * np.sqrt(1 - phi ** 2)
    if n:
        e[0] *= sd  # arranque en régimen estacionario
    return lfilter([1.0], [1.0, -phi], e)


def pulso_crecida(t: pd.DatetimeIndex, pico: pd.Timestamp, subida_h=1.5, recesion_h=8.0) -> np.ndarray:
    """Forma 0..1 de una crecida: subida rápida (gaussiana) y recesión exponencial."""
    dt = (t - pico) / pd.Timedelta(hours=1)
    dt = np.asarray(dt, dtype=float)
    return np.where(dt < 0, np.exp(-(dt / subida_h) ** 2), np.exp(-dt / recesion_h))


def campana(t: pd.DatetimeIndex, inicio, pico, fin) -> np.ndarray:
    """Forma 0..1 de coseno elevado entre inicio-pico-fin (0 fuera)."""
    x = np.asarray((t - inicio) / pd.Timedelta(hours=1), dtype=float)
    a = (pico - inicio) / pd.Timedelta(hours=1)
    b = (fin - pico) / pd.Timedelta(hours=1)
    y = np.zeros_like(x)
    m1 = (x >= 0) & (x <= a)
    y[m1] = 0.5 - 0.5 * np.cos(np.pi * x[m1] / a)
    x2 = x - a
    m2 = (x2 > 0) & (x2 <= b)
    y[m2] = 0.5 + 0.5 * np.cos(np.pi * x2[m2] / b)
    return y


def od_saturacion(temp_c: np.ndarray, altitud_m: float) -> np.ndarray:
    """OD de saturación (mg/l), agua dulce. Benson & Krause (APHA 4500-O) con corrección por altitud."""
    tk = np.asarray(temp_c, dtype=float) + 273.15
    ln = (-139.34411 + 1.575701e5 / tk - 6.642308e7 / tk ** 2
          + 1.243800e10 / tk ** 3 - 8.621949e11 / tk ** 4)
    p_atm = (1 - 2.25577e-5 * altitud_m) ** 5.25588
    return np.exp(ln) * p_atm


def hora_local(t_utc: pd.DatetimeIndex) -> np.ndarray:
    tl = t_utc.tz_convert(C.TZ_LOCAL)
    return tl.hour.to_numpy() + tl.minute.to_numpy() / 60.0


def dia_del_anio(t_utc: pd.DatetimeIndex) -> np.ndarray:
    tl = t_utc.tz_convert(C.TZ_LOCAL)
    return tl.dayofyear.to_numpy() + hora_local(t_utc) / 24.0
