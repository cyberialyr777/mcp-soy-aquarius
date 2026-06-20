"""Tools MCP del módulo de traspasos — Sprint 3.

Cuatro tools:
  traspasos_verificar_cedis   — existencia actual en CEDIS por proveedor
  traspasos_calcular_plan     — Paso 2: plan de traspasos (CEDIS → rezagadas → activos)
  traspasos_crear_borrador    — crea pickings internos en borrador en Odoo
  traspasos_validar           — valida (confirma) pickings en borrador
"""
import json
import logging

from mcp.server.fastmcp import FastMCP

from src.engines.purchase_planner import ProductoSugerido
from src.engines.transfer_planner import TransferPlanner
from src.odoo.connector import OdooConnector, OdooConnectionError
from src.tools.compras import calcular_sugeridos_proveedor, _get_product_ids_for_proveedor
from src.tools.schemas import (
    TraspasosCedisInput,
    TraspasosPlanInput,
    TraspasosBorradorInput,
    TraspasosValidarInput,
)

logger = logging.getLogger(__name__)


def _err(e: Exception) -> str:
    if isinstance(e, OdooConnectionError):
        return f"Error Odoo: {e}"
    return f"Error inesperado ({type(e).__name__}): {e}"


def _buscar_location_id(all_locs: list[dict], nombre_tienda: str) -> int | None:
    """Busca el location ID que mejor coincide con el nombre de la tienda."""
    t_upper = nombre_tienda.strip().upper()
    # Coincidencia exacta primero
    for loc in all_locs:
        if loc.get("name", "").upper() == t_upper:
            return loc["id"]
    # Coincidencia parcial en nombre corto
    for loc in all_locs:
        if t_upper in loc.get("name", "").upper():
            return loc["id"]
    # Coincidencia parcial en nombre completo
    for loc in all_locs:
        if t_upper in loc.get("complete_name", "").upper():
            return loc["id"]
    return None


