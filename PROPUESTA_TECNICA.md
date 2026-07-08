# SoyAquarius Naturista | Integración Odoo + Claude MCP

**PROPUESTA TÉCNICA**  
Sistema MCP para Compras, Traspasos y Automatización Operativa en Odoo

> Integración Odoo 18 Community + Claude mediante Model Context Protocol  
> Junio 2026 — v2.0

---

## 1. Resumen ejecutivo

SoyAquarius Naturista opera con Odoo 18 Community como sistema ERP central. Esta propuesta actualiza la arquitectura técnica para desarrollar un servidor MCP a medida, instalado localmente en cada laptop de los usuarios autorizados, conectado a la instancia de Odoo para automatizar decisiones de compra e inventario mediante Claude.

El objetivo no es únicamente consultar Odoo desde Claude. El objetivo es construir una **capa inteligente de operación**: Claude actúa como interfaz conversacional, el MCP como puente seguro con Odoo y un motor de reglas aplica la metodología interna de compras, traspasos y análisis de stock de SoyAquarius.

| Resultado esperado | Descripción |
|--------------------|-------------|
| **Compras más precisas** | El pedido al proveedor se calcula después de revisar ventas del año, stock, rotación y traspasos posibles. |
| **Menos sobreinventario** | Productos rezagados o críticos se reducen, eliminan o mandan a liquidación antes de volver a pedir. |
| **Mejor redistribución** | Antes de comprar, el sistema sugiere priorizar CEDIS y luego mover producto desde tiendas con excedente. |
| **Operación simple** | Los usuarios pueden pedir análisis, reportes y acciones desde Claude en lenguaje natural. |
| **Trazabilidad** | Cada corrida deja evidencia: reglas aplicadas, datos usados, archivos generados y acciones ejecutadas. |

---

## 2. Contexto técnico de Odoo

La instancia de SoyAquarius utiliza Odoo 18 Community con módulos personalizados para POS, inventario, compras, reglas de reorden, reportes Excel, comisiones, márgenes y traspasos internos.

El MCP debe ser especializado: debe conocer los modelos, módulos y flujos reales de la instancia para aprovechar la lógica existente y evitar duplicar procesos innecesariamente.

| Área | Módulos / modelos relevantes | Uso dentro del MCP |
|------|------------------------------|-------------------|
| **Ventas POS** | `pos.order`, `pos.order.line`, `pos.config` | Consultar ventas por tienda, producto, categoría, proveedor y periodo. |
| **Inventario** | `stock.quant`, `stock.location`, `arsabe_quant` | Consultar existencia real, última entrada, última salida y días sin movimiento. |
| **Reorden** | `stock.warehouse.orderpoint` | Leer y actualizar mínimos, máximos y `qty_to_order`. |
| **Traspasos** | `stock.picking`, `stock.move`, `x_traspasos` | Módulo intermedio de revisión + movimientos internos entre tiendas o desde CEDIS. |
| **Compras** | `purchase.order`, `purchase.order.line` | Crear pedidos a proveedor en borrador o confirmarlos con aprobación. |
| **Módulo Pedidos** | `x_pedidos` (módulo nuevo) | Módulo personalizado donde tiendas ven y aprueban pedidos antes de subir a reabastecimiento. |

---

## 3. Estrategia de usuarios, Claude y configuración local

Dado que por ahora el sistema será utilizado únicamente por **2 personas autorizadas**, la gestión de cuentas de Claude se simplifica significativamente respecto a la propuesta original.

### 3.1 Configuración local del MCP

El MCP se instalará de forma local en la laptop de cada usuario autorizado. Cada laptop tendrá su propia configuración del servidor MCP conectada con las credenciales del usuario Odoo correspondiente en esa máquina.

