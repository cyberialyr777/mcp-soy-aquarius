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


class TraspasosBorradorInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    lineas_json: str = Field(
        ...,
        description=(
            "JSON string con el array 'lineas' de la salida de traspasos_calcular_plan. "
            "Ejemplo: '[{\"product_id\": 1, \"nombre\": \"X\", \"origen\": \"A\", "
            "\"destino\": \"B\", \"cantidad\": 5, \"tipo_origen\": \"CEDIS\"}]'"
        ),
    )
    origen_referencia: str = Field(
        default="",
        description="Referencia opcional para identificar los pickings (ej. 'DONSOL-JUN-2026')",
    )


class TraspasosValidarInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    picking_ids: list[int] = Field(
        ...,
        description="Lista de IDs de stock.picking a validar (retornados por traspasos_crear_borrador)",
        min_length=1,
    )
