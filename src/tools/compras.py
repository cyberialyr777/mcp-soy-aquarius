"""Tools MCP del módulo de compras — Sprint 2.

Cuatro tools:
  compras_get_ventas_anio        — ventas del año por proveedor, tienda y mes
  compras_get_orderpoints        — reglas de reorden actuales
  compras_calcular_stock_sugerido — Paso 1 completo (rotación, ABC, patrón, nuevo_MAX)
  compras_get_calendario         — fechas de pedido del proveedor (desde JSON)

Helper público reutilizable por Sprint 3:
  calcular_sugeridos_proveedor() — ejecuta Paso 1, retorna {tienda: [ProductoSugerido]}
"""
import json
import logging
from datetime import date, timedelta
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from src.odoo.connector import OdooConnector, OdooConnectionError
from src.tools.schemas import (
    ComprasGetVentasAnioInput,
    ComprasGetOrderpointsInput,
    ComprasCalcularStockSugeridoInput,
    ComprasGetCalendarioInput,
)
from src.engines.purchase_planner import PurchasePlanner, VentaMes, StockQuant

logger = logging.getLogger(__name__)

_PATRON_PATH = Path(__file__).parent.parent / "config" / "calendario_patron.json"
_MESES_VENTANA = 12  # meses sintetizados hacia adelante desde el mes actual
_DIAS_SEMANA = ["LUNES", "MARTES", "MIERCOLES", "JUEVES", "VIERNES", "SABADO", "DOMINGO"]


def _err(e: Exception) -> str:
    if isinstance(e, OdooConnectionError):
        return f"Error Odoo: {e}"
    return f"Error inesperado ({type(e).__name__}): {e}"


def _fecha_valida(anio: int, mes: int, dia: int) -> date:
    """Ajusta el día al rango del mes y mueve domingos a lunes (no se pide en domingo)."""
    ultimo = (date(anio + (mes == 12), (mes % 12) + 1, 1) - timedelta(days=1)).day
    d = date(anio, mes, min(dia, ultimo))
    if d.weekday() == 6:  # domingo
        d += timedelta(days=1)
    return d


def _get_calendario(hoy: date | None = None) -> dict:
    """Sintetiza el calendario desde el patrón fijo por proveedor (calendario_patron.json).

    Genera una ventana móvil de _MESES_VENTANA meses a partir del mes actual, así que
    funciona para cualquier mes de cualquier año sin regenerar nada. Mismo schema que
    antes: {mes_iso: {"nombre_hoja": str, "pedidos": {proveedor: [{dia, dia_semana}]}}}.
    """
    patron = json.loads(_PATRON_PATH.read_text(encoding="utf-8"))["proveedores"]
    hoy = hoy or date.today()
    calendario = {}
    for i in range(_MESES_VENTANA):
        m = hoy.month - 1 + i
        anio, mes = hoy.year + m // 12, m % 12 + 1
        mes_iso = f"{anio}-{mes:02d}"
        pedidos = {}
        for name, info in patron.items():
            fechas = [
                {"dia": (d := _fecha_valida(anio, mes, dia)).day, "dia_semana": _DIAS_SEMANA[d.weekday()]}
                for dia in info["dias"]
            ]
            pedidos[name] = sorted(fechas, key=lambda f: f["dia"])
        calendario[mes_iso] = {"nombre_hoja": mes_iso, "pedidos": pedidos}
    return calendario


def _buscar_proveedor_en_calendario(calendario: dict, proveedor: str) -> dict[str, list]:
    """Retorna {mes_iso: [{dia, dia_semana}]} con todas las apariciones del proveedor."""
    proveedor_upper = proveedor.strip().upper()
    resultado: dict[str, list] = {}

    for mes_iso, mes_data in calendario.items():
        pedidos = mes_data.get("pedidos", {})
        for nombre_prov, fechas in pedidos.items():
            if proveedor_upper in nombre_prov or nombre_prov in proveedor_upper:
                resultado[mes_iso] = fechas
                break

    return dict(sorted(resultado.items()))


def _estimar_frecuencia(apariciones_por_mes: dict[str, list]) -> str:
    """Estima la frecuencia de pedido basándose en cuántas veces aparece por mes."""
    if not apariciones_por_mes:
        return "sin datos"
    promedios = [len(v) for v in apariciones_por_mes.values()]
    avg = sum(promedios) / len(promedios)
    if avg >= 3.5:
        return "semanal"
    elif avg >= 1.5:
        return "quincenal"
    elif avg >= 0.8:
        return "mensual"
    else:
        return "bimestral o menor"


