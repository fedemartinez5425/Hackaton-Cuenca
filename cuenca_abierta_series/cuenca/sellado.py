"""Sello de integridad: raíz de Merkle por lote + cadena de hashes entre lotes (SHA-256).

Especificación (para que cualquiera pueda verificar sin este código):
  1. Hoja = SHA-256 del texto UTF-8 de los CAMPOS de la lectura unidos con "|".
     Números: repr() de Python del float (ej. 7.66); vacío si no hay valor. Booleanos: "1"/"0".
  2. Lote = lecturas con el mismo lote_id, en el orden del archivo publicado.
     Raíz de Merkle: se hashean pares de hojas (digest binario concatenado); si un nivel es impar,
     se duplica la última.
  3. hash_lote = SHA-256 de "lote_id|dataset|n_lecturas|raiz_merkle|hash_lote_anterior".
     El primer lote usa 64 ceros como anterior. Los lotes se encadenan en el orden de cadena_lotes.csv.
  4. Se publica el último hash (cabeza). Cambiar UNA lectura vieja cambia su hoja, la raíz del lote,
     el hash del lote y todos los siguientes: la cabeza publicada deja de coincidir.
Lo que NO se sella: anomalia_id (es la "respuesta" de la demo, no un dato).
"""
import hashlib
import io
import math

import numpy as np
import pandas as pd

CAMPOS = {
    "sensores": ["punto_id", "timestamp_utc", "variable", "valor", "unidad", "origen", "metodo", "fuente"],
    "caudal": ["punto_id", "timestamp_utc", "variable", "valor", "unidad", "origen", "metodo", "fuente"],
    "laboratorio": ["muestra_id", "campana_id", "punto_id", "timestamp_utc", "fecha_precision", "variable", "valor",
                    "unidad", "bajo_ld", "limite_deteccion", "fraccion", "laboratorio", "origen", "metodo", "fuente",
                    "fuente_url"],
}
GENESIS = "0" * 64


def _txt(x) -> str:
    if x is None:
        return ""
    if isinstance(x, (bool, np.bool_)):
        return "1" if x else "0"
    if isinstance(x, (float, np.floating)):
        return "" if math.isnan(x) else repr(float(x))
    if isinstance(x, (int, np.integer)):
        return repr(float(x))
    if isinstance(x, str):
        return x
    if pd.isna(x):
        return ""
    return str(x)


def hojas(df: pd.DataFrame, dataset: str) -> list[bytes]:
    cols = [df[c].tolist() for c in CAMPOS[dataset]]
    return [hashlib.sha256("|".join(_txt(v) for v in fila).encode("utf-8")).digest() for fila in zip(*cols)]


def raiz_merkle(nivel: list[bytes]) -> str:
    if not nivel:
        return hashlib.sha256(b"").hexdigest()
    while len(nivel) > 1:
        if len(nivel) % 2:
            nivel = nivel + [nivel[-1]]
        nivel = [hashlib.sha256(nivel[i] + nivel[i + 1]).digest() for i in range(0, len(nivel), 2)]
    return nivel[0].hex()


def hash_lote(lote_id, dataset, n, raiz, previo) -> str:
    return hashlib.sha256(f"{lote_id}|{dataset}|{n}|{raiz}|{previo}".encode("utf-8")).hexdigest()


def normalizar(df: pd.DataFrame) -> pd.DataFrame:
    """Ida y vuelta por CSV: los tipos quedan iguales a los que verá quien descargue los datos."""
    d = pd.read_csv(io.StringIO(df.to_csv(index=False)), keep_default_na=False, na_values=[""])
    if "bajo_ld" in d:
        d["bajo_ld"] = d["bajo_ld"].astype(bool)
    return d


def asignar_lotes(df: pd.DataFrame, dataset: str) -> pd.Series:
    if dataset == "sensores":
        return "S-" + df["punto_id"] + "-" + df["timestamp_utc"].str.slice(0, 13).str.replace("-", "")
    if dataset == "caudal":
        return "Q-" + df["punto_id"] + "-" + df["timestamp_utc"].str.slice(0, 7)
    if dataset == "laboratorio":
        return "L-" + df["campana_id"]
    raise ValueError(dataset)


