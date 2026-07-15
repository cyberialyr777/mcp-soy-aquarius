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
            orderpoints: lista de dicts con {product_id, location, almacen, codigo, id} — de compras_get_orderpoints.
            cedis_keyword: filas CEDIS se omiten del pedido final.

        Returns:
            Lista de RegistroPedido, una entrada por (tienda, producto), excluido CEDIS.
        """
        # Índice rápido: (product_id, alias_upper) → orderpoint_id.
        # Cada orderpoint se indexa bajo la ubicación completa, su prefijo y el
        # nombre del almacén: las tiendas del resumen usan cualquiera de los tres.
        # Si dos orderpoints distintos comparten un alias, la llave se marca None
        # (ambigua): el registro sale sin orderpoint_id en vez de apuntar al equivocado.
        op_index: dict[tuple[int, str], int | None] = {}
        for op in orderpoints:
            pid = op.get("product_id")
            if not pid:
                continue
            llaves = set()
            loc = (op.get("location") or op.get("nombre", "")).strip().upper()
            if loc:
                llaves.add(loc)                        # "GUAYA/EXISTENCIAS"
                llaves.add(loc.split("/")[0].strip())  # "GUAYA", "CHEPAR", "PC"
            alm = (op.get("almacen") or "").strip().upper()
            if alm:
                llaves.add(alm)                        # "GUAYABAL", "PLAZA CRYSTAL"
            cod = (op.get("codigo") or "").strip().upper()
            if cod:
                llaves.add(cod)                        # "CITY" — código corto del almacén
            for k in llaves:
                key = (pid, k)
                if key in op_index and op_index[key] != op["id"]:
                    op_index[key] = None
                else:
                    op_index[key] = op["id"]

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

    # La tienda coincide por nombre de almacén, no por ubicación.
    registros = updater.calcular_paso3(
        [ResumenPostTraspaso("GUAYABAL", 1, "Producto X", "Activo", "A", 10.0, 0.0, 5.0, 15.0, 20, 5)],
        [{"product_id": 1, "location": "GUAYA/Existencias", "almacen": "GUAYABAL", "id": 42}],
    )
    assert registros[0].orderpoint_id == 42

    # ...y por prefijo de ubicación.
    registros = updater.calcular_paso3(
        [ResumenPostTraspaso("CHEPAR", 1, "Producto X", "Activo", "A", 10.0, 0.0, 5.0, 15.0, 20, 5)],
        [{"product_id": 1, "location": "CHEPAR/Existencias", "almacen": "CHEDRAUI PARQUE", "id": 43}],
    )
    assert registros[0].orderpoint_id == 43

    # ...y por código corto del almacén.
    registros = updater.calcular_paso3(
        [ResumenPostTraspaso("CITY", 1, "Producto X", "Activo", "A", 10.0, 0.0, 5.0, 15.0, 20, 5)],
        [{"product_id": 1, "location": "CC/Existencias", "almacen": "CITY CENTER", "codigo": "CITY", "id": 46}],
    )
    assert registros[0].orderpoint_id == 46

    # Alias en colisión (dos ubicaciones "PC/...") → ambiguo, sin orderpoint_id;
    # la ubicación completa sigue resolviendo.
    ops = [
        {"product_id": 1, "location": "PC/Existencias", "almacen": "PLAZA CRYSTAL", "id": 44},
        {"product_id": 1, "location": "PC/Bodega", "almacen": "PC BODEGA", "id": 45},
    ]
    registros = updater.calcular_paso3(
        [ResumenPostTraspaso("PC", 1, "Producto X", "Activo", "A", 10.0, 0.0, 5.0, 15.0, 20, 5)], ops)
    assert registros[0].orderpoint_id is None
    registros = updater.calcular_paso3(
        [ResumenPostTraspaso("PC/Existencias", 1, "Producto X", "Activo", "A", 10.0, 0.0, 5.0, 15.0, 20, 5)], ops)
    assert registros[0].orderpoint_id == 44
    print("OK")
