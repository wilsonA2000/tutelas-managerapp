---
description: Test completo del frontend de tutelas-managerapp simulando un usuario real
---

# Testing UI — Agente Juridico IA v3.0

Usa playwright mcp para TODAS las interacciones con el navegador.

## REGLAS OBLIGATORIAS

### Manejo de modales y overlays
- **ProgressModal (overlay oscuro con spinner "Procesando"):** Si aparece, NO interactues con nada debajo. Espera hasta 20 segundos a que termine. Si muestra boton "Cerrar", haz clic en el. Si no aparece boton, haz clic en el fondo oscuro (backdrop) para cerrarlo.
- **AgentChat (panel flotante esquina inferior derecha):** Si el chat esta abierto y bloquea otros elementos, ciérralo con el boton X en el header del chat ANTES de continuar.
- **NotificationCenter (campana de alertas):** Si el panel de alertas se despliega y bloquea navegacion, haz clic fuera para cerrarlo.
- **Cualquier otro modal/dialogo/popup/toast:** Lee su contenido, registralo en el reporte, y cierralo (busca X, "Cerrar", "Aceptar", "OK", "Cancelar").

### Protecciones criticas
- **NUNCA hagas clic en "Sincronizar Carpetas"** — dispara un proceso largo que bloquea la UI.
- **NUNCA hagas clic en "Revisar Gmail"** — conecta a Gmail real y procesa correos reales.
- **NUNCA hagas clic en "Extraer" (individual ni por lotes)** — consume tokens de IA reales y modifica datos.
- **NUNCA elimines ningun caso** — si ves boton de eliminar, verifica que existe pero NO lo uses.
- **NUNCA guardes cambios reales en campos** — si pruebas edicion inline, presiona Escape para cancelar.

### Observabilidad
- Captura errores de consola JavaScript en cada pagina.
- Captura peticiones HTTP con status 4xx o 5xx.
- Toma screenshot ANTES y DESPUES de cada accion importante.
- Si un elemento tarda mas de 10 segundos en cargar, reportalo como posible problema de rendimiento.

---

## FLUJO DE TESTING

### PASO 1: Login
1. Navega a http://localhost:5173
2. Debe aparecer pantalla de login con escudo de la Gobernacion
3. Ingresa usuario: `wilson` y contrasena: `tutelas2026`
4. Haz clic en el boton de login
5. **Verificar:** Redirige al Dashboard. Si da error 401, reportar.

### PASO 2: Dashboard
1. Verifica que cargan los 8 KPIs (no deben mostrar "0", "NaN", "undefined" ni estar vacios)
2. Verifica que las graficas renderizan (deben verse barras, lineas o arcos — no pantalla en blanco)
3. Verifica que la seccion "Actividad reciente" muestra entradas
4. Busca la campana de alertas en el sidebar — verifica que tiene un badge con numero
5. Haz clic en la campana y verifica que se abre un panel de alertas. Luego cierralo.
6. **NO hagas clic en los botones del "Centro de control"** (Revisar Gmail, Extraer, Sincronizar).
7. Captura screenshot del dashboard completo.

### PASO 3: Lista de Tutelas (/cases)
1. Haz clic en "Tutelas" en el sidebar
2. Verifica que la lista carga con casos (segun la guia debe haber ~264)
3. Usa el buscador: escribe "GARCIA" y verifica que aparecen resultados filtrados
4. Limpia la busqueda
5. Aplica filtro por estado "ACTIVO" y verifica que la lista se filtra
6. Haz clic en el primer caso de la lista
7. **Verificar:** Se abre la pagina de detalle del caso (/cases/:id)

### PASO 4: Detalle del Caso
1. Verifica que la pagina carga con datos del caso (no campos completamente vacios)
2. Busca las secciones colapsables y haz clic en al menos 3 para expandirlas
3. Verifica que el panel de documentos lista archivos
4. Verifica que existe un boton de sincronizar carpeta (NO lo uses)
5. Verifica que existe un boton de eliminar caso (NO lo uses)
6. Navega de vuelta a la lista de tutelas