def register(mcp: FastMCP, odoo: OdooConnector) -> None:

    @mcp.tool(
        name="traspasos_verificar_cedis",
        annotations={
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        },
    )
    def traspasos_verificar_cedis(params: TraspasosCedisInput) -> str:
        """Verifica la existencia actual en CEDIS para los productos de un proveedor.

        Consulta stock.quant filtrando por ubicaciones internas cuyo nombre contenga
        el cedis_keyword. Útil para saber qué puede redistribuir CEDIS antes del pedido.

        Args:
            params: proveedor (str), cedis_keyword (str, default='CEDIS')

        Returns:
            JSON con schema:
            {
                "proveedor": str,
                "cedis_tienda": str,
                "productos": [
                    {"product_id": int, "nombre": str, "existencia": float, "reservado": float, "disponible": float}
                ],
                "total_productos_con_stock": int
            }
        """
        try:
            product_ids, nombres = _get_product_ids_for_proveedor(odoo, params.proveedor)

            if not product_ids:
                return json.dumps({
                    "proveedor": params.proveedor,
                    "cedis_tienda": params.cedis_keyword,
                    "productos": [],
                    "total_productos_con_stock": 0,
                    "advertencia": f"No se encontraron productos para '{params.proveedor}'",
                }, ensure_ascii=False)

            quants = odoo.search_read(
                "stock.quant",
                [
                    ["product_id", "in", product_ids],
                    ["location_id.usage", "=", "internal"],
                    ["location_id.name", "ilike", params.cedis_keyword],
                ],
                ["product_id", "location_id", "quantity", "reserved_quantity"],
                limit=0,
            )

            cedis_nombre = ""
            productos = []
            for q in quants:
                pid = q["product_id"][0] if q["product_id"] else None
                if not pid:
                    continue
                existencia = float(q["quantity"] or 0)
                reservado = float(q["reserved_quantity"] or 0)
                disponible = max(0.0, existencia - reservado)
                if not cedis_nombre and q["location_id"]:
                    cedis_nombre = q["location_id"][1]
                productos.append({
                    "product_id": pid,
                    "nombre": nombres.get(pid, str(pid)),
                    "existencia": existencia,
                    "reservado": reservado,
                    "disponible": disponible,
                })

            productos.sort(key=lambda x: x["existencia"], reverse=True)

            return json.dumps({
                "proveedor": params.proveedor,
                "cedis_tienda": cedis_nombre or params.cedis_keyword,
                "productos": productos,
                "total_productos_con_stock": sum(1 for p in productos if p["existencia"] > 0),
            }, ensure_ascii=False)

        except Exception as e:
            return _err(e)

    @mcp.tool(
        name="traspasos_calcular_plan",
        annotations={
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        },
    )
    def traspasos_calcular_plan(params: TraspasosPlanInput) -> str:
        """Calcula el plan de traspasos (Paso 2) para un proveedor.

        Ejecuta internamente el Paso 1 (stock sugerido) y luego calcula qué mover
        entre tiendas antes de hacer el pedido al proveedor.

        Orden de prioridad de fuente:
          1. CEDIS (puede quedar en 0)
          2. Tiendas Rezagadas/Críticas (> 100 días sin venta, pueden quedar en 0)
          3. Tiendas Activas con excedente (solo cuando existencia > nuevo_MAX)

        Tiendas excluidas como destino: BACOAT, WACO, CERES.
        Piso de eficiencia: traspasos < 3 unidades se ignoran salvo producto Crítico
        o cobertura destino < 7 días.

        Args:
            params: proveedor, fecha_inicio ('YYYY-MM-DD'), fecha_fin ('YYYY-MM-DD'),
                    cedis_keyword (default='CEDIS')

        Returns:
            JSON con schema:
            {
                "proveedor": str,
                "lineas": [
                    {
                        "product_id": int,
                        "nombre": str,
                        "origen": str,
                        "destino": str,
                        "cantidad": int,
                        "tipo_origen": "CEDIS"|"Rezagado"|"Critico"|"Activo_excedente"
                    }
                ],
                "resumen": [
                    {
                        "tienda": str,
                        "product_id": int,
                        "nombre": str,
                        "rotacion": str,
                        "abc": str,
                        "existencia_antes": float,
                        "enviado": float,
                        "recibido": float,
                        "existencia_despues": float,
                        "nuevo_maximo": int,
                        "qty_a_pedir": int
                    }
                ],
                "total_unidades_a_traspasar": int,
                "total_lineas": int
            }
        """
        try:
            # Paso 1: stock sugerido para tiendas con POS
            sugeridos_por_tienda, _ = calcular_sugeridos_proveedor(
                odoo, params.proveedor, params.fecha_inicio, params.fecha_fin
            )

            if not sugeridos_por_tienda:
                return json.dumps({
                    "proveedor": params.proveedor,
                    "lineas": [],
                    "resumen": [],
                    "total_unidades_a_traspasar": 0,
                    "total_lineas": 0,
                    "advertencia": "No se encontraron ventas del proveedor en el periodo",
                }, ensure_ascii=False)

            # Obtener product_ids para consultar CEDIS
            product_ids, nombres = _get_product_ids_for_proveedor(odoo, params.proveedor)

            # Agregar CEDIS al mapa si tiene stock del proveedor
            quants_cedis = odoo.search_read(
                "stock.quant",
                [
                    ["product_id", "in", product_ids],
                    ["location_id.usage", "=", "internal"],
                    ["location_id.name", "ilike", params.cedis_keyword],
                ],
                ["product_id", "location_id", "quantity", "reserved_quantity"],
                limit=0,
            )

            cedis_nombre = params.cedis_keyword
            stock_cedis: dict[int, float] = {}
            if quants_cedis:
                cedis_nombre = quants_cedis[0]["location_id"][1] if quants_cedis[0]["location_id"] else params.cedis_keyword
                for q in quants_cedis:
                    pid = q["product_id"][0] if q["product_id"] else None
                    if pid:
                        stock_cedis[pid] = stock_cedis.get(pid, 0.0) + float(q["quantity"] or 0)

            # Crear entradas sintéticas de CEDIS (nuevo_maximo=0 → nunca es destino)
            if stock_cedis:
                cedis_prods = [
                    ProductoSugerido(
                        product_id=pid,
                        nombre=nombres.get(pid, str(pid)),
                        tienda=cedis_nombre,
                        rotacion="Activo",
                        abc="A",
                        patron="regular",
                        ventas_3m=[],
                        existencia_actual=qty,
                        nuevo_maximo=0,
                        nuevo_minimo=0,
                    )
                    for pid, qty in stock_cedis.items()
                    if qty > 0
                ]
                if cedis_prods:
                    sugeridos_por_tienda[cedis_nombre] = cedis_prods

            # Paso 2: calcular plan de traspasos
            planner = TransferPlanner()
            lineas, resumen = planner.calcular_plan(sugeridos_por_tienda, params.cedis_keyword)

            lineas_json = [
                {
                    "product_id": l.product_id,
                    "nombre": l.nombre,
                    "origen": l.origen,
                    "destino": l.destino,
                    "cantidad": l.cantidad,
                    "tipo_origen": l.tipo_origen,
                }
                for l in lineas
            ]
            resumen_json = [
                {
                    "tienda": r.tienda,
                    "product_id": r.product_id,
                    "nombre": r.nombre,
                    "rotacion": r.rotacion,
                    "abc": r.abc,
                    "existencia_antes": r.existencia_antes,
                    "enviado": r.enviado,
                    "recibido": r.recibido,
                    "existencia_despues": r.existencia_despues,
                    "nuevo_maximo": r.nuevo_maximo,
                    "qty_a_pedir": r.qty_a_pedir,
                }
                for r in resumen
            ]

            return json.dumps({
                "proveedor": params.proveedor,
                "lineas": lineas_json,
                "resumen": resumen_json,
                "total_unidades_a_traspasar": sum(l["cantidad"] for l in lineas_json),
                "total_lineas": len(lineas_json),
            }, ensure_ascii=False)

        except Exception as e:
            return _err(e)

    @mcp.tool(
        name="traspasos_crear_borrador",
        annotations={
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": True,
        },
    )
    def traspasos_crear_borrador(params: TraspasosBorradorInput) -> str:
        """Crea pickings de traspaso interno en borrador en Odoo a partir del plan.

        Para cada par (origen, destino) único en las lineas, crea un stock.picking
        de tipo 'internal' con las líneas de movimiento correspondientes.
        Los pickings quedan en estado 'draft' para revisión antes de validar.

        Args:
            params: lineas_json (JSON string del array 'lineas' de traspasos_calcular_plan),
                    origen_referencia (str, opcional — se usa como campo 'origin' del picking)

        Returns:
            JSON con schema:
            {
                "pickings_creados": [
                    {"picking_id": int, "name": str, "origen": str, "destino": str, "lineas": int}
                ],
                "errores": [str],
                "total_pickings": int
            }
        """
        try:
            lineas = json.loads(params.lineas_json)
            if not lineas:
                return json.dumps({
                    "pickings_creados": [],
                    "errores": [],
                    "total_pickings": 0,
                    "advertencia": "No hay líneas de traspaso para crear",
                }, ensure_ascii=False)

            # Cargar todas las ubicaciones internas para hacer el matching
            all_locs = odoo.search_read(
                "stock.location",
                [["usage", "=", "internal"], ["active", "=", True]],
                ["id", "name", "complete_name"],
                limit=0,
            )

            # Obtener picking type 'internal' (primer resultado)
            picking_types = odoo.search_read(
                "stock.picking.type",
                [["code", "=", "internal"]],
                ["id", "name"],
                limit=1,
            )
            if not picking_types:
                return "Error: no se encontró un tipo de picking interno en Odoo"
            picking_type_id = picking_types[0]["id"]

            # Obtener UOM por defecto de los productos
            pids_unicos = list({l["product_id"] for l in lineas})
            products_data = odoo.search_read(
                "product.product",
                [["id", "in", pids_unicos]],
                ["id", "uom_id"],
                limit=0,
            )
            uom_por_product: dict[int, int] = {
                p["id"]: p["uom_id"][0] for p in products_data if p.get("uom_id")
            }

            # Agrupar líneas por (origen, destino)
            grupos: dict[tuple[str, str], list[dict]] = {}
            for linea in lineas:
                key = (linea["origen"], linea["destino"])
                grupos.setdefault(key, []).append(linea)

            pickings_creados = []
            errores = []

            for (origen, destino), grupo_lineas in grupos.items():
                loc_origen_id = _buscar_location_id(all_locs, origen)
                loc_destino_id = _buscar_location_id(all_locs, destino)

                if not loc_origen_id:
                    errores.append(f"No se encontró ubicación para '{origen}'")
                    continue
                if not loc_destino_id:
                    errores.append(f"No se encontró ubicación para '{destino}'")
                    continue

                referencia = params.origen_referencia or "MCP-TRASPASO"

                # Crear picking
                picking_id = odoo.create(
                    "stock.picking",
                    {
                        "picking_type_id": picking_type_id,
                        "location_id": loc_origen_id,
                        "location_dest_id": loc_destino_id,
                        "origin": referencia,
                    },
                )

                # Crear stock.move por cada línea del grupo
                for linea in grupo_lineas:
                    pid = linea["product_id"]
                    uom_id = uom_por_product.get(pid)
                    if not uom_id:
                        errores.append(f"Sin UOM para producto {pid} — línea omitida")
                        continue
                    odoo.create(
                        "stock.move",
                        {
                            "picking_id": picking_id,
                            "product_id": pid,
                            "product_uom_qty": linea["cantidad"],
                            "product_uom": uom_id,
                            "location_id": loc_origen_id,
                            "location_dest_id": loc_destino_id,
                            "name": linea.get("nombre", str(pid)),
                        },
                    )

                # Obtener nombre asignado por Odoo
                picking_data = odoo.search_read(
                    "stock.picking",
                    [["id", "=", picking_id]],
                    ["name"],
                    limit=1,
                )
                picking_name = picking_data[0]["name"] if picking_data else str(picking_id)

                pickings_creados.append({
                    "picking_id": picking_id,
                    "name": picking_name,
                    "origen": origen,
                    "destino": destino,
                    "lineas": len(grupo_lineas),
                })

                logger.info("Picking %s creado: %s → %s (%d líneas)", picking_name, origen, destino, len(grupo_lineas))

            return json.dumps({
                "pickings_creados": pickings_creados,
                "errores": errores,
                "total_pickings": len(pickings_creados),
            }, ensure_ascii=False)

        except Exception as e:
            return _err(e)

    @mcp.tool(
        name="traspasos_validar",
        annotations={
            "readOnlyHint": False,
            "destructiveHint": True,
            "idempotentHint": False,
            "openWorldHint": True,
        },
    )
    def traspasos_validar(params: TraspasosValidarInput) -> str:
        """Valida (confirma) pickings de traspaso en borrador.

        Llama a button_validate en cada stock.picking indicado.
        ATENCIÓN: acción destructiva — el stock se mueve definitivamente.
        Solo ejecutar después de revisar el borrador.

        Args:
            params: picking_ids (list[int]) — IDs de stock.picking a validar

        Returns:
            JSON con schema:
            {
                "validados": [{"picking_id": int, "name": str}],
                "errores": [str],
                "total_validados": int
            }
        """
        try:
            validados = []
            errores = []

            for pid in params.picking_ids:
                try:
                    odoo.call_method("stock.picking", "button_validate", [pid])
                    picking_data = odoo.search_read(
                        "stock.picking",
                        [["id", "=", pid]],
                        ["name", "state"],
                        limit=1,
                    )
                    name = picking_data[0]["name"] if picking_data else str(pid)
                    validados.append({"picking_id": pid, "name": name})
                    logger.info("Picking %s validado", name)
                except Exception as e_inner:
                    errores.append(f"Picking {pid}: {type(e_inner).__name__}: {e_inner}")

            return json.dumps({
                "validados": validados,
                "errores": errores,
                "total_validados": len(validados),
            }, ensure_ascii=False)

        except Exception as e:
            return _err(e)
