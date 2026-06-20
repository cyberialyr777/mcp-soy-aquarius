from dataclasses import dataclass, field
from datetime import date
from typing import Optional


@dataclass
class StockQuant:
    product_id: tuple  # (id, name)
    location_id: tuple  # (id, name)
    quantity: float
    reserved_quantity: float = 0.0

    @property
    def disponible(self) -> float:
        return self.quantity - self.reserved_quantity


@dataclass
class ArsabeQuant:
    """Modelo custom de SoyAquarius que extiende stock.quant con auditoría de movimiento."""
    product_id: tuple  # (id, name)
    location_id: tuple  # (id, name)
    quantity: float
    reserved_quantity: float = 0.0
    ultima_entrada: Optional[date] = None   # Fecha de la última entrada de inventario
    ultima_salida: Optional[date] = None    # Fecha de la última venta/salida
    dias_sin_movimiento: int = 0            # Días desde el último movimiento (entrada o salida)

    @property
    def disponible(self) -> float:
        return self.quantity - self.reserved_quantity


@dataclass
class Orderpoint:
    id: int
    product_id: tuple
    location_id: tuple
    route_id: Optional[tuple]
    product_min_qty: float
    product_max_qty: float
    qty_to_order: float
    qty_on_hand: float = 0.0


@dataclass
class PosOrderLine:
    product_id: tuple
    qty: float
    price_unit: float
    price_subtotal: float
    order_id: tuple  # (id, name)


@dataclass
class StockPicking:
    id: int
    name: str
    origin: str
    location_id: tuple
    location_dest_id: tuple
    state: str
    move_ids: list = field(default_factory=list)


@dataclass
class StockMove:
    id: int
    product_id: tuple
    product_uom_qty: float
    quantity: float
    location_id: tuple
    location_dest_id: tuple
    state: str