| Componente | Configuración propuesta |
|------------|------------------------|
| **Servidor MCP** | Instalado localmente en cada laptop autorizada. |
| **Cuenta de Odoo** | Cada laptop usa las credenciales del usuario Odoo correspondiente (variables de entorno locales). |
| **Cuenta de Claude** | Puede ser la misma cuenta de Claude en ambas laptops o cuentas separadas — sin impacto técnico en el MCP. |
| **Trazabilidad** | Cada acción en Odoo queda registrada bajo el usuario Odoo que realizó la operación en esa laptop. |
| **Escalamiento futuro** | Si se agregan más usuarios, el proceso es instalar el MCP en la nueva laptop y configurar las credenciales Odoo. |

---

## 4. Requerimientos de hardware

| Componente | Especificación mínima recomendada |
|------------|----------------------------------|
| **Sistema operativo** | Windows 10/11 (64-bit) o macOS 12+. Linux compatible. |
| **RAM** | 8 GB mínimo. 16 GB recomendado. |
| **Procesador** | Intel Core i5 / AMD Ryzen 5 o superior (6ª generación en adelante). |
| **Almacenamiento** | 500 MB libres para la instalación del MCP y archivos de trabajo. |
| **Conexión a internet** | Requerida para conectarse a la API de Claude y a la instancia de Odoo. |
| **Python** | Versión 3.11+ recomendado para ejecutar el servidor MCP. |
| **Acceso a Odoo** | Acceso de red (local o VPN) a la instancia de Odoo 18 Community. |
| **Navegador web** | Google Chrome o Chromium actualizado para usar Claude en el navegador. |

### 4.1 ¿Se necesita tener la computadora encendida para las automatizaciones?

Sí. Al estar el MCP instalado localmente, la computadora debe estar encendida y con el servidor MCP activo para que se ejecuten las automatizaciones.

- Las tareas de análisis y generación de pedidos se ejecutan manualmente al iniciar una sesión en Claude.
- Si se requieren automatizaciones programadas, se puede configurar una tarea programada en el sistema operativo (`cron` en macOS/Linux, Programador de tareas en Windows).
- **Alternativa futura:** migrar el MCP a un servidor en la nube o al mismo servidor de Odoo.

---

## 5. Actualización de reglas de lógica del MCP

### 5.1 ¿Cómo se cambia la lógica del MCP?

Las reglas de negocio críticas viven en el motor de reglas del MCP como código programado.

| Tipo de cambio | Cómo se hace |
|----------------|-------------|
| Cambiar una regla de negocio (umbral de días rezagado, multiplicadores de stock) | Se edita directamente en el código del motor de reglas. Requiere reiniciar el servidor MCP. |
| Agregar un nuevo proveedor quincenal o cambiar calendario | Se actualiza el archivo de configuración del calendario de proveedores (JSON). |
| Ajuste puntual en una corrida específica | Claude puede recibir una instrucción en lenguaje natural para esa corrida puntual. El cambio aplica solo a esa sesión. |
| Agregar una nueva herramienta MCP | Se desarrolla e integra como nueva función del servidor MCP. Requiere desarrollo técnico. |

---

## 6. Problema operativo

El proceso actual requiere navegar varias pantallas, descargar reportes, cruzar información y usar Claude manualmente. Esto genera fricción, consume tiempo y aumenta el riesgo de errores.

Pasos del proceso manual actual:

1. Revisar el calendario de proveedores para saber qué proveedor toca pedir.
2. Consultar ventas del año en curso por proveedor, tienda y mes.
3. Revisar existencia actual, última entrada y días sin movimiento por tienda.
4. Exportar reglas de reorden desde Odoo.
5. Calcular stock sugerido aplicando la metodología interna.
6. Proponer traspasos priorizando CEDIS y luego excedentes entre tiendas.
7. Calcular el pedido final al proveedor.
8. Subir resultados al módulo de Pedidos en Odoo para aprobación.

**La decisión crítica no es solo cuánto pedir.** Es determinar primero si conviene pedir, reducir, eliminar, liquidar, o traspasar producto.

---

## 7. Solución propuesta

Desarrollar un sistema compuesto por tres capas principales:

```
Claude (interfaz conversacional)
        ↓
Servidor MCP (local en cada laptop)
        ↓
Motor de reglas de compras y traspasos
        ↓
Conector Odoo 18 Community
        ↓
Odoo 18 / POS / Inventario / Compras / Reorden / Módulo Pedidos
```

| Capa | Responsabilidad |
|------|----------------|
| **Claude** | Interacción en lenguaje natural, explicación de resultados, solicitud de aprobación y generación de reportes. |
| **Servidor MCP (local)** | Exponer herramientas seguras para consultar y ejecutar acciones sobre Odoo. Corre localmente en cada laptop. |
| **Motor de reglas** | Aplicar la metodología de compras, traspasos, stock sugerido, catálogo ABC y orderpoints. |
| **OdooConnector** | Conectarse a Odoo 18 Community mediante XML-RPC/JSON-RPC y ejecutar métodos autorizados. |
| **Odoo 18 Community** | Sistema fuente de datos y sistema de registro operativo, incluyendo el nuevo módulo de Pedidos. |

---

## 8. Motor de reglas para compras

### 8.1 Catálogo ABC — Cálculo de clasificación

El catálogo ABC se calcula con las ventas del año en curso (del 1 de enero al último día disponible). El resultado clasifica cada combinación (tienda × producto) como A (80/20), B, o C (larga cola).

**Regla crítica:** el 80/20 de una tienda NUNCA se calcula desde el archivo del proveedor que se está procesando. SIEMPRE se consulta el catálogo ABC por tienda.

### 8.2 Paso 1 — Stock sugerido

El motor calculará el nuevo stock máximo por producto y tienda usando:

- Ventas de los últimos 3 meses completos disponibles.
- El mes en curso se incluye tal cual, sin extrapolar ni multiplicar, solo como referencia adicional.
- Existencia actual, días sin venta, última entrada y clasificación de rotación.

**Clasificación de rotación:**

| Clasificación | Criterio y acción sugerida |
|---------------|---------------------------|
| **Activo** | ≤ 100 días sin venta. Mantener o ajustar según demanda. |
| **Rezagado** | 100 a 180 días sin venta. Reducir, traspasar o eliminar. |
| **Crítico** | Más de 180 días sin venta. Eliminar del stock sugerido o mandar a liquidación. |
| **Nunca entrado** | Sin ventas, sin existencia y sin última entrada. No pedir. |

**Patrones de venta y reglas de cálculo:**

| Patrón de venta | Regla de cálculo |
|----------------|-----------------|
| **Producto 80/20 (A — constante alto sostenido)** | Nuevo máximo = promedio 3M × 2 |
| **Pico sostenido** | Un mes vendió ≥ 2× el promedio Y sigue vendiendo. Nuevo máximo = el pico (mes más alto). |
| **Pico aislado** | Un mes vendió mucho pero luego cayó a 0. Nuevo máximo = promedio 3M × 1.5 |
| **Producto regular** | Ventas estables. Nuevo máximo = promedio 3M (sin multiplicar). |

**Reglas adicionales:**

- El stock mínimo será igual al stock máximo siempre (política operativa de SoyAquarius).
- El redondeo será estándar con `round()`. Nunca se usará `ceil()` por defecto.
- Si el resultado es 0 pero el producto vende al menos 1 pieza cada 3 meses (demanda ≥ 0.33/mes), se asignará mínimo 1.

### 8.3 Paso 2 — Traspasos entre tiendas

Antes de pedir al proveedor, el sistema verifica si el faltante puede cubrirse redistribuyendo inventario existente.

**Orden de prioridad de origen:**

| Prioridad | Descripción |
|-----------|-------------|
| **1° CEDIS** | Siempre se verifica primero si CEDIS tiene existencia disponible. |
| **2° Tiendas Rezagadas / Críticas** | Tiendas con producto con > 100 días sin venta. La tienda origen puede quedar en 0. |
| **3° Tiendas Activas con excedente** | Solo cuando `existencia > nuevo_MAX`. La tienda activa NUNCA queda por debajo de su nuevo_MAX. |

