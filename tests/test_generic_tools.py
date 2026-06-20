"""Tests para src/tools/generic.py usando OdooConnectorMock."""
import json
import pytest

from tests.mock_connector import OdooConnectorMock
from src.tools.schemas import (
    OdooSearchInput,
    OdooReadInput,
    OdooCreateInput,
    OdooWriteInput,
    OdooCallMethodInput,
    OdooGetFieldsInput,
    OdooSearchCountInput,
)


@pytest.fixture
def odoo():
    return OdooConnectorMock()


# ---------------------------------------------------------------------------
# OdooSearchInput — validación Pydantic
# ---------------------------------------------------------------------------

def test_search_input_defaults():
    inp = OdooSearchInput(model="stock.quant", fields=["quantity"])
    assert inp.limit == 100
    assert inp.order == ""
    assert inp.domain == []


def test_search_input_strips_whitespace():
    inp = OdooSearchInput(model="  stock.quant  ", fields=["quantity"])
    assert inp.model == "stock.quant"


def test_search_input_rejects_empty_model():
    with pytest.raises(Exception):
        OdooSearchInput(model="", fields=["quantity"])


def test_search_input_rejects_negative_limit():
    with pytest.raises(Exception):
        OdooSearchInput(model="stock.quant", fields=["quantity"], limit=-1)


def test_search_input_rejects_extra_fields():
    with pytest.raises(Exception):
        OdooSearchInput(model="stock.quant", fields=["quantity"], unknown_field="x")


# ---------------------------------------------------------------------------
# Lógica de tools usando mock (sin FastMCP, llamando directamente al connector)
# ---------------------------------------------------------------------------

def test_search_read_stock_quant(odoo):
    results = odoo.search_read("stock.quant", [], ["product_id", "quantity"])
    assert len(results) == 4
    assert results[0]["quantity"] == 50.0


def test_search_read_arsabe_quant(odoo):
    results = odoo.search_read("arsabe_quant", [], ["product_id", "dias_sin_movimiento"])
    assert len(results) == 4
    # Producto crítico: Chlorella Tienda Norte tiene 200 días sin movimiento
    critico = next(r for r in results if r["location_id"][1] == "Tienda Norte" and r["product_id"][1] == "Chlorella 250g")
    assert critico["dias_sin_movimiento"] == 200


def test_search_read_orderpoints(odoo):
    results = odoo.search_read("stock.warehouse.orderpoint", [], ["id", "product_max_qty"])
    assert len(results) == 2
    assert results[0]["id"] == 101


def test_search_read_limit(odoo):
    results = odoo.search_read("stock.quant", [], ["id"], limit=2)
    assert len(results) == 2


def test_search_read_unknown_model_returns_empty(odoo):
    results = odoo.search_read("modelo.inexistente", [], ["id"])
    assert results == []


def test_create_returns_int(odoo):
    new_id = odoo.create("stock.warehouse.orderpoint", {"product_id": 1, "product_min_qty": 5, "product_max_qty": 5})
    assert isinstance(new_id, int)
    assert new_id > 0


def test_write_returns_true(odoo):
    ok = odoo.write("stock.warehouse.orderpoint", [101], {"product_max_qty": 20})
    assert ok is True


def test_unlink_returns_true(odoo):
    ok = odoo.unlink("stock.warehouse.orderpoint", [101])
    assert ok is True


def test_call_method_returns_true(odoo):
    result = odoo.call_method("stock.picking", "button_validate", [1])
    assert result is True


def test_get_fields_orderpoint(odoo):
    fields = odoo.get_fields("stock.warehouse.orderpoint")
    assert "product_min_qty" in fields
    assert fields["product_min_qty"]["type"] == "float"


def test_search_count(odoo):
    count = odoo.search_count("stock.quant", [])
    assert count == 4


def test_search_count_unknown_model(odoo):
    count = odoo.search_count("modelo.inexistente", [])
    assert count == 0


# ---------------------------------------------------------------------------
# OdooCreateInput y OdooWriteInput — validación Pydantic
# ---------------------------------------------------------------------------

def test_create_input_rejects_empty_model():
    with pytest.raises(Exception):
        OdooCreateInput(model="", values={"a": 1})


def test_write_input_rejects_empty_ids():
    with pytest.raises(Exception):
        OdooWriteInput(model="stock.quant", ids=[], values={"quantity": 5})
