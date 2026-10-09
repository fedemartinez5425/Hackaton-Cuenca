"""Genera todas las series de Cuenca Abierta en ./salida.

Uso:  python generar.py            (todo, ~1 min)
      python generar.py --sin-graficos
"""
import argparse
import json
import time
from datetime import datetime, timezone

import pandas as pd

from cuenca import config as C
from cuenca.caudal import caudal_diario
from cuenca.laboratorio import generar_laboratorio
from cuenca.sellado import sellar
from cuenca.semaforo import ica_ccme, semaforo_diario, semaforo_laboratorio
from cuenca.sensores import generar_sensores


def main(graficos=True):
    t0 = time.time()
    S = C.SALIDA
    S.mkdir(exist_ok=True)

    print("1/6 caudal diario 2001-2026 …")
    caudal, mensual = caudal_diario()
    m = mensual.reset_index().rename(columns={"index": "fecha"})
    m["fecha"] = m["fecha"].dt.strftime("%Y-%m-%d")
    m = m.rename(columns={"valor": "valor_modelo", "valor_ajustado": "valor"})
    m["valor"] = m["valor"].round(3)
    m["valor_modelo"] = m["valor_modelo"].round(3)
    m["clim"] = m["clim"].round(3)
    m[["fecha", "valor", "origen", "metodo", "estado_fuente", "clim"]].assign(
        punto_id="PP", unidad="m3/s").to_csv(S / "caudal_mensual_pp.csv", index=False)
    obj = pd.DataFrame([{"anio_hidrologico": a, **o} for a, o in mensual.attrs["objetivos_pac"].items()])
    obj.to_csv(S / "caudal_objetivos_anuales_pac.csv", index=False)

    print("2/6 telemetría cada 15 min (PP, EMB, PAC) …")
    sens = generar_sensores(caudal)

    print("3/6 muestreos de laboratorio …")
    lab = generar_laboratorio(caudal, sens)

    print("4/6 sellado (Merkle por lote + cadena) …")
    caudal_pub = caudal[["punto_id", "timestamp_utc", "variable", "valor", "unidad", "origen", "metodo",
                         "fuente", "base_mensual"]]
    sellados, cadena = sellar({"caudal": caudal_pub, "sensores": sens, "laboratorio": lab})
    sellados["caudal"].to_csv(S / "caudal_diario.csv", index=False)
    sellados["sensores"].to_parquet(S / "lecturas_sensores.parquet", index=False)
    sellados["sensores"].to_csv(S / "lecturas_sensores.csv.gz", index=False, compression="gzip")
    sellados["laboratorio"].to_csv(S / "muestreos_laboratorio.csv", index=False)
    cadena.to_csv(S / "cadena_lotes.csv", index=False)
    sello = {
        "cabeza_cadena": cadena["hash_lote"].iat[-1],
        "n_lotes": int(len(cadena)),
        "n_lecturas": {k: int(len(v)) for k, v in sellados.items()},
        "generado_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "generador": C.VERSION_GENERADOR, "semilla": C.SEMILLA,
        "algoritmo": "SHA-256; raíz de Merkle por lote; hash_lote = SHA256(lote_id|dataset|n|raiz|anterior)",
        "como_verificar": "python verificar_sello.py",
    }
    (S / "sello_publicado.json").write_text(json.dumps(sello, indent=2, ensure_ascii=False))

    an = pd.DataFrame(C.ANOMALIAS)
    for c in ["inicio", "pico", "fin"]:
        an[c] = an[c].apply(lambda x: x.strftime("%Y-%m-%dT%H:%M:%SZ") if pd.notna(x) else "")
    an = an.rename(columns={"inicio": "inicio_utc", "pico": "pico_utc", "fin": "fin_utc",
                            "esperado": "que_deberia_hacer_la_plataforma"})
    n_esp = int((sens["anomalia_id"] == "QC_ESPURIA").sum())
    an.loc[len(an)] = dict(anomalia_id="QC_ESPURIA", tipo="lectura_espuria", punto_id="PP;EMB;PAC",
                           variables="ph;conductividad;temperatura;oxigeno_disuelto;turbidez",
                           descripcion=f"{n_esp} lecturas aisladas absurdas (saltos de pH ±1,2, T +8 °C, etc.)",
                           inspiracion="Ruido instrumental típico", intensidad=None,
                           que_deberia_hacer_la_plataforma="Filtrarlas en control de calidad; no deben disparar alertas.")
    an["origen"] = "simulado"
    an.to_csv(S / "anomalias.csv", index=False)

    print("5/6 semáforos e índice CCME …")
    sd = semaforo_diario(sens)
    sd.to_csv(S / "semaforo_diario.csv", index=False)
    semaforo_laboratorio(lab).to_csv(S / "semaforo_laboratorio.csv", index=False)
    ica_ccme(lab).to_csv(S / "ica_ccme.csv", index=False)
    ultimo = sd[(sd["variable"] == "_resumen")]
    ultimo = ultimo[ultimo["fecha"] == ultimo["fecha"].max()]
    actual = {p: {r.uso: {"color": r.color, "frase": r.frase} for r in g.itertuples()}
              for p, g in ultimo.groupby("punto_id")}
    (S / "semaforo_actual.json").write_text(json.dumps({"fecha": ultimo["fecha"].max(), "origen": "simulado",
                                                        "puntos": actual}, indent=2, ensure_ascii=False))
    ult = sellados["sensores"]
    ult[ult["timestamp_utc"] >= (pd.Timestamp(C.SENSORES_FIN) - pd.Timedelta(hours=48)).strftime("%Y-%m-%dT%H")] \
        .to_csv(S / "muestra_lecturas_ultimas_48h.csv", index=False)

    if graficos:
        print("6/6 gráficos de validación …")
        from cuenca.graficos import todos
        todos(caudal, m, sens, lab, sd)
    print(f"Listo en {time.time() - t0:.0f} s. Cabeza de la cadena: {sello['cabeza_cadena']}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--sin-graficos", action="store_true")
    main(not ap.parse_args().sin_graficos)