**Reglas de destino:**

- La tienda destino debe tener nuevo stock máximo > 0.
- La cantidad máxima a recibir es el menor entre: `nuevo_MAX − existencia − comprometido` y `ventas_2_meses × 1.5 − existencia − comprometido`.
- La suma total recibida no puede superar el nuevo stock máximo de la tienda destino.
- Se priorizan tiendas con menor cobertura proyectada.

**Tiendas excluidas como destino:** BACOAT, WACO, CERES — nunca reciben traspasos. Pueden enviar.

**Piso de eficiencia:** no se realizan traspasos de menos de 3 unidades, salvo que el producto esté Crítico (>180d) o el destino tenga cobertura < 7 días.

### 8.4 Paso 3 — Pedido final y actualización de orderpoint

- `qty_to_order = nuevo stock máximo − existencia después de traspasos`
- Si el resultado es negativo, `qty_to_order = 0`.
- Las filas de CEDIS no se modifican, se dejan con valores originales.
- El sistema genera un Excel compatible con importación de Odoo (`stock.warehouse.orderpoint`).

### 8.5 Proveedores con pedidos quincenales

| Proveedor | Frecuencia |
|-----------|-----------|
| TONICOL | Quincenal |
| OMNILIFE | Quincenal |
| RED NATURA | Quincenal |
| DXN | Quincenal |
| ALINSA | Quincenal |
| GENESIS | Quincenal |
| MALINGA | Quincenal |

---

## 9. Nuevo módulo de Odoo: "Traspasos" (x_traspasos)

Se desarrollará un módulo en Odoo 18 Community llamado **Traspasos** (`x_traspasos`) que reemplaza el Excel del Drive como espacio de coordinación entre el MCP, las tiendas y el responsable de pickings.

### 9.1 Dos tipos de traspaso en un solo módulo

| Tipo | Origen | ¿Quién carga? |
|------|--------|--------------|
| `por_proveedor` | Calculado por la IA al correr el Paso 2 de un proveedor | El MCP automáticamente vía `traspasos_cargar_modulo` |
| `por_encargo` | Pedido puntual de una tienda ("mándame estos productos") | Daniel, manualmente fila por fila en Odoo (MVP) |

El campo `tipo` solo etiqueta el origen. El flujo posterior (revisión, verificación, generación de pickings) es idéntico para ambos tipos.

### 9.2 Estados de una fila

| Estado | Significado |
|--------|-------------|
| `borrador` | La IA o un usuario cargó la fila. Espera revisión y comentarios de las tiendas. |
| `verificado` | El generador de pickings revisó, ajustó y marcó la fila como lista para ejecutar. |
| `ejecutado` | Ya se generó el picking en Odoo. Pasa al historial. |
| `cancelado` | La fila ya no aplica. Queda registrada para auditoría. |

### 9.3 Roles y permisos

| Rol | Permisos |
|-----|---------|
| **Vendedora de tienda** | Ve solo las filas que afectan a su tienda (origen o destino). Puede agregar comentarios. No puede editar cantidades ni generar pickings. |
| **Generador de pickings** | Ve todas las filas. Puede editar `cantidad_final`, marcar `verificado`, ejecutar "Generar pickings" y cancelar filas. |

### 9.4 Vistas del módulo

- **Vista activa (por defecto):** muestra filas en estado `borrador` y `verificado` — lo que requiere acción. Vendedoras ven solo su tienda.
- **Vista historial:** muestra filas en estado `ejecutado` y `cancelado`, filtrable por fecha, proveedor y tienda. Las filas nunca se borran.

### 9.5 Campos principales

| Campo | Descripción | ¿Editable? |
|-------|-------------|-----------|
| `tipo` | `por_proveedor` o `por_encargo` | No |
| `proveedor` | Nombre del proveedor | No |
| `product_id` | Producto | No |
| `origen` | Tienda de origen | No |
| `destino` | Tienda de destino | No |
| `cantidad_propuesta` | Cantidad calculada por la IA | No |
| `cantidad_final` | Cantidad ajustada final | Solo generador de pickings |
| `comentarios` | Comentarios de las tiendas | Vendedoras y generador |
| `state` | Estado de la fila | Automático / generador |
| `picking_id` | Referencia al picking creado | Automático |

