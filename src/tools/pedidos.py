"""Tools MCP del módulo de pedidos — Sprint 4.

Tres tools:
  pedidos_crear_registros            — Paso 3: calcula qty_to_order leyendo x_traspasos
                                       verificados y carga resultados en x_pedidos
  pedidos_actualizar_reabastecimiento — Daniel aprueba: actualiza stock.warehouse.orderpoint
  pedidos_get_estado                 — consulta estado de registros en x_pedidos
"""
import json
import logging
from collections import defaultdict

from mcp.server.fastmcp import FastMCP

from src.engines.orderpoint_updater import OrderpointUpdater, RegistroPedido
from src.engines.transfer_planner import ResumenPostTraspaso
from src.odoo.connector import OdooConnector, OdooConnectionError
from src.tools.compras import calcular_sugeridos_proveedor, _get_product_ids_for_proveedor
from src.tools.schemas import (
    PedidosCrearRegistrosInput,
    PedidosActualizarReabastecimientoInput,
    PedidosGetEstadoInput,
)

logger = logging.getLogger(__name__)


def _err(e: Exception) -> str:
    if isinstance(e, OdooConnectionError):
        return f"Error Odoo: {e}"
    return f"Error inesperado ({type(e).__name__}): {e}"


def _leer_traspasos_verificados(
    odoo: OdooConnector, proveedor: str
) -> dict[tuple[int, str, str], float]:
    """Lee x_traspasos (state=verificado|ejecutado) y retorna {(pid, origen, destino): cantidad_final}."""
    registros = odoo.search_read(
        "x_traspasos",
        [["proveedor", "=", proveedor], ["state", "in", ["verificado", "ejecutado"]]],
        ["product_id", "origen", "destino", "cantidad_final"],
        limit=0,
    )
    resultado: dict[tuple[int, str, str], float] = {}
    for r in registros:
        pid = r["product_id"][0] if isinstance(r.get("product_id"), list) else r.get("product_id")
        if pid:
            key = (pid, r.get("origen", ""), r.get("destino", ""))
            resultado[key] = resultado.get(key, 0.0) + float(r.get("cantidad_final") or 0)
    return resultado


def _ajustar_existencia_con_traspasos(
    sugeridos_por_tienda: dict,
    traspasos_verificados: dict[tuple[int, str, str], float],
) -> list[ResumenPostTraspaso]:
    """Aplica los traspasos verificados sobre la existencia del Paso 1 y retorna resumen."""
    enviado: dict[tuple[int, str], float] = defaultdict(float)
    recibido: dict[tuple[int, str], float] = defaultdict(float)

    for (pid, origen, destino), cantidad in traspasos_verificados.items():
        enviado[(pid, origen)] += cantidad
        recibido[(pid, destino)] += cantidad

    resumen: list[ResumenPostTraspaso] = []
    for tienda, prods in sugeridos_por_tienda.items():
        for p in prods:
            env = enviado.get((p.product_id, tienda), 0.0)
            rec = recibido.get((p.product_id, tienda), 0.0)
            existencia_despues = p.existencia_actual - env + rec
            qty_a_pedir = max(0, p.nuevo_maximo - int(existencia_despues))
            resumen.append(ResumenPostTraspaso(
                tienda=tienda,
                product_id=p.product_id,
                nombre=p.nombre,
                rotacion=p.rotacion,
                abc=p.abc,
                existencia_antes=p.existencia_actual,
                enviado=env,
                recibido=rec,
                existencia_despues=existencia_despues,
                nuevo_maximo=p.nuevo_maximo,
                qty_a_pedir=qty_a_pedir,
            ))
    return resumen


