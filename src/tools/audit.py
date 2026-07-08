"""Tools MCP de auditoría y validación — Sprint 4.

Dos tools:
  audit_registrar_accion    — registra una acción en la bitácora JSONL
  validation_validar_corrida — valida consistencia entre traspasos y pedido final
"""
import json
import logging

from mcp.server.fastmcp import FastMCP

from src.audit.logger import AuditLogger
from src.engines.orderpoint_updater import RegistroPedido
from src.engines.transfer_planner import TraspasoLinea
from src.engines.validation_engine import ValidationEngine
from src.odoo.connector import OdooConnector
from src.tools.schemas import AuditRegistrarAccionInput, ValidationValidarCorridaInput

logger = logging.getLogger(__name__)

_audit = AuditLogger()
_validator = ValidationEngine()


def register(mcp: FastMCP, odoo: OdooConnector) -> None:

    @mcp.tool(
        name="audit_registrar_accion",
        annotations={
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": False,
        },
    )
    def audit_registrar_accion(params: AuditRegistrarAccionInput) -> str:
        """Registra una acción en la bitácora JSONL de la corrida.

        Cada entrada queda guardada en OUTPUT_DIR/audit_logs/audit_YYYY-MM-DD.jsonl.

        Args:
            params: usuario, accion, proveedor (opcional), resultados_json (opcional),
                    archivos_generados (lista de rutas, opcional)

        Returns:
            JSON de la entrada registrada, o "Error: ..." si falló la escritura.
        """
        try:
            resultados = json.loads(params.resultados_json) if params.resultados_json else {}
            entrada = _audit.registrar(
                usuario=params.usuario,
                accion=params.accion,
                proveedor=params.proveedor,
                resultados=resultados,
                archivos_generados=params.archivos_generados,
            )
            return json.dumps(entrada, ensure_ascii=False, default=str)
        except Exception as e:
            return f"Error inesperado ({type(e).__name__}): {e}"

    @mcp.tool(
        name="validation_validar_corrida",
        annotations={
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    )
    def validation_validar_corrida(params: ValidationValidarCorridaInput) -> str:
        """Valida la consistencia entre el plan de traspasos y el pedido final calculado.

        Checks:
          - qty_to_order >= 0 en todos los registros de Paso 3.
          - Advertencia si hay productos con qty_to_order > 0 pero sin orderpoint_id.

        Args:
            params: paso3_json (campo 'registros' de pedidos_crear_registros),
                    lineas_json (campo 'lineas' de traspasos_calcular_plan)

        Returns:
            JSON con schema:
            {
                "ok": bool,
                "errores": [str],
                "advertencias": [str]
            }
        """
        try:
            paso3_raw = json.loads(params.paso3_json)
            lineas_raw = json.loads(params.lineas_json)

            paso3 = [
                RegistroPedido(
                    orderpoint_id=r.get("orderpoint_id"),
                    product_id=r["product_id"],
                    nombre=r.get("nombre", ""),
                    tienda=r.get("tienda", ""),
                    existencia_antes=r.get("existencia_antes", 0),
                    existencia_despues=r.get("existencia_despues", 0),
                    nuevo_maximo=r.get("nuevo_maximo", 0),
                    nuevo_minimo=r.get("nuevo_maximo", 0),
                    qty_to_order=r.get("qty_to_order", 0),
                    rotacion=r.get("rotacion", ""),
                    abc=r.get("abc", ""),
                )
                for r in paso3_raw
            ]

            lineas = [
                TraspasoLinea(
                    product_id=l["product_id"],
                    nombre=l.get("nombre", ""),
                    origen=l.get("origen", ""),
                    destino=l.get("destino", ""),
                    cantidad=l.get("cantidad", 0),
                    tipo_origen=l.get("tipo_origen", ""),
                )
                for l in lineas_raw
            ]

            resultado = _validator.validar_corrida(paso3, lineas)

            return json.dumps({
                "ok": resultado.ok,
                "errores": resultado.errores,
                "advertencias": resultado.advertencias,
            }, ensure_ascii=False)

        except Exception as e:
            return f"Error inesperado ({type(e).__name__}): {e}"
