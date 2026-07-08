"""Modelos Pydantic de validación para los tools MCP.

Separados de generic.py para que los tests puedan importarlos
sin necesitar el módulo `mcp`.
"""
from pydantic import BaseModel, Field, ConfigDict


class OdooSearchInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    model: str = Field(..., description="Nombre del modelo Odoo (ej. 'stock.quant', 'pos.order.line')", min_length=1)
    domain: list = Field(default_factory=list, description="Dominio de filtrado Odoo (ej. [['location_id.usage','=','internal']])")
    fields: list[str] = Field(..., description="Lista de campos a retornar (ej. ['product_id', 'quantity'])")
    limit: int = Field(default=100, description="Máximo de registros. 0 = sin límite", ge=0)
    order: str = Field(default="", description="Campo de ordenamiento (ej. 'name asc')")


class OdooReadInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    model: str = Field(..., description="Nombre del modelo Odoo", min_length=1)
    ids: list[int] = Field(..., description="Lista de IDs a leer", min_length=1)
    fields: list[str] = Field(..., description="Lista de campos a retornar")


class OdooCreateInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    model: str = Field(..., description="Nombre del modelo Odoo", min_length=1)
    values: dict = Field(..., description="Diccionario con los valores del nuevo registro")


class OdooWriteInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    model: str = Field(..., description="Nombre del modelo Odoo", min_length=1)
    ids: list[int] = Field(..., description="Lista de IDs a actualizar", min_length=1)
    values: dict = Field(..., description="Diccionario con los campos a modificar")


class OdooCallMethodInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    model: str = Field(..., description="Nombre del modelo Odoo", min_length=1)
    method: str = Field(..., description="Nombre del método a ejecutar (ej. 'action_confirm')", min_length=1)
    ids: list[int] = Field(..., description="Lista de IDs sobre los que ejecutar el método", min_length=1)


class OdooGetFieldsInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    model: str = Field(..., description="Nombre del modelo Odoo", min_length=1)


class OdooSearchCountInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    model: str = Field(..., description="Nombre del modelo Odoo", min_length=1)
    domain: list = Field(default_factory=list, description="Dominio de filtrado Odoo")


# ---------------------------------------------------------------------------
# Sprint 2 — Compras
# ---------------------------------------------------------------------------

class ComprasGetVentasAnioInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    proveedor: str = Field(..., description="Nombre del proveedor (ej. 'TONICOL')", min_length=1)
    fecha_inicio: str = Field(..., description="Fecha inicio en formato 'YYYY-MM-DD' (ej. '2025-01-01')")
    fecha_fin: str = Field(..., description="Fecha fin en formato 'YYYY-MM-DD' (ej. '2025-12-31')")
    tienda: str = Field(default="", description="Nombre de la tienda para filtrar. Vacío = todas las tiendas")


class ComprasGetOrderpointsInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    proveedor: str = Field(..., description="Nombre del proveedor", min_length=1)
    tienda: str = Field(default="", description="Nombre de la tienda para filtrar. Vacío = todas")


class ComprasCalcularStockSugeridoInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    proveedor: str = Field(..., description="Nombre del proveedor (ej. 'TONICOL')", min_length=1)
    fecha_inicio: str = Field(..., description="Inicio del año de análisis 'YYYY-MM-DD' (ej. '2026-01-01')")
    fecha_fin: str = Field(..., description="Fin del periodo de análisis 'YYYY-MM-DD' (ej. '2026-12-31')")
    tienda: str = Field(default="", description="Tienda específica. Vacío = calcular para todas las tiendas")


class ComprasGetCalendarioInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    proveedor: str = Field(..., description="Nombre del proveedor", min_length=1)


# ---------------------------------------------------------------------------
# Sprint 3 — Traspasos
# ---------------------------------------------------------------------------

class TraspasosCedisInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    proveedor: str = Field(..., description="Nombre del proveedor", min_length=1)
    cedis_keyword: str = Field(default="CEDIS", description="Substring para identificar la tienda CEDIS (ej. 'CEDIS')")


class TraspasosPlanInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    proveedor: str = Field(..., description="Nombre del proveedor", min_length=1)
    fecha_inicio: str = Field(..., description="Inicio del periodo de análisis 'YYYY-MM-DD'")
    fecha_fin: str = Field(..., description="Fin del periodo de análisis 'YYYY-MM-DD'")
    cedis_keyword: str = Field(default="CEDIS", description="Substring para identificar la tienda CEDIS")


class TraspasosCargarModuloInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    proveedor: str = Field(..., description="Nombre del proveedor", min_length=1)
    lineas_json: str = Field(
        ...,
        description=(
            "JSON string con el array 'lineas' de la salida de traspasos_calcular_plan. "
            "Ejemplo: '[{\"product_id\": 1, \"nombre\": \"X\", \"origen\": \"A\", "
            "\"destino\": \"B\", \"cantidad\": 5, \"tipo_origen\": \"CEDIS\"}]'"
        ),
    )
    origen_referencia: str = Field(default="", description="Referencia del lote (ej. 'DONSOL-JUN-2026')")


class TraspasosGetEstadoInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    proveedor: str = Field(..., description="Nombre del proveedor", min_length=1)
    state: str = Field(default="", description="Filtrar por estado. Vacío = borrador+verificado")


class TraspasosGenerarPickingsInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    proveedor: str = Field(..., description="Nombre del proveedor", min_length=1)
    origen_referencia: str = Field(default="", description="Referencia para los pickings (ej. 'DONSOL-JUN-2026')")


# ---------------------------------------------------------------------------
# Sprint 4 — Auditoría y validación
# ---------------------------------------------------------------------------

class AuditRegistrarAccionInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    usuario: str = Field(..., description="Usuario que ejecuta la acción", min_length=1)
    accion: str = Field(..., description="Descripción de la acción (ej. 'calcular_paso1')", min_length=1)
    proveedor: str = Field(default="", description="Nombre del proveedor involucrado")
    resultados_json: str = Field(default="", description="JSON opcional con resumen de resultados")
    archivos_generados: list[str] = Field(default_factory=list, description="Rutas de archivos generados")


class ValidationValidarCorridaInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    paso3_json: str = Field(
        ...,
        description="JSON del campo 'registros' de la salida de pedidos_crear_registros",
    )
    lineas_json: str = Field(
        ...,
        description="JSON del campo 'lineas' de la salida de traspasos_calcular_plan",
    )


# ---------------------------------------------------------------------------
# Sprint 4 — Pedidos
# ---------------------------------------------------------------------------

class PedidosCrearRegistrosInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    proveedor: str = Field(..., description="Nombre del proveedor", min_length=1)
    fecha_inicio: str = Field(..., description="Inicio del periodo de análisis 'YYYY-MM-DD'")
    fecha_fin: str = Field(..., description="Fin del periodo de análisis 'YYYY-MM-DD'")
    cedis_keyword: str = Field(default="CEDIS", description="Keyword para identificar CEDIS")


class PedidosActualizarReabastecimientoInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    proveedor: str = Field(..., description="Nombre del proveedor", min_length=1)


class PedidosGetEstadoInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    proveedor: str = Field(..., description="Nombre del proveedor", min_length=1)
    state: str = Field(default="", description="Filtrar por estado. Vacío = todos")


# ---------------------------------------------------------------------------
# Sprint 4 — Reportes
# ---------------------------------------------------------------------------

class ReportesExcelInput(BaseModel):
    """Reutilizado por paso1, paso2, paso3 y costeo."""
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    proveedor: str = Field(..., description="Nombre del proveedor", min_length=1)
    datos_json: str = Field(..., description="JSON con los datos del paso a exportar")
