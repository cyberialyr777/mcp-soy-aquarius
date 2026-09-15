"""Motor de traspasos (Paso 2).

Lógica pura de negocio. Sin dependencias de Odoo ni MCP.
100% testeable en seco con datos ficticios.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from src.engines.purchase_planner import ProductoSugerido

# Tiendas excluidas como destino (pueden enviar, nunca reciben)
TIENDAS_NO_DESTINO: frozenset[str] = frozenset({"BACOAT", "WACO", "CERES"})

# Mínimo de unidades para que un traspaso valga la pena
PISO_EFICIENCIA = 3

# Una Rezagada/Crítica solo puede quedar en 0 si el producto lleva más de este tiempo
# en la tienda; si llegó hace poco conserva 1 pieza (manual, Paso 2 Tipo 1).
DIAS_EN_TIENDA_PARA_VACIAR = 100

# Una tienda Activa no manda su excedente si vendió hace poco y le sobra muy poco
# (manual v3.6): solo envía con excedente >= 3 uds, o si lleva >= 35 días sin vender.
DIAS_SIN_VENTA_EXCEDENTE = 35
EXCEDENTE_MINIMO_ACTIVA = 2


# ---------------------------------------------------------------------------
# Tipos de datos
# ---------------------------------------------------------------------------

@dataclass
class TraspasoLinea:
    product_id: int
    nombre: str
    origen: str
    destino: str
    cantidad: int
    tipo_origen: str  # CEDIS | Rezagado | Critico | Activo_excedente


@dataclass
class ResumenPostTraspaso:
    tienda: str
    product_id: int
    nombre: str
    rotacion: str
    abc: str
    existencia_antes: float
    enviado: float
    recibido: float
    existencia_despues: float
    nuevo_maximo: int
    qty_a_pedir: int


# ---------------------------------------------------------------------------
# Funciones auxiliares
# ---------------------------------------------------------------------------

def _es_cedis(tienda: str, cedis_keyword: str) -> bool:
    return cedis_keyword.upper() in tienda.upper()


def _es_excluida_destino(tienda: str) -> bool:
    t_upper = tienda.upper()
    return any(excl in t_upper for excl in TIENDAS_NO_DESTINO)


def _cobertura_dias(p: ProductoSugerido, comprometido_recibir: float = 0.0) -> float:
    """Días de cobertura proyectada = (existencia + comprometido) / demanda_diaria."""
    if not p.ventas_3m:
        return 9999.0
    promedio_diario = sum(p.ventas_3m) / len(p.ventas_3m) / 30
    if promedio_diario <= 0:
        return 9999.0
    return (p.existencia_actual + comprometido_recibir) / promedio_diario


def _ventas_2m(p: ProductoSugerido) -> float:
    """Ventas de referencia de 2 meses, para acotar cuánto puede recibir un destino.

    Son los 2 meses más recientes: todos los meses del periodo son cerrados, porque
    la convención de uso es correr hasta el último día del mes anterior.

    En una tienda agotada esos meses valen casi cero — no porque no haya demanda,
    sino porque no había qué vender. Ahí manda la tasa efectiva; si no, el tope
    dejaría sin resurtir justo al producto que se acabó por venderse bien.
    """
    if p.stockout and p.tasa_efectiva > 0:
        return p.tasa_efectiva * 2
    return sum(p.ventas_3m[-2:])


def _floor_fuente(p_src: ProductoSugerido, cedis_keyword: str) -> float:
    """Stock mínimo que debe quedar en la fuente después de enviar.

    - CEDIS: siempre puede quedar en 0.
    - Rezagado / Critico: queda en 0 solo si el producto además lleva más de 100
      días en la tienda. Si llegó hace poco conserva 1 pieza — que no venda todavía
      no significa que sobre (manual, Paso 2 Tipo 1).
    - Activo: no puede bajar de su nuevo_maximo.
    """
    if _es_cedis(p_src.tienda, cedis_keyword):
        return 0.0
    if p_src.rotacion in ("Rezagado", "Critico"):
        dias = p_src.dias_en_tienda
        # Sin fecha de entrada se asume reciente: conservar 1 es el lado seguro.
        if dias is not None and dias > DIAS_EN_TIENDA_PARA_VACIAR:
            return 0.0
        return 1.0
    return float(p_src.nuevo_maximo)


def _activa_puede_enviar(p_src: ProductoSugerido, excedente: float) -> bool:
    """Regla de tamaño del excedente Activo (manual v3.6).

    Una Activa NO envía si vendió hace menos de 35 días Y le sobran 2 o menos:
    ese sobrante es su colchón mientras llega el resurtido.
    """
    if p_src.dias_sin_venta >= DIAS_SIN_VENTA_EXCEDENTE:
        return True
    return excedente > EXCEDENTE_MINIMO_ACTIVA


# ---------------------------------------------------------------------------
# Motor principal
# ---------------------------------------------------------------------------

class TransferPlanner:
    """Calcula el plan de traspasos (Paso 2)."""

    def calcular_plan(
        self,
        sugeridos_por_tienda: dict[str, list[ProductoSugerido]],
        cedis_keyword: str = "CEDIS",
    ) -> tuple[list[TraspasoLinea], list[ResumenPostTraspaso]]:
        """Calcula qué mover, de dónde y hacia dónde.

        Prioridad de fuente:
          1. CEDIS (puede quedar en 0)
          2. Rezagadas / Críticas (pueden quedar en 0)
          3. Activas con excedente (floor = nuevo_maximo)

        Prioridad de destino: menor cobertura proyectada primero.

        Args:
            sugeridos_por_tienda: {tienda: [ProductoSugerido]} — salida de PurchasePlanner.
                                  Incluir CEDIS con nuevo_maximo=0 y existencia_actual real.
            cedis_keyword: substring para identificar la tienda CEDIS por nombre.

        Returns:
            (lineas_traspaso, resumen_post_traspaso)
        """
        # Balance disponible mutable: {tienda: {pid: float}}
        balance: dict[str, dict[int, float]] = {
            t: {p.product_id: p.existencia_actual for p in prods}
            for t, prods in sugeridos_por_tienda.items()
        }

        # Comprometido a recibir: {tienda: {pid: float}}
        comp_recibir: dict[str, dict[int, float]] = defaultdict(lambda: defaultdict(float))

        lineas: list[TraspasoLinea] = []

        # Inventario de todos los productos del proveedor
        todos_prods: dict[int, str] = {}
        for prods in sugeridos_por_tienda.values():
            for p in prods:
                todos_prods.setdefault(p.product_id, p.nombre)

        for pid, nombre in todos_prods.items():
            # --- Identificar destinos con déficit ---
            destinos = []
            for tienda, prods in sugeridos_por_tienda.items():
                if _es_cedis(tienda, cedis_keyword):
                    continue
                if _es_excluida_destino(tienda):
                    continue
                p = next((x for x in prods if x.product_id == pid), None)
                if p is None or p.nuevo_maximo == 0:
                    continue
                deficit = p.nuevo_maximo - p.existencia_actual - comp_recibir[tienda][pid]
                if deficit <= 0:
                    continue
                destinos.append((
                    _cobertura_dias(p, comp_recibir[tienda][pid]),
                    tienda,
                    p,
                ))

            # Ordenar por menor cobertura (más urgente primero)
            destinos.sort(key=lambda x: x[0])

            if not destinos:
                continue

            # --- Construir lista de fuentes ordenada por prioridad ---
            def _get_fuentes_ordenadas() -> list[tuple[str, ProductoSugerido, str]]:
                """Retorna [(tienda, ProductoSugerido, tipo_origen)] en orden de prioridad."""
                cedis: list[tuple[str, ProductoSugerido, str]] = []
                rezagadas: list[tuple[str, ProductoSugerido, str]] = []
                excedentes: list[tuple[str, ProductoSugerido, str]] = []

                for tienda, prods in sugeridos_por_tienda.items():
                    p_src = next((x for x in prods if x.product_id == pid), None)
                    if p_src is None:
                        continue
                    floor = _floor_fuente(p_src, cedis_keyword)
                    disponible = balance[tienda].get(pid, 0.0) - floor
                    if disponible <= 0:
                        continue

                    if _es_cedis(tienda, cedis_keyword):
                        cedis.append((tienda, p_src, "CEDIS"))
                    elif p_src.rotacion in ("Rezagado", "Critico"):
                        tipo = p_src.rotacion
                        rezagadas.append((tienda, p_src, tipo))
                    elif p_src.rotacion == "Activo" and _activa_puede_enviar(p_src, disponible):
                        excedentes.append((tienda, p_src, "Activo_excedente"))

                # Excedentes: mayores primero
                excedentes.sort(
                    key=lambda x: balance[x[0]].get(pid, 0.0) - float(x[1].nuevo_maximo),
                    reverse=True,
                )
                return cedis + rezagadas + excedentes

            # --- Asignar traspasos por destino ---
            for _, tienda_dst, p_dst in destinos:
                ya_recibido = comp_recibir[tienda_dst][pid]
                existencia_efectiva = p_dst.existencia_actual + ya_recibido

                cap_max = p_dst.nuevo_maximo - existencia_efectiva
                cap_ventas = _ventas_2m(p_dst) * 1.5 - existencia_efectiva
                max_recibir = max(0.0, min(cap_max, cap_ventas))

                if max_recibir <= 0:
                    continue

                pendiente = max_recibir

                for tienda_src, p_src, tipo in _get_fuentes_ordenadas():
                    if tienda_src == tienda_dst:
                        continue
                    if pendiente <= 0:
                        break

                    floor = _floor_fuente(p_src, cedis_keyword)
                    disponible_src = balance[tienda_src].get(pid, 0.0) - floor
                    if disponible_src <= 0:
                        continue

                    mover = min(pendiente, disponible_src)
                    mover_int = int(mover)

                    if mover_int <= 0:
                        continue

                    # Piso de eficiencia: mover menos de 3 uds no compensa el trámite,
                    # salvo que el producto esté crítico EN EL ORIGEN (hay que sacarlo
                    # de ahí) o que el destino esté por quedarse sin nada.
                    es_critico_origen = p_src.rotacion == "Critico"
                    es_cobertura_baja = _cobertura_dias(p_dst, ya_recibido) < 7

                    if mover_int < PISO_EFICIENCIA and not es_critico_origen and not es_cobertura_baja:
                        continue

                    # Registrar traspaso
                    balance[tienda_src][pid] = balance[tienda_src].get(pid, 0.0) - mover_int
                    comp_recibir[tienda_dst][pid] += mover_int
                    ya_recibido += mover_int
                    pendiente -= mover_int

                    lineas.append(TraspasoLinea(
                        product_id=pid,
                        nombre=nombre,
                        origen=tienda_src,
                        destino=tienda_dst,
                        cantidad=mover_int,
                        tipo_origen=tipo,
                    ))

        # --- Construir resumen post-traspaso ---
        enviado_por: dict[str, dict[int, float]] = defaultdict(lambda: defaultdict(float))
        recibido_por: dict[str, dict[int, float]] = defaultdict(lambda: defaultdict(float))
        for linea in lineas:
            enviado_por[linea.origen][linea.product_id] += linea.cantidad
            recibido_por[linea.destino][linea.product_id] += linea.cantidad

        resumen: list[ResumenPostTraspaso] = []
        for tienda, prods in sugeridos_por_tienda.items():
            for p in prods:
                enviado = enviado_por[tienda].get(p.product_id, 0.0)
                recibido = recibido_por[tienda].get(p.product_id, 0.0)
                existencia_despues = p.existencia_actual - enviado + recibido
                qty_a_pedir = max(0, p.nuevo_maximo - int(existencia_despues))
                resumen.append(ResumenPostTraspaso(
                    tienda=tienda,
                    product_id=p.product_id,
                    nombre=p.nombre,
                    rotacion=p.rotacion,
                    abc=p.abc,
                    existencia_antes=p.existencia_actual,
                    enviado=enviado,
                    recibido=recibido,
                    existencia_despues=existencia_despues,
                    nuevo_maximo=p.nuevo_maximo,
                    qty_a_pedir=qty_a_pedir,
                ))

        return lineas, resumen


if __name__ == "__main__":
    def prod(tienda, existencia, maximo, rotacion="Activo", ventas=None,
             dias_sin_venta=0, dias_en_tienda=None, pid=1):
        return ProductoSugerido(
            product_id=pid, nombre="P1", tienda=tienda, rotacion=rotacion, abc="B",
            patron="regular", ventas_3m=ventas if ventas is not None else [0.0, 0.0, 0.0],
            existencia_actual=existencia, nuevo_maximo=maximo, nuevo_minimo=maximo,
            dias_sin_venta=dias_sin_venta, dias_en_tienda=dias_en_tienda,
        )

    # --- A2: los 2 meses más recientes, no los más viejos ---
    assert _ventas_2m(prod("T", 0, 0, ventas=[10.0, 20.0, 30.0])) == 50.0
    assert _ventas_2m(prod("T", 0, 0, ventas=[5.0, 7.0])) == 12.0
    assert _ventas_2m(prod("T", 0, 0, ventas=[])) == 0.0

    # --- A4: una Rezagada solo queda en 0 si el producto lleva >100d en la tienda ---
    vieja = prod("T1", 5, 0, "Rezagado", dias_en_tienda=200)
    nueva = prod("T1", 5, 0, "Rezagado", dias_en_tienda=10)
    sin_fecha = prod("T1", 5, 0, "Rezagado", dias_en_tienda=None)
    assert _floor_fuente(vieja, "CEDIS") == 0.0
    assert _floor_fuente(nueva, "CEDIS") == 1.0        # llegó hace poco: conserva 1
    assert _floor_fuente(sin_fecha, "CEDIS") == 1.0    # sin dato: lado seguro
    assert _floor_fuente(prod("CEDIS", 5, 0), "CEDIS") == 0.0
    assert _floor_fuente(prod("T1", 9, 4), "CEDIS") == 4.0   # Activa: no baja del máximo

    # --- A5: regla de tamaño del excedente Activo (v3.6) ---
    reciente = prod("T1", 0, 0, dias_sin_venta=10)
    parada = prod("T1", 0, 0, dias_sin_venta=40)
    assert not _activa_puede_enviar(reciente, 2)   # vende y le sobran 2 → colchón
    assert _activa_puede_enviar(reciente, 3)       # le sobran 3 → sí conviene mover
    assert _activa_puede_enviar(parada, 1)         # 40d sin vender → sí envía

    planner = TransferPlanner()

    # --- A3: el piso de 3 uds se salta por origen Crítico, no por destino ---
    # Crítico en el origen con 2 uds de sobra: se mueve aunque sean < 3.
    lineas, _ = planner.calcular_plan({
        "ORIGEN": [prod("ORIGEN", 2, 0, "Critico", dias_en_tienda=300)],
        "DESTINO": [prod("DESTINO", 0, 5, ventas=[10.0, 10.0, 10.0])],
    })
    assert len(lineas) == 1 and lineas[0].cantidad == 2, lineas
    assert lineas[0].tipo_origen == "Critico"

    # Origen Activo con 2 de excedente y destino sano: el piso lo bloquea.
    lineas, _ = planner.calcular_plan({
        "ORIGEN": [prod("ORIGEN", 7, 5, dias_sin_venta=40, ventas=[3.0, 3.0, 3.0])],
        "DESTINO": [prod("DESTINO", 4, 5, ventas=[2.0, 2.0, 2.0])],
    })
    assert lineas == [], lineas

    # --- CEDIS sigue siendo la primera fuente y puede quedar en 0 ---
    lineas, resumen = planner.calcular_plan({
        "CEDIS": [prod("CEDIS", 10, 0)],
        "REZAGADA": [prod("REZAGADA", 10, 0, "Rezagado", dias_en_tienda=300)],
        "DESTINO": [prod("DESTINO", 0, 6, ventas=[8.0, 8.0, 8.0])],
    })
    assert lineas and lineas[0].origen == "CEDIS", lineas
    assert sum(l.cantidad for l in lineas) == 6, lineas

    # --- BACOAT/WACO/CERES nunca reciben ---
    lineas, _ = planner.calcular_plan({
        "CEDIS": [prod("CEDIS", 10, 0)],
        "WACO": [prod("WACO", 0, 5, ventas=[5.0, 5.0, 5.0])],
    })
    assert lineas == [], lineas

    # --- El resumen cuadra: lo enviado sale del origen y entra al destino ---
    lineas, resumen = planner.calcular_plan({
        "CEDIS": [prod("CEDIS", 10, 0)],
        "DESTINO": [prod("DESTINO", 0, 4, ventas=[6.0, 6.0, 6.0])],
    })
    por_tienda = {r.tienda: r for r in resumen}
    movido = sum(l.cantidad for l in lineas)
    assert por_tienda["CEDIS"].enviado == movido
    assert por_tienda["DESTINO"].recibido == movido
    assert por_tienda["DESTINO"].existencia_despues == movido
    assert por_tienda["DESTINO"].qty_a_pedir == max(0, 4 - movido)

    print("OK")