def _get_product_ids_for_proveedor(odoo: OdooConnector, proveedor: str) -> tuple[list[int], dict[int, str]]:
    """Retorna (product_ids, {id: nombre}) para un proveedor dado."""
    supplierinfo = odoo.search_read(
        "product.supplierinfo",
        [["partner_id.name", "ilike", proveedor]],
        ["product_tmpl_id", "product_id"],
        limit=0,
    )

    product_ids_set: set[int] = set()
    tmpl_ids: list[int] = []

    for s in supplierinfo:
        if s.get("product_id") and s["product_id"]:
            product_ids_set.add(s["product_id"][0])
        elif s.get("product_tmpl_id"):
            tmpl_ids.append(s["product_tmpl_id"][0])

    if tmpl_ids:
        variantes = odoo.search_read(
            "product.product",
            [["product_tmpl_id", "in", tmpl_ids], ["active", "=", True]],
            ["id", "name"],
            limit=0,
        )
        for v in variantes:
            product_ids_set.add(v["id"])

    product_ids = list(product_ids_set)

    if not product_ids:
        return [], {}

    products_data = odoo.search_read(
        "product.product",
        [["id", "in", product_ids]],
        ["id", "name"],
        limit=0,
    )
    nombres = {p["id"]: p["name"] for p in products_data}
    return product_ids, nombres


def _get_orders_in_period(
    odoo: OdooConnector,
    fecha_inicio: str,
    fecha_fin: str,
    tienda: str = "",
) -> dict[int, dict]:
    """Retorna {order_id: {mes, tienda}} para pedidos POS en el periodo."""
    domain = [
        ["date_order", ">=", fecha_inicio + " 00:00:00"],
        ["date_order", "<=", fecha_fin + " 23:59:59"],
        ["state", "in", ["done", "invoiced"]],
    ]
    if tienda:
        domain.append(["config_id.name", "ilike", tienda])

    orders = odoo.search_read(
        "pos.order",
        domain,
        ["id", "date_order", "config_id"],
        limit=0,
    )
    return {
        o["id"]: {
            "mes": o["date_order"][:7],
            "tienda": o["config_id"][1] if o["config_id"] else "SIN_TIENDA",
        }
        for o in orders
    }


