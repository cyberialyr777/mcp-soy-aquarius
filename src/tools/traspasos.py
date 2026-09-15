"""Tools MCP del módulo de traspasos — Sprint 3 + Sprint 5b.

Tres tools activos:
  traspasos_verificar_cedis   — existencia actual en CEDIS por proveedor
  traspasos_calcular_plan     — Paso 2: plan de traspasos (CEDIS → rezagadas → activos)
  traspasos_cargar_modulo     — carga el plan como filas borrador en x_traspasos (NO crea pickings)
  traspasos_get_estado        — consulta filas en x_traspasos por proveedor y estado
  traspasos_generar_pickings  — lee verificados en x_traspasos y crea stock.picking en lote
"""
import json
import logging
from datetime import date

from mcp.server.fastmcp import FastMCP

from src.engines.purchase_planner import ProductoSugerido
from src.engines.transfer_planner import TransferPlanner
from src.odoo.almacenes import buscar_almacen, cargar_almacenes, ubicacion_transito
from src.odoo.connector import OdooConnector, OdooConnectionError
from src.tools.compras import calcular_sugeridos_proveedor, _get_product_ids_for_proveedor
from src.tools.schemas import (
    TraspasosCedisInput,
    TraspasosPlanInput,
    TraspasosCargarModuloInput,
    TraspasosGetEstadoInput,
    TraspasosGenerarPickingsInput,
)

logger = logging.getLogger(__name__)


def _err(e: Exception) -> str:
    if isinstance(e, OdooConnectionError):
        return f"Error Odoo: {e}"
    return f"Error inesperado ({type(e).__name__}): {e}"


def _referencia_corrida(proveedor: str) -> str:
    """Etiqueta del lote: 'PROSA-2026-09'. Permite ver a qué corrida pertenece una fila."""
    return f"{proveedor}-{date.today():%Y-%m}"


