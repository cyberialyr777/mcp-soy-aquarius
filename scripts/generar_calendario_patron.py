"""Deriva el PATRÓN de pedidos a proveedores desde el Excel del calendario.

El Excel tiene una hoja por mes. En cada hoja: col A = día del mes, col B = día de
la semana, cols C+ = proveedores a los que se pide ESE día. El día exacto deriva mes
a mes (se ancla a días hábiles), pero la *cadencia* y la *posición típica en el mes*
son estables. Este script pool-ea todos los días históricos de cada proveedor y fija
su(s) día(s) representativo(s) del mes + su frecuencia.

Salida: src/config/calendario_patron.json  (independiente del año; el runtime sintetiza
las fechas de cualquier mes desde este patrón).

Uso:  py scripts/generar_calendario_patron.py
Actualiza el Excel y vuelve a correrlo cuando cambien las frecuencias.
"""
import json
import statistics
from pathlib import Path

import openpyxl

RAIZ = Path(__file__).resolve().parent.parent
EXCEL = RAIZ / "CALENDARIO Y DIRECTORIO PEDIDOS (1).xlsx"
OUT = RAIZ / "src" / "config" / "calendario_patron.json"

# Hojas que no son calendarios mensuales.
IGNORAR = {"DIRECTORIO", "HOJA 1"}


def leer_por_proveedor(path: Path) -> dict[str, dict]:
    """{proveedor: {"dias": [pool global], "counts": [pedidos por mes observado]}}."""
    wb = openpyxl.load_workbook(path, data_only=True)
    data: dict[str, dict] = {}
    for ws in wb.worksheets:
        if ws.title.strip().upper() in IGNORAR:
            continue
        del_mes: dict[str, list[int]] = {}  # proveedor -> dias en ESTA hoja
        for row in ws.iter_rows(values_only=True):
            dia = row[0]
            if not isinstance(dia, (int, float)) or not (1 <= int(dia) <= 31):
                continue
            for cell in row[2:]:  # cols C+ = proveedores
                if isinstance(cell, str) and cell.strip():
                    del_mes.setdefault(cell.strip().upper(), []).append(int(dia))
        for name, dias in del_mes.items():
            d = data.setdefault(name, {"dias": [], "counts": []})
            d["dias"].extend(dias)
            d["counts"].append(len(dias))
    return data


def clusters(dias: list[int], freq: int) -> list[int]:
    """Divide los días ordenados en `freq` grupos y toma la mediana de cada uno."""
    dias = sorted(dias)
    n = len(dias)
    reps: list[int] = []
    for i in range(freq):
        grupo = dias[i * n // freq:(i + 1) * n // freq] or dias
        r = round(statistics.median(grupo))
        if not reps or r - reps[-1] >= 3:  # separación mínima de 3 días
            reps.append(r)
    return reps or [round(statistics.median(dias))]


def frecuencia(pedidos_por_mes: float) -> str:
    if pedidos_por_mes >= 3.5:
        return "semanal"
    if pedidos_por_mes >= 1.5:
        return "quincenal"
    return "mensual"


def main() -> None:
    data = leer_por_proveedor(EXCEL)

    proveedores = {}
    for name, d in sorted(data.items()):
        avg = statistics.mean(d["counts"])          # pedidos/mes reales
        freq = max(1, min(4, round(avg)))
        proveedores[name] = {
            "dias": clusters(d["dias"], freq),
            "frecuencia": frecuencia(avg),
        }

    OUT.write_text(
        json.dumps({"proveedores": proveedores}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"OK: {len(proveedores)} proveedores -> {OUT}")
    for prov in ["TONICOL", "DXN", "GENESIS", "OMNILIFE", "RED NATURA"]:
        m = next((n for n in proveedores if prov in n or n in prov), None)
        if m:
            print(f"  {m:14s} {proveedores[m]}")


if __name__ == "__main__":
    main()
