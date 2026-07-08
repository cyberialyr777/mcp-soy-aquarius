"""Tools MCP de generación de Excels — Sprint 4.

Cuatro tools:
  reportes_generar_excel_paso1  — Excel de stock sugerido (Paso 1)
  reportes_generar_excel_paso2  — Excel de plan de traspasos (Paso 2)
  reportes_generar_excel_paso3  — Excel de orderpoints actualizados (Paso 3, importable en Odoo)
  reportes_generar_costeo       — Excel de costeo con qty × precio compra (Paso 4)
"""
import json
import logging
from datetime import datetime
from pathlib import Path

import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment
from mcp.server.fastmcp import FastMCP

from src.config.settings import settings
from src.odoo.connector import OdooConnector, OdooConnectionError
from src.tools.compras import _get_product_ids_for_proveedor
from src.tools.schemas import ReportesExcelInput

logger = logging.getLogger(__name__)

_HEADER_FILL = PatternFill("solid", fgColor="1F4E79")
_HEADER_FONT = Font(color="FFFFFF", bold=True)
_HEADER_ALIGN = Alignment(horizontal="center")


def _err(e: Exception) -> str:
    if isinstance(e, OdooConnectionError):
        return f"Error Odoo: {e}"
    return f"Error inesperado ({type(e).__name__}): {e}"


def _output_path(proveedor: str, sufijo: str) -> Path:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    nombre = f"{proveedor.upper().replace(' ', '_')}_{sufijo}_{ts}.xlsx"
    return Path(settings.OUTPUT_DIR) / nombre


def _write_header(ws, columnas: list[str]) -> None:
    for col_idx, col_name in enumerate(columnas, start=1):
        cell = ws.cell(row=1, column=col_idx, value=col_name)
        cell.font = _HEADER_FONT
        cell.fill = _HEADER_FILL
        cell.alignment = _HEADER_ALIGN