### 9.6 Conexión con el Paso 3 (pedido al proveedor)

El Paso 3 calcula `qty_to_order = nuevo_máximo − existencia_después_de_traspasos`. La `existencia_después_de_traspasos` se proyecta leyendo las `cantidad_final` de las filas con `state=verificado` en `x_traspasos`. Esto garantiza que el pedido al proveedor no incluya producto que ya va a llegar vía traspaso, aunque los pickings aún estén en borrador y las vendedoras no hayan hecho la salida/entrada física.

### 9.7 MVP para traspasos por encargo

En el MVP, los traspasos `por_encargo` se capturan directamente en el módulo de Odoo, fila por fila, por Daniel. El MCP no participa en la carga de encargos en el MVP. La carga masiva desde Claude queda para un sprint posterior.

---

## 10. Nuevo módulo de Odoo: "Pedidos" (x_pedidos)

Se desarrollará un nuevo módulo en Odoo 18 Community llamado **Pedidos** (`x_pedidos`) donde los trabajadores de cada tienda podrán ver y aprobar los pedidos calculados por el sistema.

### 9.1 Descripción del módulo

- Es un módulo de solo lectura para la mayoría de los campos, **excepto la columna "Propuesta Máximo"** que los trabajadores de tienda pueden editar.
- Muestra los resultados del Paso 3 (orderpoint actualizado) para cada proveedor procesado.
- El usuario **Daniel** (usuario específico con permisos de administración) puede seleccionar todos los registros y pulsar un botón para actualizar los orderpoints en el módulo de Reabastecimiento oficial.

### 9.2 Columnas del módulo

| Columna | Descripción | ¿Editable? |
|---------|-------------|-----------|
| `id` | ID del registro de reabastecimiento en Odoo. | No |
| `product_id` | Código y nombre del producto. | No |
| `location_id` | Tienda / ubicación. | No |
| `route_id` | Ruta de reabastecimiento. | No |
| `product_min_qty` | Mínimo calculado (= máximo por política). | No |
| `product_max_qty` | Máximo calculado por el motor de reglas. | No |
| **Propuesta Máximo** | Máximo propuesto — ajustable por la tienda. | **SÍ** |
| `qty_to_order` | Cantidad a pedir al proveedor. | No |
| Existencia antes de traspasos | Stock original. | No |
| Existencia después de traspasos | Stock final. | No |
| Cobertura final (días) | Días proyectados de cobertura. | No |
| Notas | Explicación breve del movimiento aplicado. | No |

### 9.3 Flujo de aprobación por Daniel

1. Los registros se cargan en el módulo con estado 'Pendiente de revisión'.
2. Cada tienda puede revisar y ajustar la columna Propuesta Máximo.
3. Daniel selecciona todos los registros y pulsa 'Actualizar en Reabastecimiento'.
4. El sistema actualiza automáticamente los registros de `stock.warehouse.orderpoint` en Odoo.
5. El sistema registra en bitácora quién aprobó, fecha y registros actualizados.

### 9.4 Permisos del módulo

| Rol / Usuario | Permisos |
|--------------|---------|
| **Trabajadores de tienda** | Ver registros de su tienda. Editar únicamente Propuesta Máximo. |
| **Daniel (administrador)** | Ver todos los registros. Ejecutar el botón de actualización en Reabastecimiento. |
| **Compras / Inventario** | Ver todos los registros. Sin permiso de actualizar en Reabastecimiento. |

---

## 10. Flujo conversacional propuesto

**Ejemplo de instrucción del usuario:**
> *"Claude, prepara el pedido de PRONASOYA de junio."*

**Flujo esperado:**

