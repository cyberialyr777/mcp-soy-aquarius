# CLAUDE.md — Guía completa para Claude Code

Lee también `PROPUESTA_TECNICA.md` para el contexto completo de negocio.

---

## ¿Qué es este proyecto?

Un **servidor MCP (Model Context Protocol) en Python** que conecta Claude con Odoo 18 Community para automatizar el proceso de compras, traspasos de inventario y análisis de stock de **SoyAquarius Naturista**.

El servidor corre localmente en la laptop del usuario. Claude lo usa como "herramientas" para consultar y ejecutar acciones sobre Odoo en lenguaje natural.

**El flujo central:**

```
Ventas del año → Stock sugerido → CEDIS primero → Calcular Traspasos
→ Cargar a x_traspasos (Borrador) → [Vendedoras comentan/ajustan cantidades]
→ [Generador de pickings verifica] → Generar stock.pickings en lote (borrador)
→ Pedido final (lee cantidades verificadas de x_traspasos) → Módulo x_pedidos
→ Aprobación Daniel → Reabastecimiento Odoo
```

**Nota sobre traspasos:** Existen dos tipos — ambos viven en `x_traspasos`, distinguidos por el campo `tipo`:
- **`por_proveedor`** — calculados por la IA/MCP al correr el Paso 2. El MCP los carga automáticamente.
- **`por_encargo`** — pedidos puntuales de tiendas ("mándame estos productos"). En el MVP, Daniel los captura directamente fila por fila en el módulo de Odoo. El MCP no participa en este tipo en el MVP.

El MCP lee `x_traspasos` (de ambos tipos, con `state=verificado`) para calcular `existencia_despues_traspasos` y hacer el pedido final (Paso 3). Las vendedoras hacen la salida/entrada física en Odoo — el MCP nunca auto-valida pickings.

**La decisión crítica no es solo cuánto pedir.** Es determinar primero si conviene pedir, reducir, eliminar, liquidar o traspasar.

---

## Stack tecnológico

- **Lenguaje:** Python 3.11+
- **MCP SDK:** `mcp` (paquete oficial — `pip install mcp`)
- **Framework MCP:** `FastMCP` de `mcp.server.fastmcp`
- **Conexión Odoo:** `xmlrpc.client` (built-in Python) para XML-RPC
- **Validación inputs:** `pydantic` v2 (`BaseModel`, `Field`, `field_validator`)
- **Excel:** `openpyxl` para reportes auditables
- **Config:** `python-dotenv` para variables de entorno
- **Logging:** `logging` estándar (stderr) + bitácora JSONL

> **Nota:** `xmlrpc.client` es síncrono. Los tools MCP son funciones sync normales. No usar `async def` para tools que llamen a Odoo.

---

## Estructura del proyecto

```
soyaquarius-mcp/
├── CLAUDE.md
├── PROPUESTA_TECNICA.md
├── .env.example
├── .env                        ← NO commitear nunca
├── .gitignore
├── pyproject.toml
├── requirements.txt
├── server.py                   ← Entry point del servidor MCP
│
├── src/
│   ├── __init__.py
│   │
│   ├── config/
│   │   ├── __init__.py
│   │   ├── settings.py                      ← Lee .env y valida variables
│   │   └── proveedores_quincenales.json     ← Lista de proveedores con freq. quincenal
│   │
│   ├── odoo/
│   │   ├── __init__.py
│   │   ├── connector.py        ← OdooConnector: XML-RPC auth + CRUD
│   │   └── models.py           ← Dataclasses para modelos Odoo
│   │
│   ├── tools/
│   │   ├── __init__.py
│   │   ├── generic.py          ← odoo_search, odoo_read, odoo_create, odoo_write, etc.
│   │   ├── compras.py          ← compras_get_ventas_anio, compras_calcular_stock_sugerido, etc.
│   │   ├── traspasos.py        ← traspasos_verificar_cedis, traspasos_calcular_plan, etc.
│   │   ├── pedidos.py          ← pedidos_crear_registros, pedidos_actualizar_reabastecimiento, etc.
│   │   └── reportes.py         ← reportes_generar_excel_paso1/2/3/costeo
│   │
│   ├── engines/
│   │   ├── __init__.py
│   │   ├── purchase_planner.py    ← PurchasePlanner: stock sugerido, ABC, picos
│   │   ├── transfer_planner.py    ← TransferPlanner: CEDIS → rezagados → activos
│   │   ├── orderpoint_updater.py  ← OrderpointUpdater: qty_to_order, Paso 3
│   │   └── validation_engine.py   ← ValidationEngine: sanity checks
│   │
│   └── audit/
│       ├── __init__.py
│       └── logger.py           ← AuditLogger: bitácora JSONL por corrida
│
└── tests/
    ├── test_purchase_planner.py
    ├── test_transfer_planner.py
    └── test_odoo_connector.py
```

