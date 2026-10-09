"""Verifica que los datos publicados no fueron alterados.

Uso:
  python verificar_sello.py                 # verifica todo contra sello_publicado.json
  python verificar_sello.py --demo-alterar  # cambia UNA lectura vieja en memoria y muestra cómo se rompe
"""
import argparse
import json
import time

import pandas as pd

from cuenca import config as C
from cuenca.sellado import verificar


def cargar():
    S = C.SALIDA
    ds = {
        "caudal": pd.read_csv(S / "caudal_diario.csv", keep_default_na=False, na_values=[""]),
        "sensores": pd.read_parquet(S / "lecturas_sensores.parquet"),
        "laboratorio": pd.read_csv(S / "muestreos_laboratorio.csv", keep_default_na=False, na_values=[""]),
    }
    ds["laboratorio"]["bajo_ld"] = ds["laboratorio"]["bajo_ld"].astype(bool)
    cadena = pd.read_csv(S / "cadena_lotes.csv")
    sello = json.loads((S / "sello_publicado.json").read_text())
    return ds, cadena, sello


def main(demo=False):
    t0 = time.time()
    ds, cadena, sello = cargar()
    if demo:
        s = ds["sensores"]
        i = s.index[(s["punto_id"] == "EMB") & (s["variable"] == "oxigeno_disuelto")
                    & (s["timestamp_utc"] == "2025-11-03T17:00:00Z")][0]
        print(f"ALTERACIÓN: OD en EMB el 3-nov-2025 14:00 (hora local) pasa de {s.at[i, 'valor']} a 8.5 mg/l")
        s.at[i, "valor"] = 8.5
    problemas = verificar(ds, cadena, sello["cabeza_cadena"])
    n = sum(len(v) for v in ds.values())
    if problemas:
        lotes = sorted({p.split(":")[0] for p in problemas if p.startswith("lote ")},
                       key=lambda x: problemas.index(next(q for q in problemas if q.startswith(x))))
        print(f"✗ NO íntegro ({n:,} lecturas / {len(cadena):,} lotes).")
        print(f"  Primer problema: {problemas[0]}")
        print(f"  Lotes afectados desde ahí en adelante: {len(lotes):,} (la cadena queda rota hasta la cabeza)")
        if problemas[-1].startswith("la cabeza"):
            print(f"  {problemas[-1]}")
    else:
        print(f"✓ Íntegro: {n:,} lecturas en {len(cadena):,} lotes; cabeza {sello['cabeza_cadena'][:16]}… "
              f"({time.time() - t0:.1f} s)")
    return not problemas


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--demo-alterar", action="store_true")
    raise SystemExit(0 if main(ap.parse_args().demo_alterar) else 1)
