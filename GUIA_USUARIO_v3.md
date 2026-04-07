# GUIA DE USUARIO - AGENTE JURIDICO IA v3.0
## Plataforma de Gestion Juridica de Acciones de Tutela
### Gobernacion de Santander - 2026

---

## TABLA DE CONTENIDO

1. [Inicio Rapido](#1-inicio-rapido)
2. [Login y Seguridad](#2-login-y-seguridad)
3. [Dashboard](#3-dashboard)
4. [Agente IA (Chat Flotante)](#4-agente-ia-chat-flotante)
5. [Herramientas del Agente](#5-herramientas-del-agente)
6. [Tutelas](#6-tutelas)
7. [Cuadro Interactivo](#7-cuadro-interactivo)
8. [Extraccion IA](#8-extraccion-ia)
9. [Correos Gmail](#9-correos-gmail)
10. [Inteligencia Legal](#10-inteligencia-legal)
11. [Reportes](#11-reportes)
12. [Seguimiento de Cumplimientos](#12-seguimiento-de-cumplimientos)
13. [Configuracion y Alertas](#13-configuracion-y-alertas)
14. [Proveedores de IA](#14-proveedores-de-ia)
15. [Flujo de Trabajo Diario](#15-flujo-de-trabajo-diario)
16. [Solucion de Problemas](#16-solucion-de-problemas)

---

## 1. INICIO RAPIDO

### Requisitos
- Windows 10/11 con WSL2 (Ubuntu)
- Python 3.10+
- Node.js 18+
- Conexion a internet (para APIs de IA y Gmail)

### Iniciar la plataforma
```bash
cd "/mnt/c/Users/wilso/Documents/GOBERNACION DE SANTANDER/TUTELAS 2026/tutelas-app"
bash start.sh
```

### URLs
| Servicio | URL |
|----------|-----|
| Frontend | http://localhost:5173 |
| Backend API | http://localhost:8000 |
| Documentacion API | http://localhost:8000/docs |

---

## 2. LOGIN Y SEGURIDAD

La plataforma requiere autenticacion JWT.

- **Usuario:** wilson
- **Contrasena:** tutelas2026
- **Sesion:** 8 horas (se renueva automaticamente)
- **Cambiar contrasena:** Disponible en el perfil

Al entrar veras la pantalla de login con el escudo de la Gobernacion. Despues de autenticarte, el token se guarda automaticamente.

Para **cerrar sesion**, usa el boton rojo en la parte inferior del sidebar.

---

## 3. DASHBOARD

Pagina principal con:
- **8 KPIs principales:** Tutelas activas, favorabilidad, impugnaciones, desacatos
- **Centro de control:** Revisar Gmail, extraer con IA, generar Excel
- **Graficas:** Favorabilidad por juzgado, derechos vulnerados, oficinas, tendencias
- **Actividad reciente:** Ultimas acciones del sistema
- **Metricas de calidad:** Confiabilidad, documentos verificados
- **Campana de alertas:** Esquina superior del sidebar (muestra alertas criticas)

---

## 4. AGENTE IA (CHAT FLOTANTE)

El boton **"Agente IA"** aparece en la esquina inferior derecha de TODAS las paginas.

### Como usarlo
1. Click en el boton flotante azul
2. Escribe tu instruccion en lenguaje natural
3. El agente decide que herramientas usar
4. Ejecuta las herramientas y te muestra resultados

### Ejemplos de instrucciones
| Instruccion | Que hace |
|-------------|----------|
| "Dame las estadisticas generales" | Muestra total de casos, documentos, emails, favorabilidad |
| "Buscar caso personero Guavata" | Busca por radicado, accionante, juzgado o texto |
| "Analizar abogado Cruz" | Rendimiento: casos, activos, tasa de favorabilidad |
| "Escanear alertas criticas" | Detecta plazos vencidos, anomalias, emails sin caso |
| "Predecir resultado para Bucaramanga" | Prediccion basada en datos historicos |
| "Verificar plazo del caso 27" | Calcula dias restantes para cumplimiento |
| "Buscar en Knowledge Base educacion Vetas" | Busca en 2389 entradas (PDFs, emails, DOCX) |
| "Cuanto he consumido en tokens" | Muestra consumo y ahorro vs APIs de pago |
| "Casos por municipio" | Lista agrupada con conteo |

### Boton de ayuda
En el header del chat hay un icono **?** que te lleva a la pagina completa de herramientas con documentacion y ejemplos.

---

## 5. HERRAMIENTAS DEL AGENTE

Pagina **/agent** en el sidebar (icono de llave).

Muestra las **15 herramientas** organizadas por categoria:

### Busqueda (3 herramientas)
- **buscar_caso** — Por radicado, accionante, juzgado o texto libre
- **buscar_conocimiento** — Full-text search en Knowledge Base (2389 entradas)
- **buscar_email** — Por subject, remitente o contenido

### Analisis (5 herramientas)
- **verificar_plazo** — Dias restantes para cumplimiento de fallo
- **predecir_resultado** — Prediccion basada en datos historicos
- **analizar_abogado** — Rendimiento, casos, tasa favorabilidad
- **obtener_contexto** — Contexto completo de un caso (documentos, emails, datos)
- **ver_razonamiento** — Cadena de razonamiento de la ultima extraccion

### Gestion (5 herramientas)
- **estadisticas_generales** — Resumen completo del sistema
- **listar_alertas** — Alertas activas (plazos, anomalias)
- **escanear_alertas** — Ejecutar deteccion de alertas
- **casos_por_municipio** — Agrupacion con conteo
- **consumo_tokens** — Consumo, ahorro, tips de optimizacion

### Extraccion (2 herramientas)
- **extraer_caso** — Extraccion inteligente con Agente IA v3
- **validar_forest** — Verifica si un FOREST es real o alucinado

---

## 6. TUTELAS

Lista paginada de todos los casos (264 actualmente).

- **Buscar** por accionante, radicado, juzgado
- **Filtrar** por estado (ACTIVO/INACTIVO), fallo, ciudad
- **Click en una fila** para ver detalle del caso
- **Sincronizar** carpetas desde disco

### Detalle del caso
- 10 secciones colapsables con 36 campos editables
- Panel de documentos con preview inline
- Boton para sincronizar carpeta individual
- Boton para eliminar caso (con confirmacion)

---

## 7. CUADRO INTERACTIVO

Tabla tipo Excel con TODOS los campos de TODOS los casos.

- **Edicion inline:** Click en celda para editar, Enter para guardar
- **Filtro por columna:** Escribir en el header para filtrar
- **Ordenar:** Click en header de columna
- **Mostrar/ocultar columnas:** Boton de configuracion
- **Campos vacios** se muestran en rojo

---

## 8. EXTRACCION IA (Pipeline Autosuficiente v3.1)

### Que hace el pipeline cuando extraes un caso
1. **Clasifica** cada documento por tipo (RESPUESTA, CONTESTACION, SENTENCIA, SOLICITUD, etc.)
2. **Extrae abogado** de TODOS los DOCX relevantes, prioriza por tipo (RESPUESTA > CONTESTACION)
3. **Verifica** si cada documento pertenece al caso (radicado 23 digitos + accionante)
4. **Mueve automaticamente** documentos que no pertenecen a su carpeta correcta
5. **Crea casos nuevos** si detecta radicados que no existen en la DB
6. **Inyecta correcciones** historicas como aprendizaje antes de llamar a la IA
7. **Etiqueta** documentos con tipo para que la IA sepa de donde extraer cada campo
8. **Valida** cada campo post-IA (ABOGADO solo de DOCX, FALLO solo de sentencia)
9. **Muestra resultados** detallados: campos, tokens, docs movidos, casos creados

### Extraccion individual
Seleccionar caso → "Extraer Caso Individual" → esperar ~1 min → panel de resultados con:
- Campos extraidos con valores
- Documentos procesados / excluidos
- Documentos reasignados a otras carpetas
- Casos nuevos creados automaticamente
- Correcciones historicas inyectadas
- Tokens consumidos y costo

### Extraccion por lotes
- Protegida contra doble-click
- Cada caso que falla va a REVISION (nunca queda trabado en EXTRAYENDO)
- Progreso visible en el modal

### Tipos de DOCX que reconoce
| Tipo | Patron en filename | Extrae abogado? |
|------|-------------------|:---:|
| DOCX_RESPUESTA | respuesta, contestacion, CON FOREST | SI |
| DOCX_DESACATO | respuesta incidente, desacato | SI |
| DOCX_IMPUGNACION | contestacion impugnacion | SI |
| DOCX_CUMPLIMIENTO | cumplimiento fallo | SI |
| DOCX_SOLICITUD | solicitud, insumo | NO |
| DOCX_MEMORIAL | memorial, aclaratorio | NO |
| DOCX_CARTA | carta, oficio | NO |

### Aprendizaje
Cada vez que editas un campo desde el Cuadro o Detalle:
1. La correccion se registra automaticamente
2. La proxima extraccion incluye esa correccion como ejemplo
3. La IA no repite el mismo error

---

## 9. CORREOS GMAIL

- **Revisar Bandeja:** Boton manual para revisar nuevos emails
- **Lista de correos** con estado (pendiente, asignado, ignorado)
- **Detalle** con cuerpo completo, adjuntos, caso vinculado
- **Clasificacion automatica** por tipo (tutela nueva, fallo, impugnacion, etc.)

---

## 10. INTELIGENCIA LEGAL (NUEVO)

Pagina **/intelligence** con 3 tabs:

### Analytics
- **Favorabilidad por juzgado:** Que juzgados conceden mas, cuales niegan
- **Impugnaciones:** Total, resueltas, pendientes, tasa de revocacion
- **Rendimiento por abogado:** Casos, activos, favorabilidad por cada abogado
- **Derechos vulnerados:** Top 15 mas frecuentes

### Calendario
- Plazos de cumplimiento con semaforo (VENCIDO, URGENTE, EN PLAZO)
- Desacatos pendientes de decision
- Impugnaciones sin resolver

### Predictor
- Ingresa juzgado, derecho vulnerado y/o ciudad
- El sistema predice el resultado probable basado en datos historicos
- Muestra confianza, tamano de muestra y desglose

---

## 11. REPORTES

- **Generar Excel:** Exporta todos los casos con 28+ campos
- **Historial:** Lista de reportes generados con fecha y tamano
- **Descargar:** Click para bajar cualquier reporte previo

---

## 12. SEGUIMIENTO DE CUMPLIMIENTOS

Sistema semaforo para casos con fallo desfavorable:
- **VENCIDO** (rojo): Plazo excedido
- **URGENTE** (naranja): Menos de 3 dias
- **POR VENCER** (amarillo): Menos de 7 dias
- **EN PLAZO** (verde): Dentro del termino
- **CUMPLIDO** (azul): Ya se cumplio

---

## 13. CONFIGURACION Y ALERTAS

### Configuracion
- Estado de servicios (Gmail, IA, DB, carpetas)
- Informacion del sistema
- Variables de entorno (referencia)

### Sistema de alertas
- **Campana** en el sidebar con badge de conteo
- Click para ver alertas activas
- **Escanear:** Buscar nuevas alertas
- **Descartar:** Quitar alertas revisadas
- Tipos: DEADLINE, UNMATCHED_EMAIL, MISSING_DOC, ANOMALY

---

## 14. PROVEEDORES DE IA

El agente tiene **7 proveedores** con **Smart Router** automatico:

| Proveedor | Modelo | Uso principal | Costo |
|-----------|--------|---------------|:-----:|
| Google Gemini | Flash 2.5 | PDFs multimodales | Gratis (20 RPD) |
| Groq | Llama 3.3 70B | Extraccion rapida, chat | Gratis |
| Cerebras | Qwen 3 235B | Razonamiento legal complejo | Gratis |
| HF Router | Qwen 3 / Llama 3.3 | Fallback multi-proveedor | Gratis |
| DeepSeek | V3.2 | Extraccion economica | $0.28/M tokens |
| Anthropic | Claude Sonnet 4.6 | Razonamiento premium | $3-15/M tokens |
| OpenAI | GPT-4o | Multimodal premium | $2.50-10/M tokens |

El Smart Router selecciona automaticamente el mejor proveedor segun la tarea. No necesitas configurar nada.

### API keys
Las keys se configuran en `tutelas-app/.env`. Ver `GET /api/agent/routes` para ver que proveedor se usara para cada tipo de tarea.

---

## 15. FLUJO DE TRABAJO DIARIO

### Manana
1. Iniciar plataforma (`bash start.sh`)
2. Login (wilson / tutelas2026)
3. Dashboard → Revisar KPIs y alertas (campana)
4. Revisar Gmail → procesar emails nuevos

### Durante el dia
5. Usar el **Agente IA** (boton flotante) para consultas rapidas
6. Verificar plazos en **Inteligencia Legal → Calendario**
7. Extraer datos de casos nuevos (Extraccion → Individual o Lotes)
8. Revisar y corregir campos en el **Cuadro** (el agente aprende de tus correcciones)

### Cierre
9. Generar Excel actualizado (Reportes → Generar)
10. Revisar seguimiento de cumplimientos

---

## 16. SOLUCION DE PROBLEMAS

| Problema | Solucion |
|----------|----------|
| No carga el frontend | Verificar que `npm run dev` esta corriendo en puerto 5173 |
| Error 401 Unauthorized | Token expirado, cerrar sesion y volver a entrar |
| Gemini rate limited | Esperar reset (medianoche UTC) o usar Groq/Cerebras automatico |
| FOREST incorrecto | Verificar que no sea 3634740 (alucinado). Usar herramienta `validar_forest` |
| Caso no aparece | Sincronizar carpetas desde lista de Tutelas |
| Email sin caso asignado | Revisar en Correos → asignar manualmente |
| Extraccion falla | Verificar API key del proveedor en .env |

### Contacto tecnico
- Backend: FastAPI + Python 3.10 + SQLAlchemy + SQLite
- Frontend: React 19 + TypeScript + Vite + TailwindCSS
- Agente: 15 herramientas + Smart Router + Knowledge Base FTS5
- API Docs: http://localhost:8000/docs

---

*Agente Juridico IA v3.0 — Gobernacion de Santander — Marzo 2026*
