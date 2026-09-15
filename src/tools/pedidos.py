"""Tools MCP del módulo de pedidos — Sprint 4.

Tres tools:
  pedidos_crear_registros            — Paso 3: calcula qty_to_order leyendo x_traspasos
                                       verificados y carga resultados en x_pedidos
  pedidos_actualizar_reabastecimiento — Daniel aprueba: actualiza stock.warehouse.orderpoint
  pedidos_get_estado                 — consulta estado de registros en x_pedidos
"""
import json
import logging
from datetime import datetime, timezone

from mcp.server.fastmcp import FastMCP

from src.engines.orderpoint_updater import (
    OrderpointUpdater,
    RegistroPedido,
    TraspasoConfirmado,
    movimientos_pendientes,
)
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


def _id_de(valor) -> int | None:
    """Extrae el id de un campo Many2one de Odoo: [id, nombre] → id."""
    if isinstance(valor, list):
        return valor[0] if valor else None
    return valor or None


def _leer_traspasos_confirmados(
    odoo: OdooConnector, proveedor: str
) -> list[TraspasoConfirmado]:
    """Lee x_traspasos (verificado|ejecutado) junto con el estado real de sus pickings.

    El estado de cada picking decide si la mercancía ya se movió. Sin eso, los
    traspasos ya validados se aplicarían otra vez sobre una existencia que ya los
    incluye — y los de todos los meses anteriores también.
    """
    dominio = [["proveedor", "=", proveedor], ["state", "in", ["verificado", "ejecutado"]]]
    campos = ["product_id", "origen", "destino", "cantidad_final",
              "picking_id", "picking_entrada_id"]
    try:
        registros = odoo.search_read("x_traspasos", dominio, campos, limit=0)
    except Exception:
        # El campo todavía no existe en Odoo: se puede desplegar antes de crearlo,
        # pero sin él no se sabe si la mercancía ya llegó al destino y ese lado se
        # sigue contando dos veces. Mejor avisar que tumbar el Paso 3 entero.
        logger.warning(
            "x_traspasos sin campo 'picking_entrada_id': solo se verifica el picking "
            "de salida. Agrégalo en Odoo para que el Paso 3 sepa si la mercancía ya "
            "llegó a la tienda destino."
        )
        campos.remove("picking_entrada_id")
        registros = odoo.search_read("x_traspasos", dominio, campos, limit=0)

    picking_ids = {
        pid for r in registros
        for pid in (_id_de(r.get("picking_id")), _id_de(r.get("picking_entrada_id")))
        if pid
    }
    estados: dict[int, str] = {}
    if picking_ids:
        estados = {
            p["id"]: p.get("state", "")
            for p in odoo.search_read(
                "stock.picking", [["id", "in", list(picking_ids)]], ["id", "state"], limit=0)
        }

    confirmados: list[TraspasoConfirmado] = []
    for r in registros:
        pid = _id_de(r.get("product_id"))
        if not pid:
            continue
        salida = _id_de(r.get("picking_id"))
        entrada = _id_de(r.get("picking_entrada_id"))
        confirmados.append(TraspasoConfirmado(
            product_id=pid,
            origen=r.get("origen", ""),
            destino=r.get("destino", ""),
            cantidad=float(r.get("cantidad_final") or 0),
            estado_salida=estados.get(salida, "") if salida else "",
            estado_entrada=estados.get(entrada, "") if entrada else "",
        ))
    return confirmados