1. Revisar calendario de proveedores y confirmar si es semanal, quincenal o mensual.
2. Identificar proveedor, categoría y periodo de análisis.
3. Consultar ventas del año en curso por tienda y mes.
4. Consultar orderpoints actuales y existencia por tienda.
5. Calcular nuevo stock sugerido (patrón de venta, catálogo ABC, picos, rezagados).
6. Verificar si CEDIS puede surtir antes de proponer traspasos.
7. Proponer traspasos entre tiendas (Rezagadas/Críticas primero, luego excedentes Activos).
8. **Cargar plan a `x_traspasos`** como filas `por_proveedor` en estado `borrador`. → PAUSA.
9. **[PAUSA — Vendedoras]** Cada vendedora ve las filas de su tienda, comenta y ajusta `cantidad_final` si es necesario. Pueden convivir filas `por_encargo` cargadas por Daniel.
10. **[PAUSA — Generador de pickings]** Revisa el lote, hace ajustes finales y marca cada fila como `verificado`.
11. El generador de pickings ejecuta "Generar pickings" → el MCP crea los `stock.picking` en borrador en Odoo en lote. Filas pasan a `ejecutado`.
12. Las vendedoras hacen la salida/entrada físicamente en Odoo. El MCP no auto-valida pickings.
13. El MCP lee `x_traspasos` con `state=verificado` para proyectar `existencia_después_de_traspasos` (usa `cantidad_final`).
14. Calcular pedido final al proveedor con la existencia proyectada.
15. Mostrar resumen ejecutivo y pedir aprobación.
16. Subir resultados al módulo `x_pedidos` en Odoo.
17. Cuando Daniel apruebe, actualizar los orderpoints en Reabastecimiento.
18. Generar Excel de respaldo y bitácora.

---

## 11. Arquitectura de despliegue

| Elemento | Decisión propuesta |
|----------|-------------------|
| **Ubicación del MCP** | Instalación local en cada laptop autorizada. |
| **Comunicación MCP → Odoo** | Conexión directa vía XML-RPC o JSON-RPC (por red local o VPN). |
| **Acceso de usuarios** | Cada usuario inicia el MCP localmente y usa Claude desde el navegador o app. |
| **Usuarios estimados MVP** | 2 personas con acceso al MCP. |
| **Identidad operativa** | Cada laptop usa las credenciales Odoo del usuario correspondiente. |
| **Seguridad** | Variables de entorno locales para credenciales. Conexión HTTPS o VPN a Odoo. Logs de operaciones. |
| **Odoo Community 18** | Sin costo de licencia. Módulos personalizados desarrollados sobre la versión Community. |

---

## 12. Componentes técnicos

### 12.1 Servidor MCP — Herramientas expuestas

| Tipo | Herramientas |
|------|-------------|
| **Genéricas** | `odoo_search`, `odoo_read`, `odoo_create`, `odoo_write`, `odoo_call_method`, `odoo_get_fields` |
| **Compras** | `compras_get_ventas_anio`, `compras_get_orderpoints`, `compras_calcular_stock_sugerido`, `compras_get_calendario` |
| **Traspasos** | `traspasos_verificar_cedis`, `traspasos_calcular_plan`, `traspasos_cargar_modulo`, `traspasos_get_estado`, `traspasos_generar_pickings` |
| **Módulo Pedidos** | `pedidos_crear_registros`, `pedidos_actualizar_reabastecimiento`, `pedidos_get_estado` |
| **Reportes** | `reportes_generar_excel_paso1`, `reportes_generar_excel_paso2`, `reportes_generar_excel_paso3`, `reportes_generar_costeo` |
| **Seguridad** | `auth_validar_usuario_odoo`, `audit_registrar_accion`, `validation_validar_corrida` |

### 12.2 PurchasePlanner

Motor responsable de calcular el stock sugerido por producto y tienda. Implementa la metodología de ventas del año en curso, clasificación de rotación, detección de picos (sostenidos vs aislados), catálogo ABC y cálculo de mínimo/máximo.

### 12.3 TransferPlanner

