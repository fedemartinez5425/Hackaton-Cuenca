"""Emisor de telemetría "en vivo" para probar la API y el bot.

Dos modos:
  python simular_en_vivo.py                       # tiempo real: cada 15 min emite la lectura nueva de cada punto
  python simular_en_vivo.py --repetir-desde 2025-10-30 --cada 1
        # repetición acelerada: emite un bloque de 15 min por segundo desde esa fecha (ideal para el pitch:
        # arranca 4 días antes de la hipoxia A01)

Por defecto imprime JSON por línea. Con --url hace POST de cada bloque (lista JSON) a la API de Mati:
  python simular_en_vivo.py --url http://localhost:8000/lecturas
Las lecturas son las mismas que en salida/ (misma semilla); el sellado lo hace la API al recibirlas.
"""
import argparse
import json
import sys
import time
import urllib.request

import pandas as pd

from cuenca import config as C
from cuenca.caudal import caudal_diario
from cuenca.sensores import generar_sensores


def emitir(bloque: pd.DataFrame, url: str | None):
    registros = bloque.drop(columns=["anomalia_id"]).to_dict("records")
    if url:
        req = urllib.request.Request(url, data=json.dumps(registros).encode(), method="POST",
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=10) as r:
            print(f"{bloque['timestamp_utc'].iat[0]} → {len(registros)} lecturas, HTTP {r.status}", file=sys.stderr)
    else:
        for r in registros:
            print(json.dumps(r, ensure_ascii=False))
        sys.stdout.flush()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url")
    ap.add_argument("--repetir-desde", help="fecha local AAAA-MM-DD para repetición acelerada")
    ap.add_argument("--cada", type=float, default=1.0, help="segundos entre bloques en modo acelerado")
    a = ap.parse_args()

    ahora = pd.Timestamp.now(tz="UTC").floor(C.PASO_SENSOR)
    print("Generando serie (≈15 s)…", file=sys.stderr)
    caudal, _ = caudal_diario()
    fin = max(ahora + pd.Timedelta(days=1), pd.Timestamp(C.SENSORES_FIN, tz="UTC"))
    sens = generar_sensores(caudal, fin=fin)
    sens["t"] = pd.to_datetime(sens["timestamp_utc"])
    bloques = dict(tuple(sens.groupby("t")))

    if a.repetir_desde:
        t = pd.Timestamp(a.repetir_desde, tz=C.TZ_LOCAL).tz_convert("UTC")
        while t in bloques or t < ahora:
            if t in bloques:
                emitir(bloques[t].drop(columns="t"), a.url)
            t += pd.Timedelta(C.PASO_SENSOR)
            time.sleep(a.cada)
    else:
        t = ahora
        while True:
            if t in bloques:
                emitir(bloques[t].drop(columns="t"), a.url)
            t += pd.Timedelta(C.PASO_SENSOR)
            espera = (t - pd.Timestamp.now(tz="UTC")).total_seconds()
            time.sleep(max(espera, 0))


if __name__ == "__main__":
    main()
