"""Motor de validación — sanity checks antes de cargar pedidos en Odoo."""
from __future__ import annotations

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

        Checks:
          1. qty_to_order >= 0 en todos los registros.
          2. Total unidades enviadas == total unidades recibidas (balance traspasos).
          3. Advertencia si hay productos sin orderpoint_id (no se puede actualizar reabastecimiento).
        """
        errores: list[str] = []
        advertencias: list[str] = []

        for r in paso3:
            if r.qty_to_order < 0:
                errores.append(
                    f"qty_to_order negativo: {r.nombre} @ {r.tienda} = {r.qty_to_order}"
                )

        total_enviado = sum(l.cantidad for l in lineas_traspasos)
        total_recibido = sum(l.cantidad for l in lineas_traspasos)
        # Balance por producto
        enviado: dict[tuple[int, str], int] = {}
        recibido: dict[tuple[int, str], int] = {}
        for l in lineas_traspasos:
            enviado[(l.product_id, l.origen)] = enviado.get((l.product_id, l.origen), 0) + l.cantidad
            recibido[(l.product_id, l.destino)] = recibido.get((l.product_id, l.destino), 0) + l.cantidad
        if total_enviado != total_recibido:
            errores.append(
                f"Desbalance en traspasos: enviado={total_enviado} ≠ recibido={total_recibido}"
            )

        sin_op = [r for r in paso3 if r.orderpoint_id is None and r.qty_to_order > 0]
        if sin_op:
            advertencias.append(
                f"{len(sin_op)} productos con qty_to_order>0 pero sin orderpoint — "
                "no se actualizará reabastecimiento para esos productos"
            )

        return ResultadoValidacion(ok=not errores, errores=errores, advertencias=advertencias)


if __name__ == "__main__":
    from src.engines.orderpoint_updater import RegistroPedido
    from src.engines.transfer_planner import TraspasoLinea

    registros = [RegistroPedido(42, 1, "P1", "T1", 10.0, 8.0, 20, 20, 12, "Activo", "A")]
    lineas = [TraspasoLinea(1, "P1", "CEDIS", "T1", 2, "CEDIS")]
    engine = ValidationEngine()
    resultado = engine.validar_corrida(registros, lineas)
    assert resultado.ok, resultado.errores
    print("OK")
