"""Tests unitarios para src/engines/purchase_planner.py.

No requieren conexión a Odoo. Prueban las funciones de negocio puras.
Ejecutar con: python -m pytest tests/test_purchase_planner.py -v
"""
import pytest

from src.engines.purchase_planner import (
    PurchasePlanner,
    VentaMes,
    StockQuant,
    clasificar_rotacion,
    clasificar_abc,
    detectar_patron,
    calcular_nuevo_maximo,
)


# ---------------------------------------------------------------------------
# clasificar_rotacion
# ---------------------------------------------------------------------------

class TestClasificarRotacion:
    def test_nunca_entrado_sin_nada(self):
        assert clasificar_rotacion(999, False, False, False) == "Nunca_entrado"

    def test_activo_con_ventas_recientes(self):
        assert clasificar_rotacion(30, True, True, True) == "Activo"

    def test_activo_limite_exacto(self):
        assert clasificar_rotacion(100, True, False, True) == "Activo"

    def test_rezagado_101_dias(self):
        assert clasificar_rotacion(101, True, True, True) == "Rezagado"

    def test_rezagado_limite_exacto(self):
        assert clasificar_rotacion(180, True, False, True) == "Rezagado"

    def test_critico_mas_de_180(self):
        assert clasificar_rotacion(181, True, False, True) == "Critico"

    def test_tiene_existencia_pero_sin_ventas_ni_entradas(self):
        # tiene_existencia=True → no es Nunca_entrado (algo existe en stock)
        # 999 días sin venta > 180 → Critico
        assert clasificar_rotacion(999, False, True, False) == "Critico"

    def test_tiene_entradas_sin_ventas_critico(self):
        assert clasificar_rotacion(200, False, False, True) == "Critico"


# ---------------------------------------------------------------------------
# clasificar_abc
# ---------------------------------------------------------------------------

class TestClasificarAbc:
    def test_vacio(self):
        assert clasificar_abc({}) == {}

    def test_todo_cero(self):
        resultado = clasificar_abc({1: 0.0, 2: 0.0})
        assert all(v == "C" for v in resultado.values())

    def test_un_solo_producto_es_A(self):
        assert clasificar_abc({1: 100.0})[1] == "A"

    def test_pareto_clasico(self):
        # Producto 1 = 80 → 80% acumulado → A
        # Producto 2 = 10 → 90% → B
        # Producto 3 = 10 → 100% → C
        resultado = clasificar_abc({1: 80.0, 2: 10.0, 3: 10.0})
        assert resultado[1] == "A"
        assert resultado[2] == "B"
        assert resultado[3] == "C"

    def test_orden_descendente_aplicado(self):
        # El producto con más ventas debe clasificarse primero como A
        resultado = clasificar_abc({3: 10.0, 1: 80.0, 2: 10.0})
        assert resultado[1] == "A"


# ---------------------------------------------------------------------------
# detectar_patron
# ---------------------------------------------------------------------------

class TestDetectarPatron:
    def test_vacio_retorna_regular(self):
        assert detectar_patron([], "C") == "regular"

    def test_abc_A_siempre_es_80_20(self):
        assert detectar_patron([10.0, 20.0, 5.0], "A") == "80_20"
        assert detectar_patron([0.0, 0.0, 0.0], "A") == "80_20"

    def test_pico_sostenido_mes_actual_alto(self):
        # promedio = (2+2+20)/3 ≈ 8, pico = 20 ≥ 16 ✓, mes_actual = 20 ≥ 12 ✓
        assert detectar_patron([2.0, 2.0, 20.0], "B") == "pico_sostenido"

    def test_pico_aislado_mes_actual_bajo(self):
        # promedio = (20+2+2)/3 ≈ 8, pico = 20 ≥ 16 ✓, mes_actual = 2 < 12 → aislado
        assert detectar_patron([20.0, 2.0, 2.0], "B") == "pico_aislado"

    def test_regular_sin_pico(self):
        assert detectar_patron([5.0, 6.0, 5.5], "B") == "regular"

    def test_promedio_cero_no_crash(self):
        assert detectar_patron([0.0, 0.0, 0.0], "C") == "regular"


# ---------------------------------------------------------------------------
# calcular_nuevo_maximo
# ---------------------------------------------------------------------------

class TestCalcularNuevoMaximo:
    def test_vacio_retorna_cero(self):
        assert calcular_nuevo_maximo([], "regular") == 0

    def test_regular_usa_promedio(self):
        assert calcular_nuevo_maximo([10.0, 12.0, 11.0], "regular") == 11

    def test_80_20_es_doble_promedio(self):
        assert calcular_nuevo_maximo([10.0, 10.0, 10.0], "80_20") == 20

    def test_pico_sostenido_usa_pico(self):
        assert calcular_nuevo_maximo([5.0, 5.0, 20.0], "pico_sostenido") == 20

    def test_pico_aislado_es_promedio_por_1_5(self):
        # promedio = (20+5+5)/3 ≈ 10, resultado = 15
        assert calcular_nuevo_maximo([20.0, 5.0, 5.0], "pico_aislado") == 15

    def test_usa_round_no_ceil(self):
        # promedio = 10.3, round = 10 (ceil daría 11)
        result = calcular_nuevo_maximo([10.0, 10.0, 10.9], "regular")
        assert result == 10

    def test_minimo_uno_si_hay_demanda_leve(self):
        # promedio = 0.5 ≥ 0.33 → resultado debe ser ≥ 1
        assert calcular_nuevo_maximo([0.5, 0.5, 0.5], "regular") >= 1

    def test_cero_si_sin_demanda(self):
        assert calcular_nuevo_maximo([0.0, 0.0, 0.0], "regular") == 0

    def test_demanda_por_debajo_de_threshold(self):
        # promedio ≈ 0.033, round = 0, promedio < 0.33 → retorna 0
        assert calcular_nuevo_maximo([0.1, 0.0, 0.0], "regular") == 0