---

## Variables de entorno (.env)

```env
ODOO_URL=http://tu-servidor-odoo:8069
ODOO_DB=nombre_de_la_base_de_datos
ODOO_USERNAME=tu_usuario@email.com
ODOO_PASSWORD=tu_contraseña_odoo
OUTPUT_DIR=./outputs
```

Nunca hardcodear credenciales. Siempre leer desde `.env` via `python-dotenv`.

---

## Cómo funciona el servidor MCP

`server.py` inicia un servidor MCP con `FastMCP`. Cada "tool" es una función Python registrada con `@mcp.tool()`. Los tools se agrupan por módulo y se registran llamando `modulo.register(mcp, odoo)`.

### Patrón de registro de tools

```python
# server.py
from mcp.server.fastmcp import FastMCP
from src.odoo.connector import OdooConnector
from src.tools import generic, compras, traspasos, pedidos, reportes

mcp = FastMCP("soyaquarius_mcp")

def _build_server() -> None:
    settings.validate()
    settings.ensure_output_dir()
    odoo = OdooConnector()
    generic.register(mcp, odoo)
    compras.register(mcp, odoo)
    traspasos.register(mcp, odoo)
    pedidos.register(mcp, odoo)
    reportes.register(mcp, odoo)
```

### Nombre del servidor

Seguir convención mcp-builder: `soyaquarius_mcp` (snake_case, sin versiones).

---

## Patrones de código obligatorios (mcp-builder)

### 1. Pydantic para validar inputs de tools

Todo tool que reciba parámetros no triviales debe usar `BaseModel`:

```python
from pydantic import BaseModel, Field, field_validator, ConfigDict
from typing import Optional

class BusquedaOdooInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    model: str = Field(..., description="Nombre del modelo Odoo (ej. 'stock.quant')", min_length=1)
    domain: list = Field(default_factory=list, description="Dominio Odoo (ej. [['location_id.usage','=','internal']])")
    fields: list[str] = Field(..., description="Lista de campos a retornar")
    limit: int = Field(default=100, description="Máximo de registros. 0 = sin límite", ge=0)
    order: str = Field(default="", description="Ordenamiento (ej. 'name asc')")
```

### 2. Annotations en cada tool

```python
@mcp.tool(
    name="odoo_search",
    annotations={
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
def odoo_search(params: BusquedaOdooInput) -> list:
    """Busca y lee registros en cualquier modelo de Odoo.
    ...
    """
    return odoo.search_read(...)
```

### 3. Tabla de annotations por tipo de tool

| Tool tipo | readOnly | destructive | idempotent | openWorld |
|-----------|----------|-------------|------------|-----------|
| Consulta/lectura | True | False | True | True |
| Creación | False | False | False | True |
| Escritura/update | False | True | False | True |
| Ejecución método | False | True | False | True |

### 4. Manejo de errores consistente

```python
def _odoo_error(e: Exception) -> str:
    from src.odoo.connector import OdooConnectionError
    if isinstance(e, OdooConnectionError):
        return f"Error Odoo: {e}"
    return f"Error inesperado: {type(e).__name__}: {e}"
```

Siempre retornar strings con "Error: ..." para que Claude pueda leer el problema.

### 5. Docstrings con schema de retorno

```python
def compras_calcular_stock_sugerido(params: StockSugeridoInput) -> str:
    """Calcula el stock sugerido (Paso 1) para todos los productos de un proveedor en todas las tiendas.

    Args:
        params: proveedor (str), fecha_inicio (str ISO), fecha_fin (str ISO)

    Returns:
        JSON string con schema:
        {
            "proveedor": str,
            "tiendas": [
                {
                    "tienda": str,
                    "productos": [
                        {
                            "product_id": int,
                            "nombre": str,
                            "rotacion": "Activo"|"Rezagado"|"Critico"|"Nunca_entrado",
                            "abc": "A"|"B"|"C",
                            "patron": "80_20"|"pico_sostenido"|"pico_aislado"|"regular",
                            "ventas_3m": [int, int, int],
                            "existencia_actual": float,
                            "nuevo_maximo": int,
                            "nuevo_minimo": int
                        }
                    ]
                }
            ]
        }
    """
```

