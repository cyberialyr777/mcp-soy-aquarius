"""Tests for OdooConnectorMock — no real Odoo connection needed."""
import pytest
from tests.mock_connector import OdooConnectorMock


def test_authenticate_returns_uid():
    odoo = OdooConnectorMock()
    assert odoo.authenticate() == 1


def test_search_read_stock_quant():
    odoo = OdooConnectorMock()
    results = odoo.search_read("stock.quant", [], ["product_id", "quantity"])
    assert len(results) == 4
    assert results[0]["quantity"] == 50.0


def test_search_read_orderpoints():
    odoo = OdooConnectorMock()
    results = odoo.search_read("stock.warehouse.orderpoint", [], ["id", "product_max_qty"])
    assert len(results) == 2
    assert results[0]["id"] == 101


def test_create_returns_id():
    odoo = OdooConnectorMock()
    new_id = odoo.create("stock.warehouse.orderpoint", {"product_id": 1, "product_min_qty": 5, "product_max_qty": 5})
    assert isinstance(new_id, int)


def test_write_returns_true():
    odoo = OdooConnectorMock()
    assert odoo.write("stock.warehouse.orderpoint", [101], {"product_max_qty": 20}) is True
