"""Resolución tienda ↔ almacén ↔ ubicación, leída de stock.warehouse.

El nombre del almacén y el prefijo de su ubicación de existencias no siempre
coinciden (UNIVERSIDAD → UNI/Existencias, GUAYABAL → GUAYA/Existencias). Comparar
el nombre de la tienda contra el de la ubicación deja esas tiendas en existencia 0.
Aquí el mapeo sale de Odoo, no de una lista fija.

Sin dependencias de `mcp` para que los tests puedan importarlo.
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def prefijo_ubicacion(nombre_ubicacion: str) -> str:
    """'UNI/Existencias/Anaquel 1' -> 'UNI'. Primer segmento del complete_name."""
    return (nombre_ubicacion or "").split("/")[0].strip().upper()


def preparar_almacenes(registros: list[dict]) -> list[dict]:
    """Agrega 'prefijo' y 'alias' a cada almacén leído de Odoo."""
    for w in registros:
        lot = w.get("lot_stock_id")
        w["prefijo"] = (
            prefijo_ubicacion(lot[1]) if lot else (w.get("code") or "").strip().upper()
        )
        w["alias"] = {
            a for a in (
                (w.get("name") or "").strip().upper(),
                (w.get("code") or "").strip().upper(),
                w["prefijo"],
            ) if a
        }
    return registros


def cargar_almacenes(odoo: Any) -> list[dict]:
    """Almacenes activos con su prefijo de ubicación real y sus alias de nombre.

    Incluye los tipos de picking propios de cada almacén: `int_type_id` (Traslados
    internos) e `in_type_id` (Recepciones). Sin ellos los traspasos se crean todos
    bajo un mismo almacén.
    """
    return preparar_almacenes(odoo.search_read(
        "stock.warehouse", [],
        ["id", "name", "code", "lot_stock_id", "int_type_id", "in_type_id"],
        limit=0,
    ))


def ubicacion_transito(odoo: Any) -> int | None:
    """Ubicación de tránsito entre almacenes de la compañía del usuario conectado.

    Es el punto intermedio de los 2 pickings: la tienda origen saca la mercancía
    hacia aquí y la tienda destino la recibe desde aquí.

    Se lee de `res.company.internal_transit_location_id`, que es el mismo campo que
    usa Odoo para sus propios traslados entre almacenes. Buscar por `usage='transit'`
    no sirve: hay 24 ubicaciones de tránsito y 17 son de reabastecimiento desde CEDIS
    ("Traslado <TIENDA>"), así que elegir por nombre acertaría por casualidad.
    """
    usuario = odoo.read("res.users", [odoo.uid], ["company_id"])
    company = usuario[0].get("company_id") if usuario else None
    if not company:
        return None

    datos = odoo.read("res.company", [company[0]], ["internal_transit_location_id"])
    transito = datos[0].get("internal_transit_location_id") if datos else None
    return transito[0] if transito else None


def buscar_almacen(almacenes: list[dict], nombre_tienda: str) -> dict | None:
    """Resuelve el nombre de una tienda (POS o almacén) a su almacén.

    Coincidencia exacta contra cualquier alias primero; si no hay, la parcial más
    larga — así 'MINA' no se lleva 'CHEDRAUI MINA' cuando ambos almacenes existen.
    """
    t = (nombre_tienda or "").strip().upper()
    if not t:
        return None
    for w in almacenes:
        if t in w["alias"]:
            return w
    parciales = [
        (len(a), w) for w in almacenes for a in w["alias"] if a in t or t in a
    ]
    if not parciales:
        return None
    return max(parciales, key=lambda p: p[0])[1]


def prefijos_por_tienda(
    odoo: Any, tienda_config: dict[str, int], almacenes: list[dict]
) -> dict[str, str]:
    """{nombre de tienda POS: prefijo de la ubicación de existencias de su almacén}.

    El vínculo real es pos.config → picking_type_id → warehouse_id. Si Odoo no lo
    expone, cae a coincidencia por nombre/código.
    """
    wh_por_config: dict[int, int] = {}
    try:
        configs = odoo.search_read(
            "pos.config", [["id", "in", list(tienda_config.values())]],
            ["id", "picking_type_id"], limit=0,
        )
        pt_ids = [c["picking_type_id"][0] for c in configs if c.get("picking_type_id")]
        tipos = odoo.search_read(
            "stock.picking.type", [["id", "in", pt_ids]], ["id", "warehouse_id"], limit=0,
        )
        wh_por_tipo = {p["id"]: p["warehouse_id"][0] for p in tipos if p.get("warehouse_id")}
        wh_por_config = {
            c["id"]: wh_por_tipo[c["picking_type_id"][0]]
            for c in configs
            if c.get("picking_type_id") and c["picking_type_id"][0] in wh_por_tipo
        }
    except Exception as exc:
        logger.warning("No se pudo mapear pos.config → almacén (%s); se usa el nombre.", exc)

    por_id = {w["id"]: w for w in almacenes}
    prefijos: dict[str, str] = {}
    for tienda, config_id in tienda_config.items():
        w = por_id.get(wh_por_config.get(config_id)) or buscar_almacen(almacenes, tienda)
        if w:
            prefijos[tienda] = w["prefijo"]
        else:
            logger.warning(
                "Tienda '%s' sin almacén resuelto: su existencia se leería como 0.", tienda
            )
    return prefijos


if __name__ == "__main__":
    # Los 17 almacenes reales de SoyAquarius (Odoo, sep-2026).
    REALES = [
        ("CEDIS", "CEDIS/Existencias"),
        ("WACO", "WACO/Existencias"),
        ("BACOAT", "BACOAT/Existencias"),
        ("BACOM", "BACOM/Existencias"),
        ("CHECOM", "CHECOM/Existencias"),
        ("CHEDRAUI MINA", "CHEMI/Existencias"),
        ("CHEDRAUI PARAISO", "CHEPAR/Existencias"),
        ("CITY CENTER", "CITY CENTER/Existencias"),
        ("GUAYABAL", "GUAYA/Existencias"),
        ("MINA", "MINA/Existencias"),
        ("INDUSTRIAL", "INDUS/Existencias"),
        ("PLAZA CRYSTAL", "PC/Existencias"),
        ("SENDERO", "SEND/Existencias"),
        ("UNIVERSIDAD", "UNI/Existencias"),
        ("WALMART DEPORTIVA", "WADE/Existencias"),
        ("WALMART CARRIZAL", "WACA/Existencias"),
        ("ZARAGOZA", "ZARA/Existencias"),
    ]
    ALM = preparar_almacenes([
        {"id": i, "name": nombre, "code": ubic.split("/")[0], "lot_stock_id": [100 + i, ubic]}
        for i, (nombre, ubic) in enumerate(REALES, start=1)
    ])
    por_nombre = {w["name"]: w for w in ALM}

    assert prefijo_ubicacion("UNI/Existencias/Anaquel 1") == "UNI"
    assert prefijo_ubicacion("") == ""

    # Cada almacén se resuelve por su nombre largo Y por el prefijo de su ubicación.
    for nombre, ubic in REALES:
        prefijo = ubic.split("/")[0]
        assert buscar_almacen(ALM, nombre)["name"] == nombre, nombre
        assert buscar_almacen(ALM, prefijo)["name"] == nombre, prefijo

    # Las 4 que rompían el Paso 1: nombre del almacén ≠ prefijo de su ubicación.
    for nombre, esperado in [
        ("UNIVERSIDAD", "UNI"), ("INDUSTRIAL", "INDUS"),
        ("GUAYABAL", "GUAYA"), ("SENDERO", "SEND"),
    ]:
        assert por_nombre[nombre]["prefijo"] == esperado

    # Exacto le gana a parcial: MINA no se resuelve a CHEDRAUI MINA.
    assert buscar_almacen(ALM, "MINA")["name"] == "MINA"
    assert buscar_almacen(ALM, "CHEDRAUI MINA")["prefijo"] == "CHEMI"
    # WACO vs WACA: nombres parecidos, almacenes distintos.
    assert buscar_almacen(ALM, "WACO")["name"] == "WACO"
    assert buscar_almacen(ALM, "WACA")["name"] == "WALMART CARRIZAL"

    assert buscar_almacen(ALM, "NO EXISTE") is None
    assert buscar_almacen(ALM, "") is None
    print(f"OK — {len(ALM)} almacenes resueltos")
