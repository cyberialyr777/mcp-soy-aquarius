"""Verificación end-to-end de Sprint 1 — corre sin Odoo real."""
import asyncio
import json

from mcp.server.fastmcp import FastMCP
from tests.mock_connector import OdooConnectorMock
from src.tools import generic


def main():
    mcp = FastMCP("soyaquarius_mcp")
    odoo = OdooConnectorMock()
    generic.register(mcp, odoo)

    tools = mcp._tool_manager._tools
    print(f"Tools registrados: {len(tools)}")
    for name in sorted(tools.keys()):
        print(f"  - {name}")

    async def run_all():
        # odoo_search → arsabe_quant
        raw = await tools["odoo_search"].run({
            "params": {"model": "arsabe_quant", "fields": ["product_id", "dias_sin_movimiento"], "domain": [], "limit": 100, "order": ""}
        })
        data = json.loads(raw)
        assert len(data) == 4, f"Esperaba 4 registros arsabe_quant, got {len(data)}"
        critico = data[2]
        print(f"  arsabe_quant[2]: {critico['product_id'][1]} — {critico['dias_sin_movimiento']} dias")

        # odoo_search_count
        raw2 = await tools["odoo_search_count"].run({
            "params": {"model": "stock.quant", "domain": []}
        })
        count_resp = json.loads(raw2)
        assert count_resp["count"] == 4
        print(f"  odoo_search_count stock.quant: {count_resp['count']}")

        # odoo_create
        raw3 = await tools["odoo_create"].run({
            "params": {"model": "stock.warehouse.orderpoint", "values": {"product_id": 1, "product_min_qty": 5, "product_max_qty": 5}}
        })
        create_resp = json.loads(raw3)
        assert create_resp["id"] == 999
        print(f"  odoo_create: nuevo id={create_resp['id']}")

        # odoo_write
        raw4 = await tools["odoo_write"].run({
            "params": {"model": "stock.warehouse.orderpoint", "ids": [101], "values": {"product_max_qty": 20}}
        })
        write_resp = json.loads(raw4)
        assert write_resp["ok"] is True
        print(f"  odoo_write: ok={write_resp['ok']}")

        # Validación Pydantic: model vacío → FastMCP lanza ToolError (nivel protocolo)
        from mcp.server.fastmcp.exceptions import ToolError
        try:
            await tools["odoo_search"].run({
                "params": {"model": "", "fields": ["id"], "domain": []}
            })
            raise AssertionError("Debía lanzar ToolError para model=''")
        except ToolError as e:
            assert "string_too_short" in str(e) or "at least 1 character" in str(e)
            print(f"  odoo_search model='': ToolError correcto (Pydantic bloqueó)")

    asyncio.run(run_all())
    print("\nSprint 1 verificado OK.")


if __name__ == "__main__":
    main()
