"""Motor de Paso 3 — cálculo de orderpoints para pedido final.

Lógica pura. Sin dependencias de Odoo ni MCP.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from src.engines.transfer_planner import ResumenPostTraspaso

# Estados de picking que significan "esta mercancía ya no se va a mover más":
# 'done' porque ya se movió (el stock.quant ya lo refleja) y 'cancel' porque no
# va a pasar. Cualquier otro estado es un movimiento todavía pendiente.
PICKING_CERRADO = ("done", "cancel")


@dataclass
class TraspasoConfirmado:
    """Una fila de x_traspasos con el estado real de sus dos pickings.

    `salida` mueve la mercancía de la tienda origen al tránsito; `entrada` la lleva
    del tránsito a la tienda destino. Cadena vacía = todavía no existe el picking.
    """
    product_id: int
    origen: str
    destino: str
    cantidad: float
    estado_salida: str = ""
    estado_entrada: str = ""


def movimientos_pendientes(
    traspasos: list[TraspasoConfirmado],
) -> tuple[dict[tuple[int, str], float], dict[tuple[int, str], float]]:
    """Separa lo que TODAVÍA no se ha movido, por lado.

    El Paso 1 lee la existencia real de stock.quant. Si un traspaso ya se validó en
    Odoo, esa mercancía ya está contada ahí y volver a aplicarla la contaría dos
    veces. Por eso solo se aplica lo que sigue pendiente — y cada lado por separado,
    porque la tienda origen saca la mercancía días antes de que la destino la reciba.

    No hace falta saber de qué corrida es cada fila: las de meses pasados tienen
    ambos pickings cerrados y quedan fuera solas.

    Returns:
        ({(product_id, tienda): por_salir}, {(product_id, tienda): por_llegar})
    """
    por_salir: dict[tuple[int, str], float] = defaultdict(float)
    por_llegar: dict[tuple[int, str], float] = defaultdict(float)

    for t in traspasos:
        # Salida cancelada: la mercancía nunca sale, así que tampoco llega.
        if t.estado_salida == "cancel":
            continue
        if t.estado_salida not in PICKING_CERRADO:
            por_salir[(t.product_id, t.origen)] += t.cantidad
        if t.estado_entrada not in PICKING_CERRADO:
            por_llegar[(t.product_id, t.destino)] += t.cantidad

    return dict(por_salir), dict(por_llegar)


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

    # --- movimientos_pendientes: solo se aplica lo que todavía no se movió ---
    def t(salida="", entrada="", cant=5.0):
        return TraspasoConfirmado(1, "ORIGEN", "DESTINO", cant, salida, entrada)

    # Verificado, sin pickings todavía: el movimiento está por ocurrir entero.
    sale, llega = movimientos_pendientes([t()])
    assert sale == {(1, "ORIGEN"): 5.0} and llega == {(1, "DESTINO"): 5.0}

    # En tránsito: ya salió del origen (el quant ya lo refleja) pero no ha llegado.
    sale, llega = movimientos_pendientes([t("done", "assigned")])
    assert sale == {} and llega == {(1, "DESTINO"): 5.0}

    # Traspaso viejo, ambos validados: no se aplica nada. Así se excluyen solas las
    # corridas de meses anteriores, sin filtrar por fecha.
    sale, llega = movimientos_pendientes([t("done", "done")])
    assert sale == {} and llega == {}

    # Salida cancelada: la mercancía no sale, así que tampoco llega.
    sale, llega = movimientos_pendientes([t("cancel", "assigned")])
    assert sale == {} and llega == {}

    # Recepción cancelada tras haber salido: el origen ya descontó, el destino nunca recibe.
    sale, llega = movimientos_pendientes([t("done", "cancel")])
    assert sale == {} and llega == {}

    # Varias filas del mismo producto se acumulan por tienda.
    sale, llega = movimientos_pendientes([t(cant=3.0), t(cant=4.0), t("done", "done", 99.0)])
    assert sale == {(1, "ORIGEN"): 7.0} and llega == {(1, "DESTINO"): 7.0}

    print("OK")

