"""Motor de cálculo de stock sugerido — Paso 1.

Lógica pura de negocio. Sin dependencias de Odoo ni MCP.
100% testeable en seco con datos ficticios.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


# ---------------------------------------------------------------------------
# Tipos de datos
# ---------------------------------------------------------------------------

@dataclass
class VentaMes:
    product_id: int
    tienda: str
    mes: str   # "YYYY-MM"
    qty: float


@dataclass
class StockQuant:
    product_id: int
    tienda: str
    existencia: float
    reservado: float = 0.0
    dias_sin_movimiento: int = 0
    ultima_entrada: Optional[str] = None
    ultima_salida: Optional[str] = None

    @property
    def disponible(self) -> float:
        return max(0.0, self.existencia - self.reservado)


@dataclass
class ProductoSugerido:
    product_id: int
    nombre: str
    tienda: str
    rotacion: str    # Activo | Rezagado | Critico | Nunca_entrado
    abc: str         # A | B | C
    patron: str      # 80_20 | pico_sostenido | pico_aislado | regular
    ventas_3m: list[float]
    existencia_actual: float
    nuevo_maximo: int
    nuevo_minimo: int   # = nuevo_maximo (política SoyAquarius: min = max)


# ---------------------------------------------------------------------------
# Funciones de clasificación (expuestas para tests unitarios)
# ---------------------------------------------------------------------------

def clasificar_rotacion(
    dias_sin_venta: int,
    tiene_ventas: bool,
    tiene_existencia: bool,
    tiene_entradas: bool,
) -> str:
    """Clasifica la rotación de un producto según días sin venta y presencia en sistema."""
    if not tiene_ventas and not tiene_existencia and not tiene_entradas:
        return "Nunca_entrado"
    if dias_sin_venta <= 100:
        return "Activo"
    elif dias_sin_venta <= 180:
        return "Rezagado"
    else:
        return "Critico"


def clasificar_abc(ventas_anual_por_producto: dict[int, float]) -> dict[int, str]:
    """Clasifica productos en A/B/C basado en ventas del año.

    SIEMPRE debe calcularse desde el catálogo general de la tienda,
    nunca solo desde los productos del proveedor en proceso.

    A = top 80% acumulado de ventas
    B = siguiente 15% (80–95%)
    C = resto (larga cola)
    """
    if not ventas_anual_por_producto:
        return {}

    total = sum(ventas_anual_por_producto.values())
    if total == 0:
        return {pid: "C" for pid in ventas_anual_por_producto}

    ordenados = sorted(ventas_anual_por_producto.items(), key=lambda x: x[1], reverse=True)
    resultado: dict[int, str] = {}
    acumulado = 0.0
    is_first = True  # el producto #1 en ventas siempre es A, sin excepción

    for pid, ventas in ordenados:
        acumulado += ventas
        pct = acumulado / total

        if is_first:
            resultado[pid] = "A"
            is_first = False
        elif pct <= 0.80:
            resultado[pid] = "A"
        elif pct <= 0.95:
            resultado[pid] = "B"
        else:
            resultado[pid] = "C"

    return resultado


def detectar_patron(ventas_3m: list[float], abc: str) -> str:
    """Detecta el patrón de venta para determinar cómo calcular el nuevo máximo.

    El mes en curso (último elemento) se usa solo como referencia,
    nunca se extrapola ni multiplica.
    """
    if not ventas_3m:
        return "regular"

    promedio = sum(ventas_3m) / len(ventas_3m)
    pico = max(ventas_3m)
    mes_actual = ventas_3m[-1]

    if abc == "A":
        return "80_20"

    if promedio > 0 and pico >= promedio * 2:
        if mes_actual >= promedio * 1.5:
            return "pico_sostenido"
        else:
            return "pico_aislado"

    return "regular"


def calcular_nuevo_maximo(ventas_3m: list[float], patron: str) -> int:
    """Calcula el nuevo stock máximo sugerido.

    Reglas:
    - Siempre round(), NUNCA ceil()
    - Si el resultado es 0 pero hay demanda real (>=0.33/mes) → retorna 1
    - El stock mínimo = stock máximo (política SoyAquarius)
    """
    if not ventas_3m:
        return 0

    promedio = sum(ventas_3m) / len(ventas_3m)
    pico = max(ventas_3m)

    if patron == "80_20":
        resultado = promedio * 2
    elif patron == "pico_sostenido":
        resultado = pico
    elif patron == "pico_aislado":
        resultado = promedio * 1.5
    else:   # regular
        resultado = promedio

    redondeado = round(resultado)

    if redondeado == 0 and promedio >= 0.33:
        return 1
    return redondeado


# ---------------------------------------------------------------------------
# Motor principal
# ---------------------------------------------------------------------------

class PurchasePlanner:
    """Calcula el stock sugerido (Paso 1) para un proveedor en una tienda."""

    def calcular(
        self,
        proveedor: str,
        tienda: str,
        ventas_proveedor: list[VentaMes],
        ventas_catalogo_anual: dict[int, float],
        quants: list[StockQuant],
        productos: dict[int, str],
        meses_disponibles: list[str],
    ) -> list[ProductoSugerido]:
        """Ejecuta el cálculo completo de Paso 1 para una tienda.

        Args:
            proveedor: Nombre del proveedor (solo para contexto/logging).
            tienda: Nombre de la tienda.
            ventas_proveedor: Ventas mensuales de los productos del proveedor en esta tienda.
            ventas_catalogo_anual: Ventas totales del año de TODOS los productos de la tienda.
                                   Usado para clasificación ABC. No mezclar con ventas del proveedor.
            quants: Stock actual de los productos del proveedor en esta tienda.
            productos: Mapa {product_id: nombre} de los productos del proveedor.
            meses_disponibles: Lista de meses del año disponibles, ordenada ascendente ("YYYY-MM").

        Returns:
            Lista de ProductoSugerido con rotacion, abc, patron, ventas_3m, nuevo_maximo.
        """
        abc_tienda = clasificar_abc(ventas_catalogo_anual)

        # Agrupar ventas del proveedor por producto y mes
        ventas_por_prod: dict[int, dict[str, float]] = {}
        for v in ventas_proveedor:
            if v.qty <= 0:
                continue
            if v.product_id not in ventas_por_prod:
                ventas_por_prod[v.product_id] = {}
            ventas_por_prod[v.product_id][v.mes] = (
                ventas_por_prod[v.product_id].get(v.mes, 0.0) + v.qty
            )

        quant_por_prod: dict[int, StockQuant] = {q.product_id: q for q in quants}

        # Últimos 3 meses disponibles (mes en curso incluido, sin extrapolar)
        ultimos_3 = meses_disponibles[-3:] if len(meses_disponibles) >= 3 else meses_disponibles

        resultados: list[ProductoSugerido] = []

        for pid, nombre in productos.items():
            quant = quant_por_prod.get(pid)
            existencia = quant.existencia if quant else 0.0
            dias_sin_mov = quant.dias_sin_movimiento if quant else 999

            ventas_mes = ventas_por_prod.get(pid, {})
            ventas_3m = [ventas_mes.get(mes, 0.0) for mes in ultimos_3]

            tiene_ventas = bool(ventas_mes) and sum(ventas_mes.values()) > 0
            tiene_existencia = existencia > 0
            tiene_entradas = quant is not None and quant.ultima_entrada is not None

            # Estimar días sin venta desde historial mensual
            if tiene_ventas:
                meses_con_ventas = [m for m in meses_disponibles if ventas_mes.get(m, 0) > 0]
                if meses_con_ventas and meses_disponibles:
                    ultimo_mes_venta = meses_con_ventas[-1]
                    idx = meses_disponibles.index(ultimo_mes_venta)
                    meses_sin_venta = len(meses_disponibles) - 1 - idx
                    dias_sin_venta = meses_sin_venta * 30
                else:
                    dias_sin_venta = dias_sin_mov
            else:
                dias_sin_venta = dias_sin_mov

            rotacion = clasificar_rotacion(dias_sin_venta, tiene_ventas, tiene_existencia, tiene_entradas)
            abc = abc_tienda.get(pid, "C")
            patron = detectar_patron(ventas_3m, abc)
            nuevo_max = calcular_nuevo_maximo(ventas_3m, patron)

            resultados.append(ProductoSugerido(
                product_id=pid,
                nombre=nombre,
                tienda=tienda,
                rotacion=rotacion,
                abc=abc,
                patron=patron,
                ventas_3m=ventas_3m,
                existencia_actual=existencia,
                nuevo_maximo=nuevo_max,
                nuevo_minimo=nuevo_max,   # política SoyAquarius: min = max
            ))

        return resultados