---

## Modelos de Odoo relevantes

| Modelo | Uso en el MCP |
|--------|---------------|
| `pos.order` | Pedidos POS por tienda y periodo |
| `pos.order.line` | Líneas de venta: producto, qty, precio, tienda |
| `pos.config` | Configuración de cada tienda POS |
| `stock.quant` | Existencia real por producto y ubicación |
| `arsabe_quant` | **Modelo custom** — existencia extendida: última entrada, última salida, días sin movimiento |
| `stock.location` | Ubicaciones: tiendas, CEDIS, virtuales |
| `stock.warehouse.orderpoint` | Reglas de reorden: min, max, qty_to_order |
| `stock.picking` | Traspasos/movimientos internos y externos |
| `stock.move` | Líneas de movimiento dentro de un picking |
| `purchase.order` | Pedido al proveedor |
| `purchase.order.line` | Líneas del pedido a proveedor |
| `product.product` | Productos (variante) |
| `product.template` | Plantilla de productos |
| `res.partner` | Proveedores / clientes |
| `x_pedidos` | **Módulo custom** — registros de Paso 3 para aprobación de Daniel |
| `x_traspasos` | **Módulo custom** — registros de traspasos (por proveedor y por encargo). Campos: `tipo` (por_proveedor/por_encargo), `proveedor`, `product_id`, `ref_interna`, `origen`, `destino`, `cantidad_propuesta` (readonly — calculada por IA), `cantidad_final` (editable solo por generador de pickings), `dias_sin_venta`, `comentarios` (visible para vendedoras), `state` (borrador/verificado/ejecutado/cancelado), `picking_id`. Vistas: **activa** (borrador+verificado) y **historial** (ejecutado+cancelado). |

> **`arsabe_quant`** es un modelo personalizado de SoyAquarius. Extiende `stock.quant` con campos de auditoría de movimiento. Siempre preferir `arsabe_quant` sobre `stock.quant` cuando se necesite `ultima_entrada`, `ultima_salida` o `dias_sin_movimiento`.

---

## Catálogo completo de tools MCP

### Genéricos (Sprint 1)
| Tool | Descripción |
|------|-------------|
| `odoo_search` | Busca y lee registros de cualquier modelo |
| `odoo_read` | Lee registros por IDs |
| `odoo_create` | Crea un registro, retorna el nuevo ID |
| `odoo_write` | Actualiza registros existentes |
| `odoo_call_method` | Ejecuta un método de negocio sobre registros |
| `odoo_get_fields` | Retorna definición de campos de un modelo |
| `odoo_search_count` | Cuenta registros sin traer datos |

### Compras (Sprint 2)
| Tool | Descripción |
|------|-------------|
| `compras_get_ventas_anio` | Ventas del año en curso por proveedor, tienda y mes |
| `compras_get_orderpoints` | Reglas de reorden actuales por proveedor/tienda |
| `compras_calcular_stock_sugerido` | **Paso 1** — stock sugerido completo (rotación, ABC, picos) |
| `compras_get_calendario` | Retorna calendario del proveedor (semanal/quincenal/mensual) |

### Traspasos (Sprint 3)
| Tool | Descripción |
|------|-------------|
| `traspasos_verificar_cedis` | Verifica existencia en CEDIS por producto/proveedor |
| `traspasos_calcular_plan` | **Paso 2** — plan de traspasos (CEDIS → rezagados → activos) |
| `traspasos_cargar_modulo` | Carga el plan como filas `por_proveedor` en `x_traspasos` con `state=borrador` (un registro por línea). No crea pickings. |
| `traspasos_get_estado` | Consulta filas de `x_traspasos` por proveedor: borradores, verificados, comentarios de vendedoras |
| `traspasos_generar_pickings` | Lee `x_traspasos` con `state=verificado` y crea `stock.picking` en borrador en Odoo en lote. Solo lo ejecuta el generador de pickings. |