def register(mcp: FastMCP, odoo: OdooConnector) -> None:

    @mcp.tool(
        name="pedidos_crear_registros",
        annotations={
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": True,
        },
    )
    def pedidos_crear_registros(params: PedidosCrearRegistrosInput) -> str:
        """Calcula el pedido final (Paso 3) y carga resultados en el módulo x_pedidos.

        Flujo interno:
        1. Re-ejecuta Paso 1 (stock sugerido) para obtener nuevo_maximo y existencia_actual.
        2. Lee x_traspasos con state=verificado|ejecutado para obtener traspasos confirmados.
        3. Calcula existencia_despues usando cantidad_final de x_traspasos.
        4. qty_to_order = max(0, nuevo_maximo − existencia_despues).
        5. Crea registros en x_pedidos con state='pendiente'.

        Args:
            params: proveedor, fecha_inicio, fecha_fin, cedis_keyword (default='CEDIS')

        Returns:
            JSON con schema:
            {
                "proveedor": str,
                "creados": int,
                "ids": [int],
                "registros": [
                    {
                        "product_id": int,
                        "nombre": str,
                        "tienda": str,
                        "existencia_antes": float,
                        "existencia_despues": float,
                        "nuevo_maximo": int,
                        "qty_to_order": int,
                        "orderpoint_id": int|null,
                        "rotacion": str,
                        "abc": str
                    }
                ],
                "errores": [str]
            }
        """
        try:
            sugeridos_por_tienda, _ = calcular_sugeridos_proveedor(
                odoo, params.proveedor, params.fecha_inicio, params.fecha_fin
            )
            if not sugeridos_por_tienda:
                return json.dumps({
                    "proveedor": params.proveedor,
                    "creados": 0,
                    "ids": [],
                    "registros": [],
                    "errores": [],
                    "advertencia": "No se encontraron ventas del proveedor en el periodo",
                }, ensure_ascii=False)

            traspasos_verificados = _leer_traspasos_verificados(odoo, params.proveedor)
            resumen = _ajustar_existencia_con_traspasos(sugeridos_por_tienda, traspasos_verificados)

            # Cargar orderpoints para obtener IDs
            product_ids, _ = _get_product_ids_for_proveedor(odoo, params.proveedor)
            orderpoints_raw = odoo.search_read(
                "stock.warehouse.orderpoint",
                [["product_id", "in", product_ids]],
                ["id", "product_id", "location_id", "product_min_qty", "product_max_qty"],
                limit=0,
            )
            orderpoints = [
                {
                    "id": op["id"],
                    "product_id": op["product_id"][0] if op["product_id"] else None,
                    "location": op["location_id"][1] if op["location_id"] else "",
                }
                for op in orderpoints_raw
            ]

            updater = OrderpointUpdater()
            paso3 = updater.calcular_paso3(resumen, orderpoints, params.cedis_keyword)

            ids_creados = []
            errores = []
            registros_json = []

            for r in paso3:
                registros_json.append({
                    "product_id": r.product_id,
                    "nombre": r.nombre,
                    "tienda": r.tienda,
                    "existencia_antes": r.existencia_antes,
                    "existencia_despues": r.existencia_despues,
                    "nuevo_maximo": r.nuevo_maximo,
                    "qty_to_order": r.qty_to_order,
                    "orderpoint_id": r.orderpoint_id,
                    "rotacion": r.rotacion,
                    "abc": r.abc,
                })
                try:
                    rec_id = odoo.create("x_pedidos", {
                        "proveedor": params.proveedor,
                        "product_id": r.product_id,
                        "orderpoint_id": r.orderpoint_id,
                        "product_min_qty": r.nuevo_minimo,
                        "product_max_qty": r.nuevo_maximo,
                        "propuesta_max": r.nuevo_maximo,
                        "qty_to_order": r.qty_to_order,
                        "existencia_antes": r.existencia_antes,
                        "existencia_despues": r.existencia_despues,
                        "rotacion": r.rotacion,
                        "abc": r.abc,
                        "state": "pendiente",
                    })
                    ids_creados.append(rec_id)
                except Exception as e_inner:
                    errores.append(f"{r.nombre} @ {r.tienda}: {e_inner}")

            logger.info(
                "pedidos_crear_registros: %d registros en x_pedidos para %s",
                len(ids_creados), params.proveedor,
            )

            return json.dumps({
                "proveedor": params.proveedor,
                "creados": len(ids_creados),
                "ids": ids_creados,
                "registros": registros_json,
                "errores": errores,
            }, ensure_ascii=False)

        except Exception as e:
            return _err(e)

    @mcp.tool(
        name="pedidos_actualizar_reabastecimiento",
        annotations={
            "readOnlyHint": False,
            "destructiveHint": True,
            "idempotentHint": False,
            "openWorldHint": True,
        },
    )
    def pedidos_actualizar_reabastecimiento(params: PedidosActualizarReabastecimientoInput) -> str:
        """Actualiza stock.warehouse.orderpoint con los valores aprobados en x_pedidos.

        Lee los registros de x_pedidos para el proveedor (state=pendiente), usa
        'propuesta_max' (que las tiendas pudieron editar) para actualizar min/max/qty_to_order
        en los orderpoints correspondientes.

        ATENCIÓN: acción destructiva — modifica las reglas de reabastecimiento en Odoo.
        Solo ejecutar después de que Daniel haya revisado los registros en x_pedidos.

        Args:
            params: proveedor (str)

        Returns:
            JSON con schema:
            {
                "actualizados": int,
                "errores": [str],
                "sin_orderpoint": int
            }
        """
        try:
            registros = odoo.search_read(
                "x_pedidos",
                [["proveedor", "=", params.proveedor], ["state", "=", "pendiente"]],
                ["id", "orderpoint_id", "propuesta_max", "existencia_despues", "product_id"],
                limit=0,
            )

            if not registros:
                return json.dumps({
                    "actualizados": 0,
                    "errores": [],
                    "sin_orderpoint": 0,
                    "advertencia": f"No hay registros pendientes en x_pedidos para '{params.proveedor}'",
                }, ensure_ascii=False)

            actualizados = 0
            errores = []
            sin_op = 0

            for reg in registros:
                op_raw = reg.get("orderpoint_id")
                op_id = op_raw[0] if isinstance(op_raw, list) else op_raw
                if not op_id:
                    sin_op += 1
                    continue

                propuesta = float(reg.get("propuesta_max") or 0)
                existencia_despues = float(reg.get("existencia_despues") or 0)
                qty_to_order = max(0.0, propuesta - existencia_despues)

                try:
                    odoo.write("stock.warehouse.orderpoint", [op_id], {
                        "product_min_qty": propuesta,
                        "product_max_qty": propuesta,
                        "qty_to_order": qty_to_order,
                    })
                    odoo.write("x_pedidos", [reg["id"]], {"state": "aprobado"})
                    actualizados += 1
                except Exception as e_inner:
                    errores.append(f"Orderpoint {op_id}: {e_inner}")

            logger.info(
                "pedidos_actualizar_reabastecimiento: %d orderpoints actualizados para %s",
                actualizados, params.proveedor,
            )

            return json.dumps({
                "actualizados": actualizados,
                "errores": errores,
                "sin_orderpoint": sin_op,
            }, ensure_ascii=False)

        except Exception as e:
            return _err(e)

    @mcp.tool(
        name="pedidos_get_estado",
        annotations={
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        },
    )
    def pedidos_get_estado(params: PedidosGetEstadoInput) -> str:
        """Consulta el estado actual de los registros en x_pedidos para un proveedor.

        Args:
            params: proveedor (str), state (str, default='' → todos)

        Returns:
            JSON con schema:
            {
                "proveedor": str,
                "registros": [
                    {
                        "id": int,
                        "product_id": int,
                        "nombre": str,
                        "product_max_qty": float,
                        "propuesta_max": float,
                        "qty_to_order": float,
                        "existencia_despues": float,
                        "state": str,
                        "rotacion": str,
                        "abc": str
                    }
                ],
                "total": int,
                "pendientes": int,
                "aprobados": int
            }
        """
        try:
            domain: list = [["proveedor", "=", params.proveedor]]
            if params.state:
                domain.append(["state", "=", params.state])

            registros = odoo.search_read(
                "x_pedidos",
                domain,
                ["id", "product_id", "product_max_qty", "propuesta_max",
                 "qty_to_order", "existencia_despues", "state", "rotacion", "abc"],
                limit=0,
            )

            filas = [
                {
                    "id": r["id"],
                    "product_id": r["product_id"][0] if isinstance(r.get("product_id"), list) else r.get("product_id"),
                    "nombre": r["product_id"][1] if isinstance(r.get("product_id"), list) else "",
                    "product_max_qty": r.get("product_max_qty", 0),
                    "propuesta_max": r.get("propuesta_max", 0),
                    "qty_to_order": r.get("qty_to_order", 0),
                    "existencia_despues": r.get("existencia_despues", 0),
                    "state": r.get("state", ""),
                    "rotacion": r.get("rotacion", ""),
                    "abc": r.get("abc", ""),
                }
                for r in registros
            ]

            return json.dumps({
                "proveedor": params.proveedor,
                "registros": filas,
                "total": len(filas),
                "pendientes": sum(1 for f in filas if f["state"] == "pendiente"),
                "aprobados": sum(1 for f in filas if f["state"] == "aprobado"),
            }, ensure_ascii=False)

        except Exception as e:
            return _err(e)
