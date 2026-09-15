"""Tests para TransferPlanner — reglas del Paso 2.

El self-check ejecutable del motor (`python src/engines/transfer_planner.py`) cubre
el plan completo; aquí quedan las reglas que más fácil se rompen al tocar el motor.
"""
from src.engines.purchase_planner import ProductoSugerido
from src.engines.transfer_planner import (
    TransferPlanner,
    _activa_puede_enviar,
    _floor_fuente,
    _ventas_2m,
)


def prod(tienda, existencia, maximo, rotacion="Activo", ventas=None,
         dias_sin_venta=0, dias_en_tienda=None, stockout=False, tasa=0.0):
    return ProductoSugerido(
        product_id=1, nombre="P1", tienda=tienda, rotacion=rotacion, abc="B",
        patron="regular", ventas_3m=ventas if ventas is not None else [0.0, 0.0, 0.0],
        existencia_actual=existencia, nuevo_maximo=maximo, nuevo_minimo=maximo,
        dias_sin_venta=dias_sin_venta, dias_en_tienda=dias_en_tienda,
        stockout=stockout, tasa_efectiva=tasa,
    )


class TestVentas2M:
    def test_toma_los_dos_meses_mas_recientes(self):
        """Los meses del periodo son cerrados: no se descarta el último."""
        assert _ventas_2m(prod("T", 0, 0, ventas=[10.0, 20.0, 30.0])) == 50.0

    def test_menos_de_tres_meses(self):
        assert _ventas_2m(prod("T", 0, 0, ventas=[5.0, 7.0])) == 12.0
        assert _ventas_2m(prod("T", 0, 0, ventas=[])) == 0.0

    def test_agotado_usa_la_tasa_efectiva(self):
        """Sin esto el tope dejaría sin resurtir al producto que se acabó vendiendo."""
        agotado = prod("T", 0, 5, ventas=[4.0, 0.0, 0.0], stockout=True, tasa=8.0)
        assert _ventas_2m(agotado) == 16.0


class TestFloorFuente:
    def test_rezagada_vieja_puede_quedar_en_cero(self):
        assert _floor_fuente(prod("T", 5, 0, "Rezagado", dias_en_tienda=200), "CEDIS") == 0.0

    def test_rezagada_reciente_conserva_una_pieza(self):
        assert _floor_fuente(prod("T", 5, 0, "Rezagado", dias_en_tienda=10), "CEDIS") == 1.0

    def test_sin_fecha_de_entrada_conserva_una_pieza(self):
        assert _floor_fuente(prod("T", 5, 0, "Critico", dias_en_tienda=None), "CEDIS") == 1.0

    def test_cedis_siempre_puede_vaciarse(self):
        assert _floor_fuente(prod("CEDIS", 5, 0), "CEDIS") == 0.0

    def test_activa_no_baja_de_su_maximo(self):
        assert _floor_fuente(prod("T", 9, 4), "CEDIS") == 4.0


class TestExcedenteActivo:
    def test_no_envia_si_vende_y_le_sobra_poco(self):
        assert not _activa_puede_enviar(prod("T", 0, 0, dias_sin_venta=10), 2)

    def test_envia_si_el_excedente_es_grande(self):
        assert _activa_puede_enviar(prod("T", 0, 0, dias_sin_venta=10), 3)

    def test_envia_si_lleva_tiempo_sin_vender(self):
        assert _activa_puede_enviar(prod("T", 0, 0, dias_sin_venta=40), 1)


class TestPlan:
    def test_piso_de_eficiencia_se_salta_por_origen_critico(self):
        """El manual pone la excepción en el origen, no en el destino."""
        lineas, _ = TransferPlanner().calcular_plan({
            "ORIGEN": [prod("ORIGEN", 2, 0, "Critico", dias_en_tienda=300)],
            "DESTINO": [prod("DESTINO", 0, 5, ventas=[10.0, 10.0, 10.0])],
        })
        assert [l.cantidad for l in lineas] == [2]

    def test_piso_bloquea_movimientos_chicos_entre_tiendas_sanas(self):
        lineas, _ = TransferPlanner().calcular_plan({
            "ORIGEN": [prod("ORIGEN", 7, 5, dias_sin_venta=40, ventas=[3.0, 3.0, 3.0])],
            "DESTINO": [prod("DESTINO", 4, 5, ventas=[2.0, 2.0, 2.0])],
        })
        assert lineas == []

    def test_cedis_es_la_primera_fuente(self):
        lineas, _ = TransferPlanner().calcular_plan({
            "CEDIS": [prod("CEDIS", 10, 0)],
            "REZAGADA": [prod("REZAGADA", 10, 0, "Rezagado", dias_en_tienda=300)],
            "DESTINO": [prod("DESTINO", 0, 6, ventas=[8.0, 8.0, 8.0])],
        })
        assert lineas[0].origen == "CEDIS"

    def test_tiendas_excluidas_nunca_reciben(self):
        lineas, _ = TransferPlanner().calcular_plan({
            "CEDIS": [prod("CEDIS", 10, 0)],
            "WACO": [prod("WACO", 0, 5, ventas=[5.0, 5.0, 5.0])],
        })
        assert lineas == []

    def test_el_resumen_cuadra_con_las_lineas(self):
        lineas, resumen = TransferPlanner().calcular_plan({
            "CEDIS": [prod("CEDIS", 10, 0)],
            "DESTINO": [prod("DESTINO", 0, 4, ventas=[6.0, 6.0, 6.0])],
        })
        movido = sum(l.cantidad for l in lineas)
        por_tienda = {r.tienda: r for r in resumen}
        assert movido > 0
        assert por_tienda["CEDIS"].enviado == movido
        assert por_tienda["DESTINO"].recibido == movido
        assert por_tienda["DESTINO"].existencia_despues == movido