def _buscar_location_id(
    all_locs: list[dict], almacenes: list[dict], nombre_tienda: str
) -> int | None:
    """Ubicación de existencias de la tienda, resuelta por su almacén en Odoo.

    Cae a coincidencia por nombre de ubicación solo si la tienda no tiene almacén.
    """
    w = buscar_almacen(almacenes, nombre_tienda)
    if w and w.get("lot_stock_id"):
        return w["lot_stock_id"][0]

    t_upper = nombre_tienda.strip().upper()
    for loc in all_locs:
        if loc.get("name", "").upper() == t_upper:
            return loc["id"]
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

            # El nombre de la ubicación es "Existencias"; CEDIS solo vive en su
            # complete_name. Se resuelve por almacén y se baja a sus hijas.
            cedis = buscar_almacen(cargar_almacenes(odoo), params.cedis_keyword)
            if not cedis or not cedis.get("lot_stock_id"):
                return json.dumps({
                    "proveedor": params.proveedor,
                    "cedis_tienda": params.cedis_keyword,
                    "productos": [],
                    "total_productos_con_stock": 0,
                    "advertencia": f"No se encontró un almacén que coincida con '{params.cedis_keyword}'",
                }, ensure_ascii=False)

            quants = odoo.search_read(
                "stock.quant",
                [
                    ["product_id", "in", product_ids],
                    ["location_id", "child_of", cedis["lot_stock_id"][0]],
                ],
                ["product_id", "location_id", "quantity", "reserved_quantity"],
                limit=0,
            )

            cedis_nombre = cedis["name"]
            productos = []
            for q in quants:
                pid = q["product_id"][0] if q["product_id"] else None
                if not pid:
                    continue
                existencia = float(q["quantity"] or 0)
                reservado = float(q["reserved_quantity"] or 0)
                disponible = max(0.0, existencia - reservado)
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

            product_ids, nombres = _get_product_ids_for_proveedor(odoo, params.proveedor)

            cedis = buscar_almacen(cargar_almacenes(odoo), params.cedis_keyword)
            cedis_nombre = cedis["name"] if cedis else params.cedis_keyword
            stock_cedis: dict[int, float] = {}

            if cedis and cedis.get("lot_stock_id"):
                quants_cedis = odoo.search_read(
                    "stock.quant",
                    [
                        ["product_id", "in", product_ids],
                        ["location_id", "child_of", cedis["lot_stock_id"][0]],
                    ],
                    ["product_id", "quantity"],
                    limit=0,
                )
                for q in quants_cedis:
                    pid = q["product_id"][0] if q["product_id"] else None
                    if pid:
                        stock_cedis[pid] = stock_cedis.get(pid, 0.0) + float(q["quantity"] or 0)
            else:
                logger.warning("No se encontró almacén CEDIS para '%s'", params.cedis_keyword)

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
        name="traspasos_cargar_modulo",
        annotations={
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": True,
        },
    )
    def traspasos_cargar_modulo(params: TraspasosCargarModuloInput) -> str:
        """Carga el plan de traspasos calculado al módulo x_traspasos en Odoo como filas en estado 'borrador'.

        NO crea stock.picking. Las vendedoras podrán ver las filas de su tienda,
        agregar comentarios y ajustar 'cantidad_final'. El generador de pickings
        luego marca cada fila como 'verificado' y ejecuta traspasos_generar_pickings.

        Args:
            params: proveedor, lineas_json (JSON del array 'lineas' de traspasos_calcular_plan),
                    origen_referencia (opcional — etiqueta del lote, ej. 'DONSOL-JUN-2026')

        Returns:
            JSON con schema:
            {
                "creados": int,
                "ids": [int],
                "errores": [str],
                "proveedor": str,
                "origen_referencia": str
            }
        """
        try:
            lineas = json.loads(params.lineas_json)
            if not lineas:
                return json.dumps({
                    "creados": 0,
                    "ids": [],
                    "errores": [],
                    "advertencia": "No hay líneas de traspaso para cargar",
                }, ensure_ascii=False)

            # Etiqueta de la corrida. El valor anterior era constante para todas las
            # corridas del proveedor, así que no servía para distinguirlas al limpiar
            # las filas viejas en Odoo. Solo etiqueta: no cancela ni modifica nada.
            referencia = params.origen_referencia or _referencia_corrida(params.proveedor)
            ids_creados = []
            errores = []

            for linea in lineas:
                try:
                    rec_id = odoo.create("x_traspasos", {
                        "tipo": "por_proveedor",
                        "proveedor": params.proveedor,
                        "product_id": linea["product_id"],
                        "origen": linea["origen"],
                        "destino": linea["destino"],
                        "cantidad_propuesta": linea["cantidad"],
                        "cantidad_final": linea["cantidad"],
                        "comentarios": "",
                        "state": "borrador",
                        "ref_interna": referencia,
                    })
                    ids_creados.append(rec_id)
                except Exception as e_inner:
                    errores.append(f"{linea.get('nombre', linea.get('product_id'))}: {e_inner}")

            logger.info(
                "traspasos_cargar_modulo: %d registros creados en x_traspasos para %s",
                len(ids_creados), params.proveedor,
            )

            return json.dumps({
                "creados": len(ids_creados),
                "ids": ids_creados,
                "errores": errores,
                "proveedor": params.proveedor,
                "origen_referencia": referencia,
            }, ensure_ascii=False)

        except Exception as e:
            return _err(e)

    @mcp.tool(
        name="traspasos_get_estado",
        annotations={
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        },
    )
    def traspasos_get_estado(params: TraspasosGetEstadoInput) -> str:
        """Consulta el estado de las filas en x_traspasos para un proveedor.

        Por defecto muestra solo filas activas (borrador + verificado). Con state='ejecutado'
        o state='cancelado' muestra el historial.

        Args:
            params: proveedor (str), state (str, default='' → borrador+verificado)

        Returns:
            JSON con schema:
            {
                "proveedor": str,
                "state_filtro": str,
                "filas": [
                    {
                        "id": int,
                        "origen": str,
                        "destino": str,
                        "product_id": int,
                        "cantidad_propuesta": float,
                        "cantidad_final": float,
                        "comentarios": str,
                        "state": str
                    }
                ],
                "total": int,
                "resumen_estados": {"borrador": int, "verificado": int, "ejecutado": int, "cancelado": int}
            }
        """
        try:
            domain: list = [["proveedor", "=", params.proveedor]]
            if params.state:
                domain.append(["state", "=", params.state])
            else:
                domain.append(["state", "in", ["borrador", "verificado"]])

            registros = odoo.search_read(
                "x_traspasos",
                domain,
                ["id", "product_id", "origen", "destino", "cantidad_propuesta",
                 "cantidad_final", "comentarios", "state", "picking_id"],
                limit=0,
            )

            filas = [
                {
                    "id": r["id"],
                    "product_id": r["product_id"][0] if isinstance(r.get("product_id"), list) else r.get("product_id"),
                    "nombre": r["product_id"][1] if isinstance(r.get("product_id"), list) else "",
                    "origen": r.get("origen", ""),
                    "destino": r.get("destino", ""),
                    "cantidad_propuesta": r.get("cantidad_propuesta", 0),
                    "cantidad_final": r.get("cantidad_final", 0),
                    "comentarios": r.get("comentarios", ""),
                    "state": r.get("state", ""),
                    "picking_id": r["picking_id"][0] if isinstance(r.get("picking_id"), list) else r.get("picking_id"),
                }
                for r in registros
            ]

            resumen: dict[str, int] = {"borrador": 0, "verificado": 0, "ejecutado": 0, "cancelado": 0}
            for f in filas:
                s = f["state"]
                if s in resumen:
                    resumen[s] += 1

            return json.dumps({
                "proveedor": params.proveedor,
                "state_filtro": params.state or "borrador+verificado",
                "filas": filas,
                "total": len(filas),
                "resumen_estados": resumen,
            }, ensure_ascii=False)

        except Exception as e:
            return _err(e)

    @mcp.tool(
        name="traspasos_generar_pickings",
        annotations={
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": True,
        },
    )
    def traspasos_generar_pickings(params: TraspasosGenerarPickingsInput) -> str:
        """Lee las filas verificadas de x_traspasos y crea los stock.picking en Odoo.

        Por cada combinación origen→destino crea DOS pickings en borrador, vía la
        ubicación de tránsito entre almacenes:

          1. Salida    — tienda origen → tránsito, en Traslados internos del origen.
          2. Recepción — tránsito → tienda destino, en Recepciones del destino.

        Así la tienda que recibe puede validar que la mercancía realmente llegó.
        Cada picking usa el tipo de su propio almacén, no uno global.

        Solo procesa filas con state='verificado'. Usa 'cantidad_final' (no
        cantidad_propuesta). Después las deja en state='ejecutado' con ambos pickings
        vinculados (picking_id = salida, picking_entrada_id = recepción).

        Las vendedoras hacen la salida y la entrada físicamente en Odoo — este tool
        NO valida pickings. Solo debe ejecutarlo el generador de pickings.

        Args:
            params: proveedor (str), origen_referencia (str, opcional)

        Returns:
            JSON con schema:
            {
                "pickings_creados": [
                    {"picking_salida_id": int, "picking_salida": str,
                     "picking_entrada_id": int, "picking_entrada": str,
                     "origen": str, "destino": str, "lineas": int}
                ],
                "filas_ejecutadas": int,
                "errores": [str],
                "total_pickings": int
            }
        """
        try:
            # Leer filas verificadas de x_traspasos
            filas_verificadas = odoo.search_read(
                "x_traspasos",
                [["proveedor", "=", params.proveedor], ["state", "=", "verificado"]],
                ["id", "product_id", "origen", "destino", "cantidad_final"],
                limit=0,
            )

            if not filas_verificadas:
                return json.dumps({
                    "pickings_creados": [],
                    "filas_ejecutadas": 0,
                    "errores": [],
                    "total_pickings": 0,
                    "advertencia": f"No hay filas verificadas para '{params.proveedor}' en x_traspasos",
                }, ensure_ascii=False)

            all_locs = odoo.search_read(
                "stock.location",
                [["usage", "=", "internal"], ["active", "=", True]],
                ["id", "name", "complete_name"],
                limit=0,
            )
            almacenes = cargar_almacenes(odoo)

            # Todos los traspasos pasan por el tránsito entre almacenes de la
            # compañía ("Traslado entre almacenes", id 196), salgan de CEDIS o de
            # una tienda. Confirmado contra la base: es el que usa tienda ↔ tienda.
            # Las otras 17 "Traslado <TIENDA>" son de otro flujo — en 180 días su
            # origen fue CEDIS y nada más. Si algún día los traspasos CEDIS → tienda
            # deben ir por esas, hay que resolver la del destino aquí, emparejando
            # por almacén y no por nombre.
            transito_id = ubicacion_transito(odoo)
            if not transito_id:
                return (
                    "Error: la compañía no tiene configurada su ubicación de tránsito "
                    "entre almacenes (res.company.internal_transit_location_id). "
                    "Sin ella no se pueden crear los pickings de salida y recepción."
                )

            pids_unicos = list({
                r["product_id"][0] if isinstance(r["product_id"], list) else r["product_id"]
                for r in filas_verificadas
            })
            products_data = odoo.search_read(
                "product.product",
                [["id", "in", pids_unicos]],
                ["id", "uom_id"],
                limit=0,
            )
            uom_por_product: dict[int, int] = {
                p["id"]: p["uom_id"][0] for p in products_data if p.get("uom_id")
            }

            # Agrupar por (origen, destino)
            grupos: dict[tuple[str, str], list[dict]] = {}
            for fila in filas_verificadas:
                pid = fila["product_id"][0] if isinstance(fila["product_id"], list) else fila["product_id"]
                key = (fila["origen"], fila["destino"])
                grupos.setdefault(key, []).append({
                    "fila_id": fila["id"],
                    "product_id": pid,
                    "cantidad_final": float(fila.get("cantidad_final") or 0),
                })

            referencia = params.origen_referencia or _referencia_corrida(params.proveedor)
            pickings_creados = []
            errores = []
            ids_ejecutados = []

            def _crear_picking(tipo_id, loc_origen, loc_destino, grupo) -> tuple[int, int]:
                """Crea un picking con sus movimientos. Retorna (picking_id, líneas)."""
                pk_id = odoo.create("stock.picking", {
                    "picking_type_id": tipo_id,
                    "location_id": loc_origen,
                    "location_dest_id": loc_destino,
                    "origin": referencia,
                })
                lineas = 0
                for item in grupo:
                    uom_id = uom_por_product.get(item["product_id"])
                    if not uom_id:
                        continue
                    odoo.create("stock.move", {
                        "picking_id": pk_id,
                        "product_id": item["product_id"],
                        "product_uom_qty": item["cantidad_final"],
                        "product_uom": uom_id,
                        "location_id": loc_origen,
                        "location_dest_id": loc_destino,
                        "name": f"Traspaso {params.proveedor}",
                    })
                    lineas += 1
                return pk_id, lineas

            def _nombre_picking(pk_id: int) -> str:
                datos = odoo.search_read(
                    "stock.picking", [["id", "=", pk_id]], ["name"], limit=1)
                return datos[0]["name"] if datos else str(pk_id)

            for (origen, destino), grupo in grupos.items():
                alm_origen = buscar_almacen(almacenes, origen)
                alm_destino = buscar_almacen(almacenes, destino)

                loc_origen_id = _buscar_location_id(all_locs, almacenes, origen)
                loc_destino_id = _buscar_location_id(all_locs, almacenes, destino)

                if not loc_origen_id:
                    errores.append(f"No se encontró ubicación para origen '{origen}'")
                    continue
                if not loc_destino_id:
                    errores.append(f"No se encontró ubicación para destino '{destino}'")
                    continue

                # Cada picking va en el tipo de SU almacén: la salida en Traslados
                # internos del origen, la recepción en Recepciones del destino.
                tipo_salida = (alm_origen or {}).get("int_type_id")
                tipo_entrada = (alm_destino or {}).get("in_type_id")
                if not tipo_salida:
                    errores.append(f"'{origen}' no tiene tipo de Traslados internos en Odoo")
                    continue
                if not tipo_entrada:
                    errores.append(f"'{destino}' no tiene tipo de Recepciones en Odoo")
                    continue

                sin_uom = [i["product_id"] for i in grupo if not uom_por_product.get(i["product_id"])]
                for pid_sin_uom in sin_uom:
                    errores.append(f"Sin UOM para producto {pid_sin_uom} — línea omitida")

                # Salida: tienda origen → tránsito
                salida_id, lineas_ok = _crear_picking(
                    tipo_salida[0], loc_origen_id, transito_id, grupo)
                # Recepción: tránsito → tienda destino. La valida la tienda que recibe,
                # y así puede confirmar que la mercancía realmente llegó.
                entrada_id, _ = _crear_picking(
                    tipo_entrada[0], transito_id, loc_destino_id, grupo)

                fila_ids_grupo = [item["fila_id"] for item in grupo]
                odoo.write("x_traspasos", fila_ids_grupo, {
                    "state": "ejecutado",
                    "picking_id": salida_id,
                    "picking_entrada_id": entrada_id,
                })
                ids_ejecutados.extend(fila_ids_grupo)

                nombre_salida = _nombre_picking(salida_id)
                nombre_entrada = _nombre_picking(entrada_id)
                pickings_creados.append({
                    "picking_salida_id": salida_id,
                    "picking_salida": nombre_salida,
                    "picking_entrada_id": entrada_id,
                    "picking_entrada": nombre_entrada,
                    "origen": origen,
                    "destino": destino,
                    "lineas": lineas_ok,
                })
                logger.info(
                    "Traspaso %s → %s: salida %s, recepción %s (%d líneas)",
                    origen, destino, nombre_salida, nombre_entrada, lineas_ok,
                )

            return json.dumps({
                "pickings_creados": pickings_creados,
                "filas_ejecutadas": len(ids_ejecutados),
                "errores": errores,
                "total_rutas": len(pickings_creados),
                "total_pickings": len(pickings_creados) * 2,   # salida + recepción
            }, ensure_ascii=False)

        except Exception as e:
            return _err(e)