### Pedidos / Orderpoints (Sprint 4)
| Tool | Descripción |
|------|-------------|
| `pedidos_crear_registros` | **Paso 3** — carga resultados al módulo `x_pedidos` |
| `pedidos_actualizar_reabastecimiento` | Daniel aprueba: actualiza `stock.warehouse.orderpoint` |
| `pedidos_get_estado` | Consulta estado actual de registros en `x_pedidos` |

### Reportes (Sprint 4)
| Tool | Descripción |
|------|-------------|
| `reportes_generar_excel_paso1` | Excel de stock sugerido (Paso 1) |
| `reportes_generar_excel_paso2` | Excel de plan de traspasos (Paso 2) |
| `reportes_generar_excel_paso3` | Excel de orderpoints actualizados (Paso 3) — importable en Odoo |
| `reportes_generar_costeo` | Excel de costeo (Paso 4) — valores y margen del pedido |

### Seguridad y auditoría (Sprint 4)
| Tool | Descripción |
|------|-------------|
| `audit_registrar_accion` | Registra una acción en la bitácora JSONL |
| `validation_validar_corrida` | Valida que todos los insumos de una corrida estén completos |

---

## Reglas de negocio críticas

### Clasificación de rotación

```python
def clasificar_rotacion(dias_sin_venta: int, tiene_ventas: bool, tiene_existencia: bool, tiene_entradas: bool) -> str:
    if not tiene_ventas and not tiene_existencia and not tiene_entradas:
        return "Nunca_entrado"
    if dias_sin_venta <= 100:
        return "Activo"
    elif dias_sin_venta <= 180:
        return "Rezagado"
    else:
        return "Critico"
```

### Catálogo ABC

- Calculado sobre ventas del año en curso (1 enero → último día disponible).
- **NUNCA** desde el archivo del proveedor en proceso. SIEMPRE desde el catálogo general de la tienda.
- A = top 80% de ventas, B = siguiente 15%, C = resto (larga cola).

### Patrones de venta y cálculo de nuevo máximo

```python
def detectar_patron(ventas_3m: list[float], abc: str) -> str:
    promedio = sum(ventas_3m) / len(ventas_3m)
    pico = max(ventas_3m)
    mes_actual = ventas_3m[-1]  # mes en curso: referencia, no extrapolar

    if abc == "A":
        return "80_20"
    if pico >= promedio * 2:
        # ¿El pico sigue? (mes más reciente también es alto)
        if mes_actual >= promedio * 1.5:
            return "pico_sostenido"
        else:
            return "pico_aislado"
    return "regular"

def calcular_nuevo_maximo(ventas_3m: list[float], patron: str) -> int:
    promedio = sum(ventas_3m) / len(ventas_3m)
    pico = max(ventas_3m)

    if patron == "80_20":
        resultado = promedio * 2
    elif patron == "pico_sostenido":
        resultado = pico
    elif patron == "pico_aislado":
        resultado = promedio * 1.5
    else:  # regular
        resultado = promedio

    redondeado = round(resultado)  # NUNCA ceil()

    # Si 0 pero demanda real >= 0.33/mes → asignar 1
    if redondeado == 0 and promedio >= 0.33:
        return 1
    return redondeado
```

**Regla crítica:** El stock mínimo SIEMPRE es igual al stock máximo (política SoyAquarius).

### Paso 2 — Traspasos

**Orden de prioridad de origen:**
1. **CEDIS** — siempre verificar primero. La tienda CEDIS puede quedar en 0.
2. **Tiendas Rezagadas/Críticas** — producto con > 100 días sin venta. Pueden quedar en 0.
3. **Tiendas Activas con excedente** — solo cuando `existencia > nuevo_MAX`. NUNCA quedan por debajo de su nuevo_MAX.

**Destino:**
- Tienda destino debe tener `nuevo_MAX > 0`.
- Cantidad máxima a recibir = `min(nuevo_MAX − existencia − comprometido, ventas_2_meses × 1.5 − existencia − comprometido)`.
- No superar el nuevo_MAX de la tienda destino.
- Priorizar tiendas con menor cobertura proyectada.

**Tiendas excluidas como destino:** `{"BACOAT", "WACO", "CERES"}` — pueden enviar, nunca reciben.

**Piso de eficiencia:** ignorar traspasos < 3 unidades, salvo producto Crítico (>180d) o cobertura destino < 7 días.

