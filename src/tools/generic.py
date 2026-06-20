import json

from mcp.server.fastmcp import FastMCP

from src.odoo.connector import OdooConnector, OdooConnectionError
from src.tools.schemas import (
    OdooSearchInput,
    OdooReadInput,
    OdooCreateInput,
    OdooWriteInput,
    OdooCallMethodInput,
    OdooGetFieldsInput,
    OdooSearchCountInput,
)


def _err(e: Exception) -> str:
    if isinstance(e, OdooConnectionError):
        return f"Error Odoo: {e}"
    return f"Error inesperado ({type(e).__name__}): {e}"


def register(mcp: FastMCP, odoo: OdooConnector) -> None:

    @mcp.tool(
        name="odoo_search",
        annotations={
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        },
    )
    def odoo_search(params: OdooSearchInput) -> str:
        """Busca y lee registros en cualquier modelo de Odoo.

        Útil para consultar stock, ventas, orderpoints, productos, proveedores, etc.
        Para `arsabe_quant` usar model='arsabe_quant' (incluye ultima_entrada, ultima_salida, dias_sin_movimiento).

        Args:
            params: model, domain, fields, limit (default 100), order (opcional)

        Returns:
            JSON string con lista de registros. Cada registro tiene los campos solicitados.
            Ejemplo: [{"id": 1, "product_id": [42, "Espirulina"], "quantity": 15.0}]
            En caso de error retorna: "Error Odoo: <mensaje>"
        """
        try:
            result = odoo.search_read(
                params.model,
                params.domain,
                params.fields,
                limit=params.limit,
                order=params.order,
            )
            return json.dumps(result, ensure_ascii=False, default=str)
        except Exception as e:
            return _err(e)

    @mcp.tool(
        name="odoo_read",
        annotations={
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        },
    )
    def odoo_read(params: OdooReadInput) -> str:
        """Lee registros por IDs en cualquier modelo de Odoo.

        Usar cuando ya se conocen los IDs. Para búsqueda por criterios usar odoo_search.

        Args:
            params: model, ids (lista de enteros), fields

        Returns:
            JSON string con lista de registros.
            En caso de error retorna: "Error Odoo: <mensaje>"
        """
        try:
            result = odoo.read(params.model, params.ids, params.fields)
            return json.dumps(result, ensure_ascii=False, default=str)
        except Exception as e:
            return _err(e)

    @mcp.tool(
        name="odoo_create",
        annotations={
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": True,
        },
    )
    def odoo_create(params: OdooCreateInput) -> str:
        """Crea un registro en Odoo y retorna el nuevo ID.

        Args:
            params: model, values (dict con campos y valores)

        Returns:
            JSON string: {"id": <nuevo_id>}
            En caso de error retorna: "Error Odoo: <mensaje>"
        """
        try:
            new_id = odoo.create(params.model, params.values)
            return json.dumps({"id": new_id})
        except Exception as e:
            return _err(e)

    @mcp.tool(
        name="odoo_write",
        annotations={
            "readOnlyHint": False,
            "destructiveHint": True,
            "idempotentHint": False,
            "openWorldHint": True,
        },
    )
    def odoo_write(params: OdooWriteInput) -> str:
        """Actualiza registros existentes en Odoo.

        Args:
            params: model, ids (lista de IDs), values (dict con campos a modificar)

        Returns:
            JSON string: {"ok": true} si exitoso.
            En caso de error retorna: "Error Odoo: <mensaje>"
        """
        try:
            odoo.write(params.model, params.ids, params.values)
            return json.dumps({"ok": True})
        except Exception as e:
            return _err(e)

    @mcp.tool(
        name="odoo_call_method",
        annotations={
            "readOnlyHint": False,
            "destructiveHint": True,
            "idempotentHint": False,
            "openWorldHint": True,
        },
    )
    def odoo_call_method(params: OdooCallMethodInput) -> str:
        """Ejecuta un método de negocio sobre registros de Odoo.

        Usar para: action_confirm (confirmar pedidos), button_validate (validar picking), etc.

        Args:
            params: model, method (nombre del método), ids (lista de IDs)

        Returns:
            JSON string con el resultado del método (varía por método).
            En caso de error retorna: "Error Odoo: <mensaje>"
        """
        try:
            result = odoo.call_method(params.model, params.method, params.ids)
            return json.dumps(result, ensure_ascii=False, default=str)
        except Exception as e:
            return _err(e)

    @mcp.tool(
        name="odoo_get_fields",
        annotations={
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        },
    )
    def odoo_get_fields(params: OdooGetFieldsInput) -> str:
        """Retorna la definición de campos de un modelo Odoo.

        Útil para descubrir qué campos existen antes de hacer odoo_search.

        Args:
            params: model (ej. 'stock.warehouse.orderpoint')

        Returns:
            JSON string: dict de campo → {string, type, required, readonly}
            En caso de error retorna: "Error Odoo: <mensaje>"
        """
        try:
            result = odoo.get_fields(
                params.model,
                attributes=["string", "type", "required", "readonly"],
            )
            return json.dumps(result, ensure_ascii=False, default=str)
        except Exception as e:
            return _err(e)

    @mcp.tool(
        name="odoo_search_count",
        annotations={
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        },
    )
    def odoo_search_count(params: OdooSearchCountInput) -> str:
        """Cuenta registros que cumplan el dominio sin traer datos.

        Más eficiente que odoo_search cuando solo se necesita saber cuántos hay.

        Args:
            params: model, domain

        Returns:
            JSON string: {"count": <número>}
            En caso de error retorna: "Error Odoo: <mensaje>"
        """
        try:
            count = odoo.search_count(params.model, params.domain)
            return json.dumps({"count": count})
        except Exception as e:
            return _err(e)