def _ajustar_existencia_con_traspasos(
    sugeridos_por_tienda: dict,
    traspasos: list[TraspasoConfirmado],
) -> list[ResumenPostTraspaso]:
    """Aplica sobre la existencia del Paso 1 solo los traspasos todavía pendientes."""
    enviado, recibido = movimientos_pendientes(traspasos)

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
        2. Lee x_traspasos con state=verificado|ejecutado junto con el estado de sus
           pickings de salida y recepción.
        3. Aplica SOLO los traspasos todavía pendientes: lo ya validado en Odoo ya
           está reflejado en stock.quant y contarlo otra vez lo duplicaría. Cada lado
           se evalúa aparte (la tienda origen saca la mercancía días antes de que la
           destino la reciba), y los traspasos de meses anteriores quedan fuera solos.
        4. qty_to_order = max(0, nuevo_maximo − existencia_despues).
        5. Carga en x_pedidos con state='pendiente'. Si ya hay un registro pendiente
           del mismo producto y tienda, lo actualiza en vez de duplicarlo.

        Args:
            params: proveedor, fecha_inicio, fecha_fin, cedis_keyword (default='CEDIS')

        Returns:
            JSON con schema:
            {
                "proveedor": str,
                "creados": int,
                "actualizados": int,
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
                    "actualizados": 0,
                    "ids": [],
                    "registros": [],
                    "errores": [],
                    "advertencia": "No se encontraron ventas del proveedor en el periodo",
                }, ensure_ascii=False)

            traspasos = _leer_traspasos_confirmados(odoo, params.proveedor)
            resumen = _ajustar_existencia_con_traspasos(sugeridos_por_tienda, traspasos)

            # Cargar orderpoints para obtener IDs
            product_ids, _ = _get_product_ids_for_proveedor(odoo, params.proveedor)
            orderpoints_raw = odoo.search_read(
                "stock.warehouse.orderpoint",
                [["product_id", "in", product_ids]],
                ["id", "product_id", "location_id", "warehouse_id",
                 "product_min_qty", "product_max_qty"],
                limit=0,
            )
            wh_ids = list({op["warehouse_id"][0] for op in orderpoints_raw if op.get("warehouse_id")})
            wh_codes = {w["id"]: (w.get("code") or "") for w in odoo.search_read(
                "stock.warehouse", [["id", "in", wh_ids]], ["id", "code"], limit=0)}
            orderpoints = [
                {
                    "id": op["id"],
                    "product_id": op["product_id"][0] if op["product_id"] else None,
                    "location": op["location_id"][1] if op["location_id"] else "",
                    "almacen": op["warehouse_id"][1] if op["warehouse_id"] else "",
                    "codigo": wh_codes.get(op["warehouse_id"][0], "") if op.get("warehouse_id") else "",
                }
                for op in orderpoints_raw
            ]

            updater = OrderpointUpdater()
            paso3 = updater.calcular_paso3(resumen, orderpoints, params.cedis_keyword)

            # Registros pendientes de una corrida anterior del mismo proveedor, para
            # actualizarlos en vez de duplicarlos. Los que no tienen orderpoint no se
            # pueden identificar por tienda (x_pedidos no guarda la tienda), así que
            # esos sí se vuelven a crear.
            pendientes_previos: dict[tuple[int, int | None], int] = {}
            for prev in odoo.search_read(
                "x_pedidos",
                [["proveedor", "=", params.proveedor], ["state", "=", "pendiente"]],
                ["id", "product_id", "orderpoint_id"],
                limit=0,
            ):
                op_prev = _id_de(prev.get("orderpoint_id"))
                pid_prev = _id_de(prev.get("product_id"))
                if pid_prev and op_prev:
                    pendientes_previos.setdefault((pid_prev, op_prev), prev["id"])

            ids_creados = []
            ids_actualizados = []
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
                valores = {
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
                }
                try:
                    # Si ya hay un registro pendiente de este producto y tienda, se
                    # actualiza. Crear otro dejaría dos versiones del mismo pedido
                    # conviviendo, y al aprobar ambas escribirían sobre el mismo
                    # orderpoint.
                    existente = pendientes_previos.get((r.product_id, r.orderpoint_id))
                    if existente:
                        odoo.write("x_pedidos", [existente], valores)
                        ids_actualizados.append(existente)
                    else:
                        ids_creados.append(odoo.create("x_pedidos", valores))
                except Exception as e_inner:
                    errores.append(f"{r.nombre} @ {r.tienda}: {e_inner}")

            logger.info(
                "pedidos_crear_registros: %d creados y %d actualizados en x_pedidos para %s",
                len(ids_creados), len(ids_actualizados), params.proveedor,
            )

            return json.dumps({
                "proveedor": params.proveedor,
                "creados": len(ids_creados),
                "actualizados": len(ids_actualizados),
                "ids": ids_creados + ids_actualizados,
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

        Lee los registros de x_pedidos para el proveedor (state=pendiente) y usa
        'propuesta_final' para actualizar min/max en los orderpoints. Es la columna de
        Daniel — la decisión final —, no 'propuesta_max', que es lo que propuso la
        vendedora y él pudo haber cambiado.

        'qty_to_order' se calcula igual que el botón: max(0, propuesta_final −
        existencia_despues).

        Escribe el mismo resultado que el botón x_pedidos.action_actualizar_reabastecimiento
        del módulo traspasos_pedidos, autoría incluida.

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
                ["id", "orderpoint_id", "propuesta_final", "existencia_despues", "product_id"],
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

                propuesta = float(reg.get("propuesta_final") or 0)
                existencia_despues = float(reg.get("existencia_despues") or 0)
                qty_to_order = max(0.0, propuesta - existencia_despues)

                try:
                    odoo.write("stock.warehouse.orderpoint", [op_id], {
                        "product_min_qty": propuesta,
                        "product_max_qty": propuesta,
                        "qty_to_order": qty_to_order,
                    })
                    odoo.write("x_pedidos", [reg["id"]], {
                        "state": "aprobado",
                        "aprobado_por": odoo.uid,
                        "aprobado_el": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
                    })
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
