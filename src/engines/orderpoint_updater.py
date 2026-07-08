"""Motor de Paso 3 — cálculo de orderpoints para pedido final.

Lógica pura. Sin dependencias de Odoo ni MCP.
"""
from __future__ import annotations

from dataclasses import dataclass

from src.engines.transfer_planner import ResumenPostTraspaso


@dataclass
class RegistroPedido:
    orderpoint_id: int | None
    product_id: int
    nombre: str
    tienda: str
    existencia_antes: float
    existencia_despues: float
    nuevo_maximo: int
    nuevo_minimo: int   # = nuevo_maximo (política SoyAquarius: min == max)
    qty_to_order: int
    rotacion: str
    abc: str


class OrderpointUpdater:
    """Calcula qty_to_order por (tienda, producto) después de los traspasos."""

    def calcular_paso3(
        self,
        resumen: list[ResumenPostTraspaso],
        orderpoints: list[dict],
        cedis_keyword: str = "CEDIS",
    ) -> list[RegistroPedido]:
        """Construye la lista de registros para el pedido final.

        Args:
            resumen: salida de TransferPlanner.calcular_plan (incluye existencia_despues y qty_a_pedir).
            orderpoints: lista de dicts con {product_id, location (tienda), id} — de compras_get_orderpoints.
            cedis_keyword: filas CEDIS se omiten del pedido final.

        Returns:
            Lista de RegistroPedido, una entrada por (tienda, producto), excluido CEDIS.
        """
        # Índice rápido: (product_id, tienda_upper) → orderpoint_id
        op_index: dict[tuple[int, str], int] = {}
        for op in orderpoints:
            pid = op.get("product_id")
            loc = (op.get("location") or op.get("nombre", "")).strip().upper()
            if pid and loc:
                op_index[(pid, loc)] = op["id"]

        resultado: list[RegistroPedido] = []
        for r in resumen:
            if cedis_keyword.upper() in r.tienda.upper():
                continue
            op_id = op_index.get((r.product_id, r.tienda.strip().upper()))
            resultado.append(RegistroPedido(
                orderpoint_id=op_id,
                product_id=r.product_id,
                nombre=r.nombre,
                tienda=r.tienda,
                existencia_antes=r.existencia_antes,
                existencia_despues=r.existencia_despues,
                nuevo_maximo=r.nuevo_maximo,
                nuevo_minimo=r.nuevo_maximo,
                qty_to_order=r.qty_a_pedir,
                rotacion=r.rotacion,
                abc=r.abc,
            ))
        return resultado


if __name__ == "__main__":
    from src.engines.transfer_planner import ResumenPostTraspaso
    r = ResumenPostTraspaso("TIENDA1", 1, "Producto X", "Activo", "A", 10.0, 0.0, 5.0, 15.0, 20, 5)
    updater = OrderpointUpdater()
    registros = updater.calcular_paso3([r], [{"product_id": 1, "location": "TIENDA1", "id": 42}])
    assert len(registros) == 1
    assert registros[0].qty_to_order == 5
    assert registros[0].orderpoint_id == 42
    print("OK")