def calcular_sugeridos_proveedor(
    odoo: OdooConnector,
    proveedor: str,
    fecha_inicio: str,
    fecha_fin: str,
    tienda: str = "",
) -> tuple[dict[str, list], list[str]]:
    """Ejecuta Paso 1 completo para todas las tiendas de un proveedor.

    Reutilizable por traspasos.py (Paso 2) sin duplicar lógica.

    Returns:
        ({tienda: [ProductoSugerido]}, meses_disponibles)
        Retorna ({}, []) si no hay productos o ventas.
    Raises:
        Exception si hay error de conexión con Odoo.
    """
    planner = PurchasePlanner()
    product_ids, nombres = _get_product_ids_for_proveedor(odoo, proveedor)

    if not product_ids:
        return {}, []

    _fecha: list = [
        ["order_id.date_order", ">=", fecha_inicio + " 00:00:00"],
        ["order_id.date_order", "<=", fecha_fin + " 23:59:59"],
        ["order_id.state", "in", ["done", "invoiced"]],
    ]
    if tienda:
        _fecha.append(["order_id.config_id.name", "ilike", tienda])

    lines_proveedor = odoo.search_read(
        "pos.order.line",
        [["product_id", "in", product_ids]] + _fecha,
        ["product_id", "qty", "order_id"],
        limit=0,
    )

    if not lines_proveedor:
        return {}, []

    oids_proveedor = list({
        (line["order_id"][0] if isinstance(line["order_id"], list) else line["order_id"])
        for line in lines_proveedor
    })
    orders_meta = odoo.search_read(
        "pos.order",
        [["id", "in", oids_proveedor]],
        ["id", "date_order", "config_id"],
        limit=0,
    )
    order_info: dict[int, dict] = {
        o["id"]: {
            "mes": o["date_order"][:7],
            "tienda": o["config_id"][1] if o["config_id"] else "SIN_TIENDA",
            "config_id": o["config_id"][0] if o["config_id"] else None,
        }
        for o in orders_meta
    }

    tienda_config: dict[str, int] = {}
    for info in order_info.values():
        if info["config_id"] and info["tienda"] not in tienda_config:
            tienda_config[info["tienda"]] = info["config_id"]

    tiendas_unicas = sorted(tienda_config.keys())
    meses_disponibles = sorted({info["mes"] for info in order_info.values()})

    quants_raw = odoo.search_read(
        "stock.quant",
        [["product_id", "in", product_ids], ["location_id.usage", "=", "internal"]],
        ["product_id", "location_id", "quantity", "reserved_quantity"],
        limit=0,
    )

    abc_por_tienda: dict[str, dict[int, float]] = {}
    for t, config_id in tienda_config.items():
        abc_rows = odoo.read_group(
            "pos.order.line",
            [
                ["order_id.date_order", ">=", fecha_inicio + " 00:00:00"],
                ["order_id.date_order", "<=", fecha_fin + " 23:59:59"],
                ["order_id.state", "in", ["done", "invoiced"]],
                ["order_id.config_id", "=", config_id],
            ],
            ["product_id", "qty"],
            ["product_id"],
            lazy=False,
        )
        catalogo: dict[int, float] = {}
        for row in abc_rows:
            pid_raw = row.get("product_id")
            pid = pid_raw[0] if isinstance(pid_raw, list) else int(pid_raw or 0)
            qty = float(row.get("qty", 0) or 0)
            if pid and qty > 0:
                catalogo[pid] = catalogo.get(pid, 0.0) + qty
        abc_por_tienda[t] = catalogo

    sugeridos_por_tienda: dict[str, list] = {}

    for t in tiendas_unicas:
        ventas_tienda: list[VentaMes] = []
        for line in lines_proveedor:
            oid = line["order_id"][0] if isinstance(line["order_id"], list) else line["order_id"]
            info = order_info.get(oid, {})
            if info.get("tienda") != t:
                continue
            qty = float(line["qty"] or 0)
            if qty <= 0:
                continue
            ventas_tienda.append(VentaMes(
                product_id=line["product_id"][0],
                tienda=t,
                mes=info.get("mes", ""),
                qty=qty,
            ))

        has_product_sales = bool(ventas_tienda)
        has_product_stock = any(
            t.upper() in (q["location_id"][1] if q["location_id"] else "").upper()
            for q in quants_raw
        )
        if not has_product_sales and not has_product_stock:
            continue

        quants_tienda: list[StockQuant] = []
        for q in quants_raw:
            loc_name = q["location_id"][1] if q["location_id"] else ""
            if t.upper() in loc_name.upper():
                quants_tienda.append(StockQuant(
                    product_id=q["product_id"][0],
                    tienda=t,
                    existencia=float(q["quantity"] or 0),
                    reservado=float(q["reserved_quantity"] or 0),
                ))

        sugeridos = planner.calcular(
            proveedor=proveedor,
            tienda=t,
            ventas_proveedor=ventas_tienda,
            ventas_catalogo_anual=abc_por_tienda.get(t, {}),
            quants=quants_tienda,
            productos=nombres,
            meses_disponibles=meses_disponibles,
        )

        if sugeridos:
            sugeridos_por_tienda[t] = sugeridos

    return sugeridos_por_tienda, meses_disponibles