# ---------------------------------------------------------------------------
# PurchasePlanner.calcular — integración sin Odoo
# ---------------------------------------------------------------------------

class TestPurchasePlanner:

    def test_calcular_producto_activo(self):
        planner = PurchasePlanner()
        ventas = [
            VentaMes(product_id=1, tienda="TIENDA1", mes="2026-01", qty=10.0),
            VentaMes(product_id=1, tienda="TIENDA1", mes="2026-02", qty=12.0),
            VentaMes(product_id=1, tienda="TIENDA1", mes="2026-03", qty=11.0),
            VentaMes(product_id=1, tienda="TIENDA1", mes="2026-04", qty=9.0),
            VentaMes(product_id=1, tienda="TIENDA1", mes="2026-05", qty=10.0),
            VentaMes(product_id=1, tienda="TIENDA1", mes="2026-06", qty=3.0),
        ]
        quants = [StockQuant(product_id=1, tienda="TIENDA1", existencia=5.0)]
        ventas_catalogo = {1: 55.0, 99: 100.0, 98: 20.0}
        productos = {1: "Producto Test"}
        meses = ["2026-01", "2026-02", "2026-03", "2026-04", "2026-05", "2026-06"]

        resultados = planner.calcular(
            proveedor="TEST",
            tienda="TIENDA1",
            ventas_proveedor=ventas,
            ventas_catalogo_anual=ventas_catalogo,
            quants=quants,
            productos=productos,
            meses_disponibles=meses,
        )

        assert len(resultados) == 1
        r = resultados[0]
        assert r.product_id == 1
        assert r.tienda == "TIENDA1"
        assert r.rotacion == "Activo"
        assert r.existencia_actual == 5.0
        assert r.nuevo_maximo == r.nuevo_minimo  # política: min = max
        assert r.nuevo_maximo > 0
        assert r.ventas_3m == [9.0, 10.0, 3.0]  # abr, may, jun (últimos 3)

    def test_calcular_producto_nunca_entrado(self):
        planner = PurchasePlanner()
        resultados = planner.calcular(
            proveedor="TEST",
            tienda="TIENDA1",
            ventas_proveedor=[],
            ventas_catalogo_anual={1: 0.0},
            quants=[],
            productos={1: "Producto Nunca"},
            meses_disponibles=["2026-01", "2026-02", "2026-03"],
        )
        assert len(resultados) == 1
        assert resultados[0].rotacion == "Nunca_entrado"
        assert resultados[0].nuevo_maximo == 0
        assert resultados[0].nuevo_minimo == 0

    def test_min_siempre_igual_a_max(self):
        """Invariante crítico: nuevo_minimo == nuevo_maximo en todos los casos."""
        planner = PurchasePlanner()
        ventas = [VentaMes(product_id=i, tienda="T", mes="2026-01", qty=float(i * 5)) for i in range(1, 6)]
        productos = {i: f"Prod{i}" for i in range(1, 6)}
        ventas_catalogo = {i: float(i * 5) for i in range(1, 6)}
        quants = [StockQuant(product_id=i, tienda="T", existencia=float(i)) for i in range(1, 6)]

        resultados = planner.calcular(
            proveedor="TEST",
            tienda="T",
            ventas_proveedor=ventas,
            ventas_catalogo_anual=ventas_catalogo,
            quants=quants,
            productos=productos,
            meses_disponibles=["2026-01"],
        )

        for r in resultados:
            assert r.nuevo_minimo == r.nuevo_maximo, (
                f"Producto {r.product_id}: min={r.nuevo_minimo} != max={r.nuevo_maximo}"
            )

    def test_abc_usa_catalogo_no_proveedor(self):
        """ABC se calcula desde ventas_catalogo_anual, no desde ventas del proveedor."""
        planner = PurchasePlanner()
        # Producto 1 tiene pocas ventas del proveedor pero domina el catálogo general
        ventas_proveedor = [VentaMes(product_id=1, tienda="T", mes="2026-01", qty=1.0)]
        ventas_catalogo = {1: 1000.0, 2: 10.0, 3: 5.0}
        productos = {1: "Top Seller", 2: "Otro", 3: "Otro2"}

        resultados = planner.calcular(
            proveedor="TEST",
            tienda="T",
            ventas_proveedor=ventas_proveedor,
            ventas_catalogo_anual=ventas_catalogo,
            quants=[],
            productos=productos,
            meses_disponibles=["2026-01"],
        )

        prod1 = next(r for r in resultados if r.product_id == 1)
        assert prod1.abc == "A"      # domina el catálogo → A
        assert prod1.patron == "80_20"  # ABC=A → patrón 80_20

    def test_meses_menos_de_3(self):
        """Con menos de 3 meses disponibles, ventas_3m tiene el mismo largo que meses."""
        planner = PurchasePlanner()
        ventas = [VentaMes(product_id=1, tienda="T", mes="2026-01", qty=5.0)]
        resultados = planner.calcular(
            proveedor="TEST",
            tienda="T",
            ventas_proveedor=ventas,
            ventas_catalogo_anual={1: 5.0},
            quants=[],
            productos={1: "Prod"},
            meses_disponibles=["2026-01"],
        )
        assert len(resultados[0].ventas_3m) == 1
