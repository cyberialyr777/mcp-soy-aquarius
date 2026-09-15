"""Motor de cálculo de stock sugerido — Paso 1.

Lógica pura de negocio. Sin dependencias de Odoo ni MCP.
100% testeable en seco con datos ficticios.
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
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
class Stockout:
    """Resultado del análisis de agotamiento de un producto en una tienda."""
    activo: bool = False
    dias_con_stock: int = 0
    tasa_mensual: float = 0.0
    confiable: bool = False   # dias_con_stock >= DIAS_STOCK_CONFIABLE


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
    dias_sin_venta: int = 0
    # Días que el producto lleva en la tienda (desde la última entrada).
    # None = sin fecha de entrada conocida; el Paso 2 lo trata como reciente.
    dias_en_tienda: Optional[int] = None
    # Se agotó porque se vendía, no porque no se venda.
    stockout: bool = False
    tasa_efectiva: float = 0.0     # ventas mensuales mientras SÍ hubo stock
    dias_con_stock: int = 0
    alertas: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Funciones de clasificación (expuestas para tests unitarios)
# ---------------------------------------------------------------------------

def meses_del_periodo(fecha_inicio: str, fecha_fin: str) -> list[str]:
    """Todos los meses del rango en orden: ['2026-01', ..., '2026-08'].

    Los meses sin ventas valen cero, no desaparecen. Derivarlos de los pedidos
    existentes hace que un mes sin ventas del proveedor se esfume, y entonces el
    promedio se divide entre menos meses de los reales — pidiendo de más.
    """
    ini = date.fromisoformat(fecha_inicio[:10])
    fin = date.fromisoformat(fecha_fin[:10])
    meses: list[str] = []
    anio, mes = ini.year, ini.month
    while (anio, mes) <= (fin.year, fin.month):
        meses.append(f"{anio}-{mes:02d}")
        anio, mes = (anio + 1, 1) if mes == 12 else (anio, mes + 1)
    return meses


def dias_desde(fecha: Optional[str], hoy: date) -> Optional[int]:
    """Días transcurridos desde una fecha de Odoo ('YYYY-MM-DD' o con hora). None si no hay."""
    if not fecha:
        return None
    try:
        d = datetime.strptime(str(fecha)[:10], "%Y-%m-%d").date()
    except ValueError:
        return None
    return max(0, (hoy - d).days)


# --- Stockout (Paso 1.0 del manual) -----------------------------------------

DIAS_STOCK_CONFIABLE = 14   # con menos días la tasa efectiva es ruido, no señal
DIAS_SIN_VENTA_STOCKOUT = 30
VENTAS_MINIMAS_STOCKOUT = 3


def _primer_dia(mes_iso: str) -> date:
    anio, mes = mes_iso.split("-")
    return date(int(anio), int(mes), 1)


def _ultimo_dia(mes_iso: str) -> date:
    anio, mes = int(mes_iso[:4]), int(mes_iso[5:7])
    return date(anio + (mes == 12), (mes % 12) + 1, 1) - timedelta(days=1)


def detectar_stockout(
    ventana: list[str],
    ventas_ventana: list[float],
    existencia: float,
    ultima_entrada: Optional[str],
    ultima_venta: Optional[str],
    dias_sin_venta: int,
) -> Stockout:
    """Detecta si el producto está agotado por demanda, no por falta de ella.

    Un producto que se acabó porque se vendía bien queda sin ventas recientes y sin
    existencia: visto de lejos parece muerto, y se le calcularía máximo 0. La tasa
    efectiva mide lo que vendía MIENTRAS tuvo mercancía, que es la demanda real.

    Marca stockout si se cumplen las cuatro condiciones del manual: sin existencia,
    sin reposición después de la última venta, más de 30 días sin vender, y al menos
    3 ventas en la ventana (por debajo de eso es ruido).
    """
    if not ventana or existencia > 0 or not ultima_venta:
        return Stockout()
    if dias_sin_venta <= DIAS_SIN_VENTA_STOCKOUT:
        return Stockout()
    if sum(ventas_ventana) < VENTAS_MINIMAS_STOCKOUT:
        return Stockout()

    f_venta = date.fromisoformat(str(ultima_venta)[:10])
    f_entrada = date.fromisoformat(str(ultima_entrada)[:10]) if ultima_entrada else None

    # Si hubo reposición después de la última venta, no es stockout: hay mercancía
    # nueva que simplemente no se ha vendido.
    if f_entrada and f_entrada > f_venta:
        return Stockout()

    inicio_ventana = _primer_dia(ventana[0])
    fin_ventana = _ultimo_dia(ventana[-1])

    # `ultima_entrada` en Odoo es la entrada MÁS RECIENTE, no la primera. Si hubo
    # ventas en meses que cerraron antes de esa fecha, es que hubo entradas previas
    # sin registrar, así que el stock venía desde el arranque de la ventana.
    ventas_antes = 0.0
    if f_entrada:
        ventas_antes = sum(
            qty for mes, qty in zip(ventana, ventas_ventana)
            if _ultimo_dia(mes) < f_entrada
        )

    if f_entrada and ventas_antes == 0:
        inicio = max(inicio_ventana, f_entrada)
    else:
        inicio = inicio_ventana

    fin = min(fin_ventana, f_venta)
    dias_con_stock = (fin - inicio).days + 1
    if dias_con_stock <= 0:
        return Stockout(activo=True)

    tasa = sum(ventas_ventana) / dias_con_stock * 30
    return Stockout(
        activo=True,
        dias_con_stock=dias_con_stock,
        tasa_mensual=tasa,
        confiable=dias_con_stock >= DIAS_STOCK_CONFIABLE,
    )


def calcular_maximo_stockout(tasa_mensual: float, abc: str) -> int:
    """Máximo cuando el producto estuvo agotado: manda la tasa efectiva.

    Mismos multiplicadores que el flujo normal (×2 para 80/20), aplicados sobre la
    tasa en lugar del promedio. No se aplica la regla del pico: un pico dentro de una
    ventana corta es el flush del lote, no demanda sostenida.
    """
    resultado = tasa_mensual * (2 if abc == "A" else 1)
    redondeado = round(resultado)
    if redondeado == 0 and tasa_mensual >= 0.33:
        return 1
    return redondeado


def detectar_alertas(ventas_3m: list[float]) -> list[str]:
    """Banderas de revisión manual (Paso 1.1). No cambian el cálculo."""
    alertas: list[str] = []
    if len(ventas_3m) < 2:
        return alertas

    promedio = sum(ventas_3m) / len(ventas_3m)
    if promedio > 0:
        desviacion = statistics.pstdev(ventas_3m)
        if desviacion / promedio > 0.5:
            alertas.append("alta volatilidad — revisar")

    for i, valor in enumerate(ventas_3m):
        otros = ventas_3m[:i] + ventas_3m[i + 1:]
        mediana = statistics.median(otros) if otros else 0.0
        if mediana > 0 and valor >= 3 * mediana:
            alertas.append(f"posible outlier en el mes {i + 1} de la ventana")
    return alertas


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

    Todos los meses son cerrados (la convención es correr hasta el último día del
    mes anterior). El último elemento es el mes más reciente y se usa tal cual,
    sin extrapolar.
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
        hoy: Optional[date] = None,
        ultima_venta: Optional[dict[int, str]] = None,
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
            hoy: Fecha de referencia para la antigüedad del stock. Default: hoy.
            ultima_venta: {product_id: 'YYYY-MM-DD'} con la fecha exacta de la última
                          venta en esta tienda. Sin ella los días sin venta se estiman
                          en bloques de 30 días y no se puede detectar el stockout.

        Returns:
            Lista de ProductoSugerido con rotacion, abc, patron, ventas_3m, nuevo_maximo.
        """
        hoy = hoy or date.today()
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

        # Últimos 3 meses del periodo — todos cerrados, sin extrapolar
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

            # Días sin venta: con la fecha exacta de la última venta se usa esa. La
            # estimación por meses (bloques de 30 días) puede mover la frontera
            # 100/180 hasta un mes entero, así que solo se usa como respaldo.
            fecha_ultima_venta = (ultima_venta or {}).get(pid)
            dias_exactos = dias_desde(fecha_ultima_venta, hoy)

            if dias_exactos is not None:
                dias_sin_venta = dias_exactos
            elif tiene_ventas:
                meses_con_ventas = [m for m in meses_disponibles if ventas_mes.get(m, 0) > 0]
                if meses_con_ventas and meses_disponibles:
                    ultimo_mes_venta = meses_con_ventas[-1]
                    idx = meses_disponibles.index(ultimo_mes_venta)
                    meses_sin_venta = len(meses_disponibles) - 1 - idx
                    dias_sin_venta = meses_sin_venta * 30
                else:
                    dias_sin_venta = dias_sin_mov
            else:
                # Ni una venta en el periodo. La antigüedad la marca la última entrada:
                # lo que acaba de llegar todavía no es rezagado. Sin esa fecha, se asume
                # parado todo el periodo analizado (nunca 0, que lo haría "Activo").
                dias_desde_entrada = dias_desde(
                    quant.ultima_entrada if quant else None, hoy
                )
                if dias_desde_entrada is not None:
                    dias_sin_venta = dias_desde_entrada
                else:
                    dias_sin_venta = max(dias_sin_mov, len(meses_disponibles) * 30)

            rotacion = clasificar_rotacion(dias_sin_venta, tiene_ventas, tiene_existencia, tiene_entradas)
            abc = abc_tienda.get(pid, "C")
            alertas = detectar_alertas(ventas_3m)

            agotado = detectar_stockout(
                ventana=ultimos_3,
                ventas_ventana=ventas_3m,
                existencia=existencia,
                ultima_entrada=quant.ultima_entrada if quant else None,
                ultima_venta=fecha_ultima_venta,
                dias_sin_venta=dias_sin_venta,
            )

            if agotado.activo and agotado.confiable:
                # Se agotó vendiendo: manda la tasa efectiva, no el promedio (que
                # está diluido por los meses en que no hubo nada que vender).
                patron = "stockout"
                nuevo_max = calcular_maximo_stockout(agotado.tasa_mensual, abc)
            else:
                patron = detectar_patron(ventas_3m, abc)
                nuevo_max = calcular_nuevo_maximo(ventas_3m, patron)
                if agotado.activo:
                    alertas.append("stockout corto — tasa de baja confianza, se usa el promedio")

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
                dias_sin_venta=dias_sin_venta,
                dias_en_tienda=dias_desde(quant.ultima_entrada if quant else None, hoy),
                stockout=agotado.activo,
                tasa_efectiva=agotado.tasa_mensual,
                dias_con_stock=agotado.dias_con_stock,
                alertas=alertas,
            ))

        return resultados