def register(mcp: FastMCP, odoo: OdooConnector) -> None:

    @mcp.tool(
        name="compras_get_ventas_anio",
        annotations={
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        },
    )
    def compras_get_ventas_anio(params: ComprasGetVentasAnioInput) -> str:
        """Obtiene ventas del año en curso por proveedor, agrupadas por tienda y mes.

        Consulta pos.order.line filtrando por los productos del proveedor en el rango
        de fechas indicado. Insumo principal para calcular stock sugerido (Paso 1).

        Args:
            params: proveedor, fecha_inicio ('YYYY-MM-DD'), fecha_fin ('YYYY-MM-DD'),
                    tienda (opcional, vacío = todas las tiendas)

        Returns:
            JSON con schema:
            {
                "proveedor": str,
                "periodo": {"inicio": str, "fin": str},
                "meses": ["YYYY-MM", ...],
                "ventas": [
                    {"product_id": int, "nombre": str, "tienda": str, "mes": str, "qty": float}
                ],
                "productos": {"<id>": str}
            }
            En caso de error: "Error Odoo: <mensaje>"
        """
        try:
            product_ids, nombres = _get_product_ids_for_proveedor(odoo, params.proveedor)

            if not product_ids:
                return json.dumps({
                    "proveedor": params.proveedor,
                    "periodo": {"inicio": params.fecha_inicio, "fin": params.fecha_fin},
                    "meses": [],
                    "ventas": [],
                    "productos": {},
                    "advertencia": f"No se encontraron productos para proveedor '{params.proveedor}'",
                }, ensure_ascii=False)

            order_info = _get_orders_in_period(odoo, params.fecha_inicio, params.fecha_fin, params.tienda)

            if not order_info:
                return json.dumps({
                    "proveedor": params.proveedor,
                    "periodo": {"inicio": params.fecha_inicio, "fin": params.fecha_fin},
                    "meses": [],
                    "ventas": [],
                    "productos": {str(k): v for k, v in nombres.items()},
                    "advertencia": "No se encontraron pedidos POS en el periodo",
                }, ensure_ascii=False)

            lines = odoo.search_read(
                "pos.order.line",
                [
                    ["product_id", "in", product_ids],
                    ["order_id", "in", list(order_info.keys())],
                ],
                ["product_id", "qty", "order_id"],
                limit=0,
            )

            ventas_list = []
            meses_set: set[str] = set()

            for line in lines:
                pid = line["product_id"][0]
                oid = line["order_id"][0] if isinstance(line["order_id"], list) else line["order_id"]
                info = order_info.get(oid, {})
                mes = info.get("mes", "")
                tienda_nombre = info.get("tienda", "SIN_TIENDA")
                qty = float(line["qty"] or 0)

                if qty <= 0 or not mes:
                    continue

                meses_set.add(mes)
                ventas_list.append({
                    "product_id": pid,
                    "nombre": nombres.get(pid, str(pid)),
                    "tienda": tienda_nombre,
                    "mes": mes,
                    "qty": qty,
                })

            return json.dumps({
                "proveedor": params.proveedor,
                "periodo": {"inicio": params.fecha_inicio, "fin": params.fecha_fin},
                "meses": sorted(meses_set),
                "ventas": ventas_list,
                "productos": {str(k): v for k, v in nombres.items()},
            }, ensure_ascii=False)

        except Exception as e:
            return _err(e)

    @mcp.tool(
        name="compras_get_orderpoints",
        annotations={
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        },
    )
    def compras_get_orderpoints(params: ComprasGetOrderpointsInput) -> str:
        """Obtiene las reglas de reorden (orderpoints) actuales para un proveedor.

        Lee stock.warehouse.orderpoint filtrando por los productos del proveedor.
        Incluye product_min_qty, product_max_qty y qty_to_order actuales.

        Args:
            params: proveedor (str), tienda (str, opcional)

        Returns:
            JSON array de orderpoints:
            [{"id": int, "product_id": int, "nombre": str, "location": str,
              "product_min_qty": float, "product_max_qty": float, "qty_to_order": float}]
            En caso de error: "Error Odoo: <mensaje>"
        """
        try:
            product_ids, nombres = _get_product_ids_for_proveedor(odoo, params.proveedor)

            if not product_ids:
                return json.dumps([], ensure_ascii=False)

            domain: list = [["product_id", "in", product_ids]]
            if params.tienda:
                domain.append(["location_id.name", "ilike", params.tienda])

            orderpoints = odoo.search_read(
                "stock.warehouse.orderpoint",
                domain,
                ["product_id", "location_id", "product_min_qty", "product_max_qty", "qty_to_order"],
                limit=0,
            )

            result = [
                {
                    "id": op["id"],
                    "product_id": op["product_id"][0] if op["product_id"] else None,
                    "nombre": op["product_id"][1] if op["product_id"] else "",
                    "location": op["location_id"][1] if op["location_id"] else "",
                    "product_min_qty": op["product_min_qty"],
                    "product_max_qty": op["product_max_qty"],
                    "qty_to_order": op["qty_to_order"],
                }
                for op in orderpoints
            ]

            return json.dumps(result, ensure_ascii=False, default=str)

        except Exception as e:
            return _err(e)

    @mcp.tool(
        name="compras_calcular_stock_sugerido",
        annotations={
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        },
    )
    def compras_calcular_stock_sugerido(params: ComprasCalcularStockSugeridoInput) -> str:
        """Calcula el stock sugerido (Paso 1) para todos los productos de un proveedor en todas las tiendas.

        Flujo completo:
        1. Obtiene productos del proveedor via product.supplierinfo
        2. Consulta ventas del periodo por tienda y mes (pos.order.line)
        3. Consulta catálogo ABC del año completo por tienda (pos.order.line — todos los productos)
        4. Consulta stock actual (stock.quant)
        5. Para cada tienda × producto: calcula rotación, ABC, patrón y nuevo_máximo/mínimo

        Args:
            params: proveedor, fecha_inicio ('YYYY-MM-DD'), fecha_fin ('YYYY-MM-DD'),
                    tienda (opcional, vacío = todas las tiendas)

        Returns:
            JSON con schema:
            {
                "proveedor": str,
                "tiendas": [
                    {
                        "tienda": str,
                        "productos": [
                            {
                                "product_id": int,
                                "nombre": str,
                                "rotacion": "Activo"|"Rezagado"|"Critico"|"Nunca_entrado",
                                "abc": "A"|"B"|"C",
                                "patron": "80_20"|"pico_sostenido"|"pico_aislado"|"regular",
                                "ventas_3m": [float, float, float],
                                "existencia_actual": float,
                                "nuevo_maximo": int,
                                "nuevo_minimo": int
                            }
                        ]
                    }
                ]
            }
            En caso de error: "Error Odoo: <mensaje>"
        """
        try:
            sugeridos_por_tienda, _ = calcular_sugeridos_proveedor(
                odoo, params.proveedor, params.fecha_inicio, params.fecha_fin, params.tienda
            )

            if not sugeridos_por_tienda:
                return json.dumps({
                    "proveedor": params.proveedor,
                    "tiendas": [],
                    "advertencia": "No se encontraron productos o ventas para el proveedor en el periodo",
                }, ensure_ascii=False)

            resultados_tiendas = [
                {
                    "tienda": tienda,
                    "productos": [
                        {
                            "product_id": s.product_id,
                            "nombre": s.nombre,
                            "rotacion": s.rotacion,
                            "abc": s.abc,
                            "patron": s.patron,
                            "ventas_3m": s.ventas_3m,
                            "existencia_actual": s.existencia_actual,
                            "nuevo_maximo": s.nuevo_maximo,
                            "nuevo_minimo": s.nuevo_minimo,
                        }
                        for s in sugeridos
                    ],
                }
                for tienda, sugeridos in sorted(sugeridos_por_tienda.items())
            ]

            return json.dumps({
                "proveedor": params.proveedor,
                "tiendas": resultados_tiendas,
            }, ensure_ascii=False)

        except Exception as e:
            return _err(e)

    @mcp.tool(
        name="compras_get_calendario",
        annotations={
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        },
    )
    def compras_get_calendario(params: ComprasGetCalendarioInput) -> str:
        """Retorna el calendario de pedidos del proveedor para los próximos 12 meses.

        Sintetiza las fechas desde el patrón fijo por proveedor (src/config/calendario_patron.json,
        derivado del Excel con scripts/generar_calendario_patron.py). Funciona para cualquier
        mes/año. Muestra en qué días de cada mes está programado el pedido del proveedor.

        Args:
            params: proveedor (str)

        Returns:
            JSON con schema:
            {
                "proveedor": str,
                "frecuencia_estimada": "semanal"|"quincenal"|"mensual"|"bimestral o menor"|"sin datos",
                "meses": [
                    {
                        "mes": "YYYY-MM",
                        "nombre_hoja": str,
                        "fechas": [{"dia": int, "dia_semana": str}]
                    }
                ],
                "total_meses_con_pedido": int
            }
        """
        try:
            calendario = _get_calendario()
            apariciones = _buscar_proveedor_en_calendario(calendario, params.proveedor)
            frecuencia = _estimar_frecuencia(apariciones)

            meses_resultado = [
                {
                    "mes": mes_iso,
                    "nombre_hoja": calendario[mes_iso]["nombre_hoja"],
                    "fechas": fechas,
                }
                for mes_iso, fechas in apariciones.items()
            ]

            return json.dumps({
                "proveedor": params.proveedor,
                "frecuencia_estimada": frecuencia,
                "meses": meses_resultado,
                "total_meses_con_pedido": len(meses_resultado),
            }, ensure_ascii=False)

        except Exception as e:
            return f"Error al leer calendario: {e}"