Motor responsable de proponer traspasos entre tiendas. Prioriza siempre primero el surtido desde CEDIS, luego busca tiendas origen con producto rezagado o crítico, y finalmente evalúa excedentes en tiendas activas.

### 12.4 OrderpointUpdater

Motor responsable de preparar la actualización de reglas de reabastecimiento (Paso 3) y cargar los resultados en el módulo de Pedidos para aprobación. Calcula `product_min_qty`, `product_max_qty` y `qty_to_order` después de aplicar traspasos.

### 12.5 Módulo Odoo "Pedidos" (x_pedidos)

Módulo personalizado desarrollado en Odoo 18 Community. Recibe los resultados del Paso 3, los muestra a los trabajadores con permisos de lectura (y edición solo en Propuesta Máximo), y permite que Daniel ejecute la actualización masiva de orderpoints con un solo botón.

### 12.6 ValidationEngine

Verifica que existan los insumos requeridos, valida que no haya `qty_to_order` negativos, confirma que unidades enviadas en traspasos sean iguales a unidades recibidas, y compara el Paso 1 contra el Paso 3 para asegurar consistencia de máximos.

### 12.7 AuditLogger

Registra cada corrida: usuario, fecha, proveedor, datos consultados, reglas aplicadas, resultados, aprobaciones, archivos generados y acciones ejecutadas sobre Odoo.

---

## 13. Seguridad, trazabilidad y aprobación humana

| Modo | Qué permite |
|------|------------|
| **Lectura** | Consultar ventas, stock, productos, proveedores, orderpoints y movimientos. |
| **Propuesta** | Calcular stock sugerido, traspasos, pedido final y reportes. |
| **Carga en módulo Traspasos** | MCP sube plan `por_proveedor` a `x_traspasos` como `borrador`. Vendedoras comentan y ajustan. Sin generar pickings aún. |
| **Generación de Traspasos** | Solo el generador de pickings: tras marcar filas como `verificado`, ejecuta creación de `stock.picking` en borrador en lote. |
| **Carga en módulo Pedidos** | Subir resultados del Paso 3 al módulo para revisión de tiendas. Sin confirmar en Reabastecimiento. |
| **Actualización en Reabastecimiento** | Solo Daniel puede ejecutar esta acción masiva después de que las tiendas hayan revisado. |

**Principios de seguridad:**
- No usar una cuenta Odoo administradora compartida para todas las acciones.
- Registrar qué usuario solicita, aprueba y ejecuta cada operación.
- Separar permisos de lectura, propuesta y ejecución.
- Mantener bitácora suficiente para revertir cambios si se detecta error.

---

## 14. Automatización por fases

### Fase 1 — Semi-automatización con archivos

El MCP y Claude ayudan a validar, calcular, generar reportes y preparar acciones. Los archivos exportados desde Odoo se usan como fuente inicial. Los resultados se suben al módulo de Pedidos para aprobación.

### Fase 2 — Automatización directa desde Odoo

El MCP consulta directamente Odoo eliminando la necesidad de descargar archivos manualmente. Consulta ventas desde `pos.order.line`, inventario desde `stock.quant`, reglas desde `stock.warehouse.orderpoint`.

### Fase 3 — Ejecución controlada en Odoo

Claude puede ejecutar acciones reales mediante el MCP siempre bajo el patrón:

**Analizar → Proponer → Validar → Cargar en módulo Pedidos → Revisar y aprobar (tiendas + Daniel) → Actualizar Reabastecimiento → Reportar**

---

## 15. Entregables