### PASO 5: Cuadro Interactivo (/cuadro)
1. Haz clic en "Cuadro" en el sidebar
2. Verifica que la tabla carga con multiples filas y columnas
3. Haz clic en una celda para verificar que entra en modo edicion
4. Presiona Escape inmediatamente (NO guardes cambios)
5. Prueba escribir en el filtro de una columna y verifica que filtra
6. Haz clic en un header de columna para verificar ordenamiento
7. Verifica si hay campos vacios marcados en rojo

### PASO 6: Extraccion (/extraction)
1. Haz clic en "Extraccion" en el sidebar
2. Verifica que la pagina carga correctamente
3. Verifica que hay una cola de revision (review queue)
4. **NO ejecutes ninguna extraccion** — solo observa la interfaz
5. Verifica que los botones de "Extraer" existen y son clicables (sin hacer clic)

### PASO 7: Correos (/emails)
1. Haz clic en "Correos" en el sidebar
2. Verifica que la lista de correos carga (paginada)
3. Verifica que cada correo muestra: asunto, remitente, estado
4. Si hay correos, haz clic en uno para ver el detalle
5. **NO hagas clic en "Revisar Bandeja"**

### PASO 8: Reportes (/reports)
1. Haz clic en "Reportes" en el sidebar
2. Verifica que hay historial de reportes generados
3. Si hay reportes, verifica que tienen fecha y tamano
4. **NO generes un nuevo reporte** (toma tiempo y genera archivos reales)

### PASO 9: Inteligencia Legal (/intelligence)
1. Haz clic en "Inteligencia" en el sidebar
2. Verifica que hay 3 tabs: Analytics, Calendario, Predictor
3. Haz clic en "Analytics" — verifica que las graficas de favorabilidad cargan
4. Haz clic en "Calendario" — verifica el semaforo de plazos (colores)
5. Haz clic en "Predictor" — ingresa "Bucaramanga" como ciudad y verifica que muestra prediccion
6. Captura screenshot de cada tab

### PASO 10: Agente IA (chat flotante)
1. Busca el boton flotante "Agente IA" en la esquina inferior derecha
2. Haz clic para abrir el chat
3. Verifica que muestra mensaje de bienvenida y comandos rapidos
4. Escribe: "Dame las estadisticas generales"
5. Espera hasta 30 segundos por la respuesta (usa Smart Router con APIs externas)
6. Verifica que responde con datos numericos (no error)
7. Cierra el chat con el boton X

### PASO 11: Herramientas del Agente (/agent)
1. Haz clic en "Agente IA" en el sidebar (no el boton flotante)
2. Verifica que muestra la lista de 15 herramientas organizadas por categoria
3. Verifica categorias: Busqueda, Analisis, Gestion, Extraccion

### PASO 12: Configuracion (/settings)
1. Haz clic en "Configuracion" en el sidebar
2. Verifica el estado de servicios: Gmail, IA, DB, carpetas
3. Registra cuales servicios estan OK y cuales tienen error

### PASO 13: Seguimiento (/seguimiento)
1. Haz clic en "Seguimiento" en el sidebar
2. Verifica que muestra el sistema semaforo de cumplimientos
3. Verifica colores: VENCIDO (rojo), URGENTE (naranja), POR VENCER (amarillo), EN PLAZO (verde), CUMPLIDO (azul)

### PASO 14: Logout
1. Busca el boton rojo "Cerrar sesion" en la parte inferior del sidebar
2. Haz clic en cerrar sesion
3. Verifica que redirige a la pantalla de login

---

## REPORTE FINAL

Genera un reporte estructurado con estas secciones:

### Resumen
- Total de flujos testeados
- Flujos exitosos vs con problemas

### Detalle por flujo
Para cada paso indica:
- ✅ **PASSED** — Flujo completo sin errores
- ⚠️ **WARNING** — Funciona pero con problemas menores (lento, UI fea, texto cortado)
- ❌ **FAILED** — Error real (crash, error de consola, HTTP 500, elemento no encontrado)

### Errores de Consola
Lista todos los errores JavaScript capturados, agrupados por pagina

### Peticiones HTTP Fallidas
Lista todas las peticiones con status 4xx o 5xx

### Screenshots
Lista de screenshots tomados con descripcion

### Problemas de UX
Sugerencias de mejora encontradas durante la navegacion

### Bugs Criticos
Lista priorizada de bugs que necesitan atencion inmediata
