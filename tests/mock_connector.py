"""OdooConnectorMock — datos ficticios para tests sin conexión real a Odoo."""
from typing import Any


class OdooConnectorMock:
    """Reemplaza OdooConnector con datos estáticos para pruebas unitarias.

    Implementa la misma interfaz que OdooConnector para que los engines
    y tools sean testeables sin conexión a Odoo.
    """

    _STOCK_QUANT = [
        {"id": 1, "product_id": (1, "Espirulina 500g"), "location_id": (10, "CEDIS"), "quantity": 50.0, "reserved_quantity": 0.0},
        {"id": 2, "product_id": (1, "Espirulina 500g"), "location_id": (11, "Tienda Norte"), "quantity": 5.0, "reserved_quantity": 1.0},
        {"id": 3, "product_id": (2, "Chlorella 250g"), "location_id": (11, "Tienda Norte"), "quantity": 0.0, "reserved_quantity": 0.0},
        {"id": 4, "product_id": (2, "Chlorella 250g"), "location_id": (12, "Tienda Sur"), "quantity": 20.0, "reserved_quantity": 0.0},
    ]

    _ARSABE_QUANT = [
        {
            "id": 1,
            "product_id": (1, "Espirulina 500g"),
            "location_id": (10, "CEDIS"),
            "quantity": 50.0,
            "reserved_quantity": 0.0,
            "ultima_entrada": "2026-05-10",
            "ultima_salida": "2026-05-20",
            "dias_sin_movimiento": 18,
        },
        {
            "id": 2,
            "product_id": (1, "Espirulina 500g"),
            "location_id": (11, "Tienda Norte"),
            "quantity": 5.0,
            "reserved_quantity": 1.0,
            "ultima_entrada": "2026-04-01",
            "ultima_salida": "2026-05-30",
            "dias_sin_movimiento": 8,
        },
        {
            "id": 3,
            "product_id": (2, "Chlorella 250g"),
            "location_id": (11, "Tienda Norte"),
            "quantity": 0.0,
            "reserved_quantity": 0.0,
            "ultima_entrada": "2025-11-01",
            "ultima_salida": "2025-11-15",
            "dias_sin_movimiento": 200,
        },
        {
            "id": 4,
            "product_id": (2, "Chlorella 250g"),
            "location_id": (12, "Tienda Sur"),
            "quantity": 20.0,
            "reserved_quantity": 0.0,
            "ultima_entrada": "2026-03-01",
            "ultima_salida": "2026-05-01",
            "dias_sin_movimiento": 37,
        },
    ]

    _ORDERPOINTS = [
        {
            "id": 101,
            "product_id": (1, "Espirulina 500g"),
            "location_id": (11, "Tienda Norte"),
            "route_id": (1, "Reabastecimiento"),
            "product_min_qty": 10.0,
            "product_max_qty": 10.0,
            "qty_to_order": 5.0,
            "qty_on_hand": 5.0,
        },
        {
            "id": 102,
            "product_id": (2, "Chlorella 250g"),
            "location_id": (11, "Tienda Norte"),
            "route_id": (1, "Reabastecimiento"),
            "product_min_qty": 8.0,
            "product_max_qty": 8.0,
            "qty_to_order": 8.0,
            "qty_on_hand": 0.0,
        },
    ]

    _POS_ORDER_LINES = [
        {"product_id": (1, "Espirulina 500g"), "qty": 10.0, "price_unit": 50.0, "price_subtotal": 500.0, "order_id": (200, "POS/001")},
        {"product_id": (1, "Espirulina 500g"), "qty": 12.0, "price_unit": 50.0, "price_subtotal": 600.0, "order_id": (201, "POS/002")},
        {"product_id": (1, "Espirulina 500g"), "qty": 8.0,  "price_unit": 50.0, "price_subtotal": 400.0, "order_id": (203, "POS/004")},
        {"product_id": (2, "Chlorella 250g"),  "qty": 3.0,  "price_unit": 30.0, "price_subtotal": 90.0,  "order_id": (202, "POS/003")},
    ]

    def authenticate(self) -> int:
        return 1

    def search_read(self, model: str, domain: list, fields: list, **kwargs: Any) -> list:
        data_map = {
            "stock.quant": self._STOCK_QUANT,
            "arsabe_quant": self._ARSABE_QUANT,
            "stock.warehouse.orderpoint": self._ORDERPOINTS,
            "pos.order.line": self._POS_ORDER_LINES,
        }
        rows = data_map.get(model, [])
        limit = kwargs.get("limit", 0)
        if limit and limit > 0:
            rows = rows[:limit]
        return rows

    def search(self, model: str, domain: list, **kwargs: Any) -> list[int]:
        rows = self.search_read(model, domain, ["id"], **kwargs)
        return [r["id"] for r in rows if "id" in r]

    def read(self, model: str, ids: list, fields: list) -> list:
        return []

    def create(self, model: str, values: dict) -> int:
        return 999

    def write(self, model: str, ids: list, values: dict) -> bool:
        return True

    def unlink(self, model: str, ids: list) -> bool:
        return True

    def call_method(self, model: str, method: str, ids: list, *args: Any) -> Any:
        return True

    def get_fields(self, model: str, attributes: list | None = None) -> dict:
        if model == "stock.warehouse.orderpoint":
            return {
                "product_id": {"string": "Producto", "type": "many2one", "required": True, "readonly": False},
                "product_min_qty": {"string": "Cantidad mínima", "type": "float", "required": True, "readonly": False},
                "product_max_qty": {"string": "Cantidad máxima", "type": "float", "required": True, "readonly": False},
                "qty_to_order": {"string": "Cantidad a pedir", "type": "float", "required": False, "readonly": True},
            }
        return {}

    def search_count(self, model: str, domain: list) -> int:
        return len(self.search_read(model, domain, ["id"]))