- Servidor MCP desarrollado a medida y configurado para Odoo 18 Community de SoyAquarius.
- Conector Odoo con autenticación, lectura, escritura y ejecución controlada de métodos de negocio.
- Motor de reglas de compras con cálculo de stock sugerido (ventas del año), catálogo ABC, rotación, picos, traspasos priorizados (CEDIS → rezagados → excedentes activos) y pedido final.
- Módulo Odoo 'Pedidos' (`x_pedidos`) con estructura del Paso 3, permisos por rol y botón de actualización para Daniel.
- Automatización de traspasos entre tiendas, inicialmente en borrador.
- Automatización de pedidos a proveedor, inicialmente en RFQ/borrador.
- Generación de archivos Excel auditables para Paso 1, Paso 2, Paso 3 y Costeo (Paso 4).
- Bitácora de operaciones, aprobaciones y acciones ejecutadas.
- Documentación técnica de instalación local, configuración de variables de entorno y permisos.
- Guía de uso para usuarios con ejemplos de prompts.
- Sesión de onboarding y pruebas con usuarios clave.

---

## 16. Plan de implementación

| Fase | Duración y actividades principales |
|------|-----------------------------------|
| **1. Diagnóstico técnico** | 1 semana — Revisar acceso Odoo 18, modelos, campos, proveedores, POS, permisos, calendario y módulos personalizados existentes. |
| **2. MCP base para Odoo** | 2 semanas — Crear servidor MCP local, autenticación, tools genéricos, permisos y pruebas de lectura. |
| **3. Motor de compras** | 2 semanas — Implementar reglas de stock sugerido (ventas del año), catálogo ABC, traspasos (CEDIS + excedentes) y generación Excel. |
| **4. Módulo Pedidos en Odoo** | 1 a 2 semanas — Desarrollar el módulo `x_pedidos` con las columnas del Paso 3, permisos por rol y botón de actualización masiva para Daniel. |
| **5. Ejecución en Odoo** | 1 semana — Crear traspasos y pedidos en borrador, actualización de orderpoints, logs y aprobación humana. |
| **6. Piloto operativo** | 2 semanas — Probar con proveedores reales incluyendo quincenales, comparar contra proceso manual, ajustar reglas y documentar operación. |

---

## 17. MVP recomendado

El MVP es un asistente de pedido por proveedor con aprobación en Odoo. El usuario indica el proveedor y el mes; el sistema analiza ventas del año, calcula stock sugerido, prioriza CEDIS, propone traspasos, calcula pedido final, lo sube al módulo de Pedidos y espera aprobación de Daniel para actualizar el reabastecimiento.

| Incluido en MVP | No incluido en MVP inicial |
|----------------|---------------------------|
| Análisis por proveedor con ventas del año. | Confirmación automática sin aprobación humana. |
| Catálogo ABC calculado con ventas del año en curso. | Uso masivo por los 35 trabajadores desde el primer día. |
| Traspasos priorizados: CEDIS → rezagados → excedentes activos. | Interfaz interna completa tipo chat corporativo. |
| Módulo Pedidos en Odoo con aprobación por Daniel. | Automatización de todos los módulos de Odoo. |
| Soporte para proveedores quincenales (7 proveedores). | Reglas avanzadas no documentadas en el manual. |
| Excel auditable (Pasos 1-4). | Automatización programada sin laptop encendida. |

---

## 18. Conclusión

La recomendación es construir un MCP general para Odoo 18 Community, con un módulo especializado de compras, traspasos y aprobación como primer caso de uso. El valor principal no está solo en consultar Odoo desde Claude, sino en **automatizar el razonamiento operativo** que hoy se hace manualmente, garantizando que el flujo de aprobación humana (módulo Pedidos + Daniel) sea parte integral del proceso antes de modificar el Reabastecimiento oficial.

```
Ventas del año → Stock sugerido → CEDIS primero → Plan de Traspasos
→ x_traspasos (borrador) → Vendedoras comentan/ajustan → Generador verifica
→ Pickings en lote → Pedido final (lee verificados) → x_pedidos → Aprobación Daniel → Reabastecimiento Odoo
```

La configuración local del MCP (2 laptops) simplifica el despliegue inicial y reduce costos. Para el despliegue, se recomienda comenzar con un proveedor mensual de prueba y luego incorporar los 7 proveedores quincenales antes del piloto completo.

---

*Propuesta técnica actualizada | Junio 2026 | v2.0*