def sellar(datasets: dict[str, pd.DataFrame]) -> tuple[dict[str, pd.DataFrame], pd.DataFrame]:
    """Asigna lote_id y hash_lote a cada lectura y arma la cadena de lotes (orden cronológico)."""
    resumen, por_ds = [], {}
    for ds, df in datasets.items():
        df = normalizar(df)  # se sella exactamente lo que se publica en CSV
        df["lote_id"] = asignar_lotes(df, ds)
        df = df.sort_values(["lote_id"], kind="stable").reset_index(drop=True)  # orden publicado = orden sellado
        h = hojas(df, ds)
        lid = df["lote_id"].to_numpy()
        cortes = np.flatnonzero(lid[1:] != lid[:-1]) + 1
        ini = np.concatenate([[0], cortes])
        fin = np.concatenate([cortes, [len(df)]])
        ts = df["timestamp_utc"].to_numpy()
        for a, b in zip(ini, fin):
            resumen.append(dict(lote_id=lid[a], dataset=ds, punto_id=df["punto_id"].iat[a] if ds != "laboratorio" else "varios",
                                desde_utc=min(ts[a:b]), hasta_utc=max(ts[a:b]), n_lecturas=int(b - a),
                                raiz_merkle=raiz_merkle(h[a:b])))
        por_ds[ds] = df
    cadena = pd.DataFrame(resumen).sort_values(["hasta_utc", "dataset", "lote_id"]).reset_index(drop=True)
    previo, hs, ps = GENESIS, [], []
    for f in cadena.itertuples():
        ps.append(previo)
        previo = hash_lote(f.lote_id, f.dataset, f.n_lecturas, f.raiz_merkle, previo)
        hs.append(previo)
    cadena["hash_lote_anterior"] = ps
    cadena["hash_lote"] = hs
    cadena.insert(0, "orden", np.arange(len(cadena)))
    mapa = dict(zip(cadena["lote_id"], cadena["hash_lote"]))
    for ds, df in por_ds.items():
        df["hash_lote"] = df["lote_id"].map(mapa)
    return por_ds, cadena


def verificar(datasets: dict[str, pd.DataFrame], cadena: pd.DataFrame, cabeza: str | None = None) -> list[str]:
    """Recalcula todo. Devuelve la lista de problemas (vacía = íntegro)."""
    problemas = []
    raices = {}
    for ds, df in datasets.items():
        h = hojas(df, ds)
        lid = df["lote_id"].to_numpy()
        cortes = np.flatnonzero(lid[1:] != lid[:-1]) + 1
        ini = np.concatenate([[0], cortes])
        fin = np.concatenate([cortes, [len(df)]])
        for a, b in zip(ini, fin):
            raices[lid[a]] = (raiz_merkle(h[a:b]), int(b - a))
    previo = GENESIS
    for f in cadena.itertuples():
        r = raices.get(f.lote_id)
        if r is None:
            problemas.append(f"lote {f.lote_id}: no está en los datos")
            continue
        if r[0] != f.raiz_merkle or r[1] != f.n_lecturas:
            problemas.append(f"lote {f.lote_id}: las lecturas no coinciden con la raíz sellada")
        if f.hash_lote_anterior != previo:
            problemas.append(f"lote {f.lote_id}: la cadena está cortada (hash anterior distinto)")
        esperado = hash_lote(f.lote_id, f.dataset, r[1], r[0], previo)
        if esperado != f.hash_lote:
            problemas.append(f"lote {f.lote_id}: hash_lote recalculado no coincide")
        previo = esperado
    if cabeza is not None and previo != cabeza:
        problemas.append(f"la cabeza recalculada {previo[:16]}… no coincide con la publicada {cabeza[:16]}…")
    extra = set(raices) - set(cadena["lote_id"])
    if extra:
        problemas.append(f"{len(extra)} lotes en los datos que no figuran en la cadena")
    return problemas
