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
    """Suma de los últimos 2 meses completos (excluye mes en curso)."""
    v = p.ventas_3m
    if len(v) >= 3:
        return v[0] + v[1]
    if len(v) == 2:
        return v[0]
    if len(v) == 1:
        return v[0]
    return 0.0


def _floor_fuente(p_src: ProductoSugerido, cedis_keyword: str) -> float:
    """Stock mínimo que debe quedar en la fuente después de enviar.

    - CEDIS: siempre puede quedar en 0.
    - Rezagado / Critico: puede quedar en 0.
    - Activo: no puede bajar de su nuevo_maximo.
    """
    if _es_cedis(p_src.tienda, cedis_keyword):
        return 0.0
    if p_src.rotacion in ("Rezagado", "Critico"):
        return 0.0
    return float(p_src.nuevo_maximo)


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
                    elif p_src.rotacion == "Activo" and disponible > 0:
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
                es_critico_dst = p_dst.rotacion in ("Rezagado", "Critico")

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

                    cobertura_actual = _cobertura_dias(p_dst, ya_recibido)
                    es_cobertura_baja = cobertura_actual < 7

                    # Aplicar piso de eficiencia
                    if mover_int < PISO_EFICIENCIA and not es_critico_dst and not es_cobertura_baja:
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
