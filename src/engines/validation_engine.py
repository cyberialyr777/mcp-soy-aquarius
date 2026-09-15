"""Motor de validación — sanity checks antes de cargar pedidos en Odoo."""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from src.engines.orderpoint_updater import RegistroPedido
from src.engines.transfer_planner import TraspasoLinea


@dataclass
class ResultadoValidacion:
    ok: bool
    errores: list[str] = field(default_factory=list)
    advertencias: list[str] = field(default_factory=list)


class ValidationEngine:

    def validar_corrida(
        self,
        paso3: list[RegistroPedido],
        lineas_traspasos: list[TraspasoLinea],
    ) -> ResultadoValidacion:
        """Valida consistencia entre el plan de traspasos y el pedido final.

        No se comprueba que el total enviado sea igual al recibido: cada línea suma
        lo mismo de los dos lados, así que esa igualdad se cumple sola y no prueba
        nada. Se comprueba lo que sí puede salir mal:

          1. qty_to_order >= 0.
          2. Cantidades de traspaso enteras y mayores que cero.
          3. Ninguna tienda envía más de lo que tenía.
          4. Ninguna tienda envía y recibe el mismo producto (movimiento circular).
          5. existencia_despues nunca queda negativa.
          6. Advertencias: existencia por encima del nuevo máximo, y productos con
             qty_to_order > 0 pero sin orderpoint que actualizar.
        """
        errores: list[str] = []
        advertencias: list[str] = []

        for r in paso3:
            if r.qty_to_order < 0:
                errores.append(
                    f"qty_to_order negativo: {r.nombre} @ {r.tienda} = {r.qty_to_order}"
                )
            if r.existencia_despues < 0:
                errores.append(
                    f"Existencia negativa tras traspasos: {r.nombre} @ {r.tienda} "
                    f"= {r.existencia_despues}"
                )
            if r.nuevo_maximo and r.existencia_despues > r.nuevo_maximo:
                advertencias.append(
                    f"{r.nombre} @ {r.tienda} queda en {r.existencia_despues} "
                    f"con máximo {r.nuevo_maximo}"
                )

        enviado: dict[tuple[int, str], float] = defaultdict(float)
        recibido: dict[tuple[int, str], float] = defaultdict(float)

        for l in lineas_traspasos:
            if l.cantidad <= 0:
                errores.append(
                    f"Traspaso sin cantidad: {l.nombre} {l.origen} → {l.destino} = {l.cantidad}"
                )
            elif int(l.cantidad) != l.cantidad:
                errores.append(
                    f"Traspaso con fracción: {l.nombre} {l.origen} → {l.destino} = {l.cantidad}"
                )
            if l.origen == l.destino:
                errores.append(f"Traspaso a sí misma: {l.nombre} en {l.origen}")
            enviado[(l.product_id, l.origen)] += l.cantidad
            recibido[(l.product_id, l.destino)] += l.cantidad

        # Una tienda no puede enviar más de lo que tenía antes de los traspasos.
        # CEDIS no aparece en paso3, así que solo se valida lo que sí está ahí.
        existencia_antes = {(r.product_id, r.tienda): r.existencia_antes for r in paso3}
        nombres = {(r.product_id, r.tienda): r.nombre for r in paso3}

        for clave, total in enviado.items():
            antes = existencia_antes.get(clave)
            if antes is not None and total > antes:
                errores.append(
                    f"{nombres.get(clave, clave[0])} @ {clave[1]}: envía {total} "
                    f"pero solo tenía {antes}"
                )
            if clave in recibido:
                errores.append(
                    f"{nombres.get(clave, clave[0])} @ {clave[1]}: envía y recibe "
                    "el mismo producto"
                )

        sin_op = [r for r in paso3 if r.orderpoint_id is None and r.qty_to_order > 0]
        if sin_op:
            advertencias.append(
                f"{len(sin_op)} productos con qty_to_order>0 pero sin orderpoint — "
                "no se actualizará reabastecimiento para esos productos"
            )

        return ResultadoValidacion(ok=not errores, errores=errores, advertencias=advertencias)


if __name__ == "__main__":
    engine = ValidationEngine()

    def registro(tienda, antes, despues, qty, maximo=20, pid=1, op=42):
        return RegistroPedido(op, pid, "P1", tienda, antes, despues, maximo, maximo,
                              qty, "Activo", "A")

    # Corrida sana.
    ok = engine.validar_corrida(
        [registro("T1", 10.0, 8.0, 12), registro("T2", 4.0, 6.0, 14, pid=1, op=43)],
        [TraspasoLinea(1, "P1", "T1", "T2", 2, "Activo_excedente")],
    )
    assert ok.ok, ok.errores
    assert not ok.advertencias, ok.advertencias

    # Una tienda envía más de lo que tenía → error (antes esto pasaba desapercibido).
    malo = engine.validar_corrida(
        [registro("T1", 1.0, -4.0, 0)],
        [TraspasoLinea(1, "P1", "T1", "T2", 5, "Activo_excedente")],
    )
    assert not malo.ok
    assert any("envía 5" in e for e in malo.errores), malo.errores
    assert any("negativa" in e for e in malo.errores), malo.errores

    # Envía y recibe el mismo producto.
    circular = engine.validar_corrida(
        [registro("T1", 10.0, 10.0, 10)],
        [TraspasoLinea(1, "P1", "T1", "T2", 3, "CEDIS"),
         TraspasoLinea(1, "P1", "T3", "T1", 3, "CEDIS")],
    )
    assert not circular.ok
    assert any("envía y recibe" in e for e in circular.errores), circular.errores

    # qty_to_order negativo y traspaso en cero.
    varios = engine.validar_corrida(
        [registro("T1", 10.0, 10.0, -1)],
        [TraspasoLinea(1, "P1", "T1", "T2", 0, "CEDIS")],
    )
    assert not varios.ok
    assert any("qty_to_order negativo" in e for e in varios.errores), varios.errores
    assert any("sin cantidad" in e for e in varios.errores), varios.errores

    # Sin orderpoint → advertencia, no error.
    sin_op = engine.validar_corrida(
        [RegistroPedido(None, 1, "P1", "T1", 10.0, 10.0, 20, 20, 10, "Activo", "A")], [])
    assert sin_op.ok
    assert any("sin orderpoint" in a for a in sin_op.advertencias), sin_op.advertencias

    print("OK")