def register(mcp: FastMCP, odoo: OdooConnector) -> None:

    @mcp.tool(
        name="reportes_generar_excel_paso1",
        annotations={
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": False,
        },
    )
    def reportes_generar_excel_paso1(params: ReportesExcelInput) -> str:
        """Genera un Excel auditable con el stock sugerido (Paso 1).

        Args:
            params: proveedor, datos_json (JSON de la salida de compras_calcular_stock_sugerido)

        Returns:
            Ruta absoluta del archivo generado, o "Error: ...".
        """
        try:
            datos = json.loads(params.datos_json)
            wb = openpyxl.Workbook()
            ws = wb.active
            ws.title = "Paso1_StockSugerido"

            columnas = [
                "Tienda", "Producto", "Rotación", "ABC", "Patrón",
                "Vta M-2", "Vta M-1", "Vta Mes", "Stock Actual",
                "Nuevo Máximo", "Nuevo Mínimo",
            ]
            _write_header(ws, columnas)

            row = 2
            for tienda_data in datos.get("tiendas", []):
                tienda = tienda_data.get("tienda", "")
                for p in tienda_data.get("productos", []):
                    ventas = p.get("ventas_3m", [0, 0, 0])
                    ws.append([
                        tienda,
                        p.get("nombre", ""),
                        p.get("rotacion", ""),
                        p.get("abc", ""),
                        p.get("patron", ""),
                        ventas[0] if len(ventas) > 0 else 0,
                        ventas[1] if len(ventas) > 1 else 0,
                        ventas[2] if len(ventas) > 2 else 0,
                        p.get("existencia_actual", 0),
                        p.get("nuevo_maximo", 0),
                        p.get("nuevo_minimo", 0),
                    ])
                    row += 1

            ruta = _output_path(params.proveedor, "PASO1")
            wb.save(ruta)
            logger.info("Excel Paso 1 generado: %s", ruta)
            return str(ruta)

        except Exception as e:
            return _err(e)

    @mcp.tool(
        name="reportes_generar_excel_paso2",
        annotations={
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": False,
        },
    )
    def reportes_generar_excel_paso2(params: ReportesExcelInput) -> str:
        """Genera un Excel auditable con el plan de traspasos (Paso 2).

        Args:
            params: proveedor, datos_json (JSON de la salida de traspasos_calcular_plan)

        Returns:
            Ruta absoluta del archivo generado, o "Error: ...".
        """
        try:
            datos = json.loads(params.datos_json)
            wb = openpyxl.Workbook()

            # Hoja de líneas de traspaso
            ws1 = wb.active
            ws1.title = "Lineas_Traspaso"
            _write_header(ws1, ["Origen", "Destino", "Producto", "Cantidad", "Tipo Origen"])
            for linea in datos.get("lineas", []):
                ws1.append([
                    linea.get("origen", ""),
                    linea.get("destino", ""),
                    linea.get("nombre", ""),
                    linea.get("cantidad", 0),
                    linea.get("tipo_origen", ""),
                ])

            # Hoja de resumen por tienda
            ws2 = wb.create_sheet("Resumen_Tiendas")
            _write_header(ws2, [
                "Tienda", "Producto", "Rotación", "ABC",
                "Stock Antes", "Enviado", "Recibido", "Stock Después",
                "Nuevo Máximo", "Qty a Pedir",
            ])
            for r in datos.get("resumen", []):
                ws2.append([
                    r.get("tienda", ""),
                    r.get("nombre", ""),
                    r.get("rotacion", ""),
                    r.get("abc", ""),
                    r.get("existencia_antes", 0),
                    r.get("enviado", 0),
                    r.get("recibido", 0),
                    r.get("existencia_despues", 0),
                    r.get("nuevo_maximo", 0),
                    r.get("qty_a_pedir", 0),
                ])

            ruta = _output_path(params.proveedor, "PASO2")
            wb.save(ruta)
            logger.info("Excel Paso 2 generado: %s", ruta)
            return str(ruta)

        except Exception as e:
            return _err(e)

    @mcp.tool(
        name="reportes_generar_excel_paso3",
        annotations={
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": False,
        },
    )
    def reportes_generar_excel_paso3(params: ReportesExcelInput) -> str:
        """Genera un Excel con los orderpoints actualizados (Paso 3), importable en Odoo.

        Incluye hoja 'Importar_Odoo' con columnas id/product_min_qty/product_max_qty/qty_to_order
        y hoja 'Detalle' con información completa para revisión.

        Args:
            params: proveedor, datos_json (JSON de registros — lista de RegistroPedido serializado,
                    campo 'registros' de la salida de pedidos_crear_registros)

        Returns:
            Ruta absoluta del archivo generado, o "Error: ...".
        """
        try:
            datos = json.loads(params.datos_json)
            registros = datos if isinstance(datos, list) else datos.get("registros", [])

            wb = openpyxl.Workbook()

            # Hoja importable en Odoo
            ws1 = wb.active
            ws1.title = "Importar_Odoo"
            _write_header(ws1, ["id", "product_min_qty", "product_max_qty", "qty_to_order"])
            for r in registros:
                op_id = r.get("orderpoint_id")
                if op_id:
                    ws1.append([op_id, r.get("nuevo_maximo", 0), r.get("nuevo_maximo", 0), r.get("qty_to_order", 0)])

            # Hoja detalle
            ws2 = wb.create_sheet("Detalle")
            _write_header(ws2, [
                "Tienda", "Producto", "Rotación", "ABC",
                "Stock Antes", "Stock Después", "Nuevo Máximo", "Qty a Pedir",
                "Orderpoint ID",
            ])
            for r in registros:
                ws2.append([
                    r.get("tienda", ""),
                    r.get("nombre", ""),
                    r.get("rotacion", ""),
                    r.get("abc", ""),
                    r.get("existencia_antes", 0),
                    r.get("existencia_despues", 0),
                    r.get("nuevo_maximo", 0),
                    r.get("qty_to_order", 0),
                    r.get("orderpoint_id"),
                ])

            ruta = _output_path(params.proveedor, "PASO3")
            wb.save(ruta)
            logger.info("Excel Paso 3 generado: %s", ruta)
            return str(ruta)

        except Exception as e:
            return _err(e)

    @mcp.tool(
        name="reportes_generar_costeo",
        annotations={
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": True,
        },
    )
    def reportes_generar_costeo(params: ReportesExcelInput) -> str:
        """Genera un Excel de costeo (Paso 4) con qty_to_order × precio de compra.

        Consulta product.supplierinfo para obtener los precios de compra del proveedor.

        Args:
            params: proveedor, datos_json (mismo JSON que reportes_generar_excel_paso3)

        Returns:
            Ruta absoluta del archivo generado, o "Error: ...".
        """
        try:
            datos = json.loads(params.datos_json)
            registros = datos if isinstance(datos, list) else datos.get("registros", [])

            # Obtener precios de compra del proveedor
            pids = [r["product_id"] for r in registros if r.get("product_id")]
            precios_raw = odoo.search_read(
                "product.supplierinfo",
                [
                    ["partner_id.name", "ilike", params.proveedor],
                    ["product_id", "in", pids],
                ],
                ["product_id", "price", "min_qty"],
                limit=0,
            )
            precio_por_pid: dict[int, float] = {}
            for si in precios_raw:
                pid = si["product_id"][0] if isinstance(si.get("product_id"), list) else si.get("product_id")
                if pid and pid not in precio_por_pid:
                    precio_por_pid[pid] = float(si.get("price") or 0)

            wb = openpyxl.Workbook()
            ws = wb.active
            ws.title = "Costeo"

            columnas = [
                "Tienda", "Producto", "Rotación", "ABC",
                "Qty a Pedir", "Precio Compra", "Subtotal",
                "Stock Antes", "Stock Después", "Nuevo Máximo",
            ]
            _write_header(ws, columnas)

            total_piezas = 0
            total_costo = 0.0

            for r in registros:
                pid = r.get("product_id")
                qty = r.get("qty_to_order", 0)
                precio = precio_por_pid.get(pid, 0.0)
                subtotal = qty * precio
                total_piezas += qty
                total_costo += subtotal
                ws.append([
                    r.get("tienda", ""),
                    r.get("nombre", ""),
                    r.get("rotacion", ""),
                    r.get("abc", ""),
                    qty,
                    precio,
                    subtotal,
                    r.get("existencia_antes", 0),
                    r.get("existencia_despues", 0),
                    r.get("nuevo_maximo", 0),
                ])

            # Fila de totales
            last_row = ws.max_row + 1
            ws.cell(row=last_row, column=1, value="TOTAL")
            ws.cell(row=last_row, column=5, value=total_piezas)
            ws.cell(row=last_row, column=7, value=total_costo)
            for col in [1, 5, 7]:
                ws.cell(row=last_row, column=col).font = Font(bold=True)

            ruta = _output_path(params.proveedor, "COSTEO")
            wb.save(ruta)
            logger.info("Excel Costeo generado: %s (%d piezas, $%.2f)", ruta, total_piezas, total_costo)
            return str(ruta)

        except Exception as e:
            return _err(e)
