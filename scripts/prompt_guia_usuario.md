# Prompt para Claude Desktop — Generar guía de usuario del MCP SoyAquarius

> Copia todo lo que está debajo de la línea y pégalo en Claude Desktop (con el MCP `soyaquarius` ya conectado).

---

Eres un redactor técnico. Tu tarea es generar un **documento guía completo** (en español, formato Markdown) para que el equipo de **SoyAquarius Naturista** sepa usar el servidor MCP `soyaquarius` conectado a este Claude. El documento va dirigido a personas **no técnicas** (compras, vendedoras, encargado de traspasos, dirección). Escríbelo claro, con ejemplos copiables y sin jerga innecesaria.

Antes de escribir, explora las herramientas MCP disponibles (lista los tools `compras_*`, `traspasos_*`, `pedidos_*`, `reportes_*`, `odoo_*`) para que la guía refleje lo que realmente existe. No ejecutes acciones de escritura; solo lectura/inspección.

El documento debe tener estas secciones:

## 1. ¿Qué es esto y para qué sirve?
Explica en 2-3 párrafos que este MCP conecta a Claude con Odoo para automatizar el proceso de **compras, traspasos de inventario y pedido final** de SoyAquarius. Menciona el flujo central: Ventas del año → Stock sugerido → CEDIS primero → Traspasos → Pedido final → Aprobación. Aclara que Claude nunca valida movimientos físicos ni confirma reabastecimiento por su cuenta.

## 2. Tipos de usuario y qué puede hacer cada uno
Haz una tabla con los roles y sus permisos:
- **Compras / Analista** — corre los cálculos (stock sugerido, traspasos, pedido final), genera reportes. Modo lectura y propuesta.
- **Vendedoras** — revisan las filas de traspasos que afectan a su tienda en el módulo `x_traspasos`, agregan comentarios y ajustan `cantidad_final`. No corren cálculos.
- **Generador de pickings** — verifica el lote de traspasos, hace ajustes finales y marca filas como `verificado`; dispara la generación de `stock.picking` en borrador.
- **Daniel (Dirección)** — único que aprueba y ejecuta la actualización masiva de `stock.warehouse.orderpoint` (reabastecimiento). También captura traspasos `por_encargo` manualmente.

## 3. Cómo pedirle cosas a Claude (instrucciones para escribir prompts)
Da reglas prácticas para redactar buenos prompts:
- Siempre indicar **proveedor**, **periodo** y **paso** que se quiere.
- Ir paso por paso; no pedir todo el flujo de golpe la primera vez.
- Confirmar antes de cargar a módulos o actualizar Odoo.
- Cómo revisar un resultado antes de aprobarlo.

## 4. Prompts listos para usar
Incluye un bloque de prompts copiables para cada etapa del flujo, por ejemplo:
- "Claude, prepara el pedido de [PROVEEDOR] de [MES]." (flujo completo guiado)
- "Muéstrame las ventas del año de [PROVEEDOR] por tienda y mes."
- "Calcula el stock sugerido (Paso 1) de [PROVEEDOR]."
- "Verifica si CEDIS puede surtir [PROVEEDOR] antes de traspasar."
- "Calcula el plan de traspasos (Paso 2) de [PROVEEDOR]."
- "Carga el plan de traspasos al módulo x_traspasos en borrador."
- "Consulta el estado de los traspasos de [PROVEEDOR] (borradores, verificados, comentarios)."
- "Genera los pickings de los traspasos ya verificados de [PROVEEDOR]."
- "Calcula el pedido final (Paso 3) de [PROVEEDOR] usando las cantidades verificadas."
- "Sube el pedido final al módulo x_pedidos para aprobación."
- "Genera los Excel de los Pasos 1, 2, 3 y el costeo."
Para cada prompt, agrega una línea de qué hace y qué devuelve.

## 5. El flujo completo, paso a paso
Explica en lenguaje sencillo los pasos del proceso (del 1 al final): calendario del proveedor → ventas → stock sugerido → CEDIS → traspasos → pausa de vendedoras → verificación del generador → pickings → pedido final → aprobación de Daniel → reabastecimiento → Excel y bitácora. Marca claramente dónde hay **PAUSA** (intervención humana) y dónde actúa Claude.

## 6. Reglas de negocio que conviene conocer
Resume en viñetas, sin fórmulas complejas: qué significa rotación (Activo/Rezagado/Crítico/Nunca entrado), qué es el catálogo ABC, que el stock mínimo siempre es igual al máximo, el orden de origen de traspasos (CEDIS → rezagadas → excedentes de activas), las tiendas que nunca reciben (BACOAT, WACO, CERES), y que las filas de CEDIS no se modifican en el pedido final.

## 7. Preguntas frecuentes y errores comunes
Incluye: qué hacer si Claude no encuentra un proveedor, cómo saber si un proveedor es quincenal, qué hacer si un cálculo se ve raro, y a quién escalar cada tipo de duda.

## 8. Glosario
Define términos clave: CEDIS, orderpoint, picking, x_traspasos, x_pedidos, arsabe_quant, stock sugerido, cantidad_final vs cantidad_propuesta.

Al final, entrega el documento completo en un solo bloque Markdown listo para copiar. Si detectas que algún tool mencionado no existe en la conexión actual, márcalo con una nota en lugar de inventarlo.