if __name__ == "__main__":
    # Clasificación de rotación cuando el producto NO vendió en el periodo.
    HOY = date(2026, 9, 1)
    MESES = [f"2026-{m:02d}" for m in range(1, 9)]   # ene–ago, periodo de 8 meses
    PRODS = {1: "Producto X"}

    def rotacion(quants: list[StockQuant], ventas: list[VentaMes]) -> str:
        return PurchasePlanner().calcular(
            proveedor="P", tienda="T", ventas_proveedor=ventas,
            ventas_catalogo_anual={}, quants=quants, productos=PRODS,
            meses_disponibles=MESES, hoy=HOY,
        )[0].rotacion

    def con_stock(entrada: Optional[str]) -> list[StockQuant]:
        return [StockQuant(product_id=1, tienda="T", existencia=5.0, ultima_entrada=entrada)]

    # Con stock y cero ventas: lo viejo es Crítico, no "Activo".
    assert rotacion(con_stock("2026-01-05"), []) == "Critico"
    # ...pero lo que acaba de llegar todavía no es rezagado.
    assert rotacion(con_stock("2026-08-25"), []) == "Activo"
    assert rotacion(con_stock("2026-04-20"), []) == "Rezagado"
    # Sin fecha de entrada se asume parado todo el periodo (nunca 0 días).
    assert rotacion(con_stock(None), []) == "Critico"
    # Sin stock, sin ventas y sin entradas: nunca entró al catálogo de la tienda.
    assert rotacion([], []) == "Nunca_entrado"
    # Con ventas manda el historial mensual, no la fecha de entrada.
    assert rotacion(con_stock("2026-01-05"), [VentaMes(1, "T", "2026-08", 3.0)]) == "Activo"
    assert rotacion(con_stock("2026-08-25"), [VentaMes(1, "T", "2026-01", 3.0)]) == "Critico"

    assert dias_desde("2026-08-25 14:30:00", HOY) == 7
    assert dias_desde(None, HOY) is None
    assert dias_desde(False, HOY) is None
    assert dias_desde("basura", HOY) is None

    # Los meses salen del periodo pedido, no de los meses que tuvieron ventas.
    assert meses_del_periodo("2026-01-01", "2026-08-31") == MESES
    assert meses_del_periodo("2026-11-01", "2027-02-28") == [
        "2026-11", "2026-12", "2027-01", "2027-02"]
    assert meses_del_periodo("2026-03-15", "2026-03-31") == ["2026-03"]

    # Un producto que solo vendió en enero y agosto promedia sobre los 3 últimos
    # meses del periodo (jun, jul, ago), no sobre los 2 meses que sí vendieron.
    sugerido = PurchasePlanner().calcular(
        proveedor="P", tienda="T",
        ventas_proveedor=[VentaMes(1, "T", "2026-01", 30.0), VentaMes(1, "T", "2026-08", 3.0)],
        ventas_catalogo_anual={}, quants=con_stock("2026-08-25"), productos=PRODS,
        meses_disponibles=MESES, hoy=HOY,
    )[0]
    assert sugerido.ventas_3m == [0.0, 0.0, 3.0], sugerido.ventas_3m

    # --- Fase C: stockout (Paso 1.0 del manual) ---
    VENTANA = ["2026-06", "2026-07", "2026-08"]

    def so(ventas, existencia=0.0, entrada=None, venta=None, dias=60):
        return detectar_stockout(VENTANA, ventas, existencia, entrada, venta, dias)

    # Se agotó vendiendo: entró el 1-jun, vendió hasta el 30-jun y se acabó.
    agotado = so([10.0, 0.0, 0.0], entrada="2026-06-01", venta="2026-06-30")
    assert agotado.activo and agotado.confiable
    assert agotado.dias_con_stock == 30, agotado.dias_con_stock
    assert abs(agotado.tasa_mensual - 10.0) < 0.01, agotado.tasa_mensual
    # El promedio 3M diría 3.3/mes; la tasa efectiva dice 10. Esa es la diferencia.
    assert calcular_maximo_stockout(agotado.tasa_mensual, "C") == 10
    assert calcular_maximo_stockout(agotado.tasa_mensual, "A") == 20   # 80/20 sigue x2

    # Con existencia no hay stockout: hay mercancía, simplemente no se vende.
    assert not so([10.0, 0.0, 0.0], existencia=5.0, entrada="2026-06-01", venta="2026-06-30").activo
    # Menos de 3 ventas en la ventana: ruido, no señal.
    assert not so([2.0, 0.0, 0.0], entrada="2026-06-01", venta="2026-06-30").activo
    # Vendió hace poco: todavía no es stockout.
    assert not so([10.0, 0.0, 0.0], entrada="2026-06-01", venta="2026-08-30", dias=10).activo
    # Hubo reposición después de la última venta: hay producto nuevo sin vender.
    assert not so([10.0, 0.0, 0.0], entrada="2026-08-20", venta="2026-06-30").activo
    # Hubo ventas antes de la última entrada → hubo entradas previas sin registrar,
    # así que el stock venía desde el arranque de la ventana (regla v3.1 del manual).
    previo = so([5.0, 0.0, 0.0], entrada="2026-08-25", venta="2026-08-31")
    assert previo.dias_con_stock == 92, previo.dias_con_stock

    # Ventana corta: entró el 1-jul, vendió hasta el 5-jul. 5 días de stock → se
    # marca el stockout pero sin confianza, y el cálculo cae al promedio.
    corto = so([0.0, 5.0, 0.0], entrada="2026-07-01", venta="2026-07-05")
    assert corto.activo and not corto.confiable, corto
    assert corto.dias_con_stock == 5, corto.dias_con_stock

    # Integración: el producto agotado recupera un máximo real en vez de 0.
    agotado_prod = PurchasePlanner().calcular(
        proveedor="P", tienda="T",
        ventas_proveedor=[VentaMes(1, "T", "2026-06", 10.0)],
        ventas_catalogo_anual={}, quants=[StockQuant(1, "T", 0.0, ultima_entrada="2026-06-01")],
        productos=PRODS, meses_disponibles=MESES, hoy=HOY,
        ultima_venta={1: "2026-06-30"},
    )[0]
    assert agotado_prod.stockout, agotado_prod
    assert agotado_prod.patron == "stockout"
    assert agotado_prod.nuevo_maximo == 10, agotado_prod.nuevo_maximo
    # Con el promedio 3M habría salido 3 en vez de 10.
    assert calcular_nuevo_maximo([10.0, 0.0, 0.0], "regular") == 3

    # Días sin venta exactos cuando se conoce la fecha (antes: bloques de 30 días).
    assert agotado_prod.dias_sin_venta == 63, agotado_prod.dias_sin_venta

    # Banderas de revisión: no cambian el cálculo.
    assert any("volatilidad" in a for a in detectar_alertas([1.0, 1.0, 20.0]))
    assert any("outlier" in a for a in detectar_alertas([1.0, 1.0, 20.0]))
    assert detectar_alertas([5.0, 5.0, 5.0]) == []

    print("OK")