### Paso 3 — Pedido final

```python
qty_to_order = max(0, nuevo_maximo - existencia_despues_traspasos)
```

- Si negativo → `qty_to_order = 0`.
- Filas de CEDIS: NO modificar, dejar valores originales.
- Generar Excel importable en `stock.warehouse.orderpoint`.

### Proveedores quincenales

```json
["TONICOL", "OMNILIFE", "RED NATURA", "DXN", "ALINSA", "GENESIS", "MALINGA"]
```

---

## Modos de operación y seguridad

| Modo | Qué permite |
|------|-------------|
| **Lectura** | Consultar ventas, stock, productos, proveedores, orderpoints, movimientos. |
| **Propuesta** | Calcular stock sugerido, traspasos, pedido final y reportes. Sin escribir en Odoo. |
| **Carga en módulo Traspasos** | MCP sube plan `por_proveedor` a `x_traspasos` como `borrador`. Vendedoras comentan y ajustan `cantidad_final`. Sin generar pickings aún. |
| **Generación de Traspasos** | Solo el generador de pickings: tras marcar filas como `verificado`, ejecuta `traspasos_generar_pickings` → crea `stock.picking` en borrador en lote. |
| **Carga en módulo Pedidos** | Subir resultados del Paso 3 a `x_pedidos` para revisión. Sin confirmar en Reabastecimiento. |
| **Actualización en Reabastecimiento** | Solo Daniel puede ejecutar esta acción masiva después de aprobación de tiendas. |

---

## Flujo conversacional completo

Cuando el usuario dice "Claude, prepara el pedido de PROVEEDOR de MES":

1. Verificar calendario del proveedor (semanal/quincenal/mensual).
2. Identificar proveedor, categoría y periodo de análisis.
3. Consultar ventas del año en curso por tienda y mes (`pos.order.line`).
4. Consultar orderpoints actuales y existencia por tienda (`stock.warehouse.orderpoint` + `arsabe_quant`).
5. Calcular stock sugerido — Paso 1 (rotación, catálogo ABC, patrones, nuevo máximo).
6. Verificar si CEDIS puede surtir antes de proponer traspasos.
7. Calcular plan de traspasos — Paso 2 (CEDIS → Rezagadas/Críticas → excedentes Activos).
8. **Cargar plan a `x_traspasos`** (`traspasos_cargar_modulo`) como filas `por_proveedor` en estado `borrador`. → PAUSA.
9. **[PAUSA — Revisión de vendedoras]** Cada vendedora ve las filas que afectan a su tienda, agrega comentarios y ajusta `cantidad_final` si es necesario. También pueden existir filas `por_encargo` cargadas manualmente por Daniel.
10. **[PAUSA — Verificación del generador de pickings]** El generador de pickings revisa el lote, hace ajustes finales en `cantidad_final` y marca filas como `verificado`.
11. Cuando todo está verificado: `traspasos_generar_pickings` crea `stock.picking` en borrador en Odoo en lote. Las filas pasan a `ejecutado`.
12. Las vendedoras hacen la salida/entrada físicamente en Odoo. El MCP no auto-valida pickings.
13. Leer `x_traspasos` con `state=verificado` para calcular `existencia_despues_traspasos` (usa `cantidad_final`).
14. Calcular pedido final al proveedor — Paso 3 (`qty_to_order = max(0, nuevo_max - existencia_despues)`).
15. Mostrar resumen ejecutivo y pedir aprobación.
16. Subir resultados al módulo `x_pedidos`.
17. Cuando Daniel apruebe: actualizar `stock.warehouse.orderpoint`.
18. Generar Excels (Pasos 1-4) y registrar en bitácora.

---

## Orden de desarrollo recomendado

### Sprint 1 — Fundamentos (COMPLETADO)
- [x] `src/odoo/connector.py` — OdooConnector con XML-RPC
- [x] `src/tools/generic.py` — Tools genéricos con Pydantic + annotations
- [x] `server.py` — Servidor MCP funcional
- [x] `src/config/settings.py` — Settings con .env
- [x] `src/odoo/models.py` — Dataclasses Odoo
- [x] `src/audit/logger.py` — AuditLogger JSONL
- [x] `src/config/proveedores_quincenales.json`

### Sprint 2 — Motor de compras
1. `src/engines/purchase_planner.py` — `clasificar_rotacion`, `clasificar_abc`, `detectar_patron`, `calcular_nuevo_maximo`, `PurchasePlanner.calcular(proveedor, tienda, ventas, orderpoints, quants)`
2. `src/tools/compras.py` — `compras_get_ventas_anio`, `compras_get_orderpoints`, `compras_calcular_stock_sugerido`, `compras_get_calendario`
3. Prueba: Claude pregunta el stock sugerido de un proveedor real.

### Sprint 3 — Motor de traspasos (COMPLETADO — pendiente adaptar a nuevo flujo)
- [x] `src/engines/transfer_planner.py` — `TransferPlanner.calcular_plan(productos, tiendas, quants)`
- [x] `src/tools/traspasos.py` — `traspasos_verificar_cedis`, `traspasos_calcular_plan`
- [x] `traspasos_crear_borrador` — DEPRECADO. Reemplazado por `traspasos_cargar_modulo` (Sprint 5b)
- [x] `traspasos_validar` — DEPRECADO. Reemplazado por `traspasos_generar_pickings` (Sprint 5b)
- [ ] **Sprint 5b** — adaptar al nuevo flujo con módulo x_traspasos:
  - `traspasos_cargar_modulo` → carga filas `por_proveedor` en `x_traspasos` con `state=borrador`
  - `traspasos_get_estado` → consulta borradores/verificados/comentarios por proveedor
  - `traspasos_generar_pickings` → lee `state=verificado` → crea `stock.picking` en borrador en lote
  - Módulo Odoo `x_traspasos`: campo `tipo` (por_proveedor/por_encargo), estados (borrador/verificado/ejecutado/cancelado), roles (vendedora/generador), dos vistas (activa/historial)

### Sprint 4 — Pedido final + Excel + Pedidos
7. `src/engines/orderpoint_updater.py` — `OrderpointUpdater.calcular_paso3(paso1, paso2)`
8. `src/engines/validation_engine.py` — `ValidationEngine.validar_corrida(paso1, paso2, paso3)`
9. `src/tools/pedidos.py` — `pedidos_crear_registros`, `pedidos_actualizar_reabastecimiento`, `pedidos_get_estado`
10. `src/tools/reportes.py` — Excel Pasos 1, 2, 3 y Costeo (Paso 4)
11. Prueba: corrida completa de un proveedor quincenal de prueba.

### Sprint 5 — Módulo Odoo x_pedidos (repositorio separado)
12. El módulo `x_pedidos` vive en repo separado (`soyaquarius-odoo-pedidos`).
    Este MCP se comunica con él vía XML-RPC una vez instalado en Odoo.

---

## Configuración en Claude Desktop

`claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "soyaquarius": {
      "command": "python",
      "args": ["/ruta/absoluta/al/proyecto/server.py"],
      "env": {
        "ODOO_URL": "http://...",
        "ODOO_DB": "...",
        "ODOO_USERNAME": "...",
        "ODOO_PASSWORD": "..."
      }
    }
  }
}
```

---

## Preguntas frecuentes para el desarrollo

**¿Cómo testeo sin Odoo disponible?**
Crear `OdooConnectorMock` en `tests/` que devuelva datos ficticios. Los engines deben ser testeables sin conexión real.

**¿Cómo arranco el servidor?**
```bash
python server.py
# Logs van a stderr. El servidor escucha por stdin/stdout (protocolo MCP stdio).
```

**¿Dónde se guardan los Excels?**
En `OUTPUT_DIR` definido en `.env` (default: `./outputs/`).

**¿Cómo redondeo stocks?**
Siempre `round()`. **NUNCA** `ceil()` ni `math.ceil()`.

**¿Cómo manejo el mes en curso en ventas 3M?**
El mes en curso se incluye tal cual (no se extrapola, no se multiplica). Solo como referencia adicional.

**¿Puedo calcular ABC por proveedor?**
No. El catálogo ABC se calcula SIEMPRE desde el catálogo general por tienda, nunca desde el archivo de un proveedor específico.

**¿Qué es `arsabe_quant`?**
Modelo personalizado de SoyAquarius que extiende `stock.quant` con campos: `ultima_entrada` (date), `ultima_salida` (date), `dias_sin_movimiento` (int). Preferir sobre `stock.quant` cuando se necesite info de rotación.
