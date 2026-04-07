# AGENTE JURIDICO IA v3.1
## Plataforma de Ingenieria Legal — Gobernacion de Santander
### Creado por Wilson — Ingeniero Legal | Abril 2026

---

## Que es el Agente Juridico IA

Es un sistema de inteligencia artificial especializado en la gestion de acciones de tutela colombianas. No es un simple chatbot ni una herramienta CRUD — es un **agente autonomo** que analiza, clasifica, extrae, verifica, mueve documentos, crea casos y aprende de las correcciones del usuario.

Diseñado para la Gobernacion de Santander, gestiona 264+ casos de tutela con 3700+ documentos juridicos, 564 correos y 7 proveedores de IA.

---

## Capacidades del Agente

### 1. Extraccion Inteligente de Campos
El agente lee PDFs judiciales, documentos DOCX de respuesta, correos electronicos y archivos .md para extraer 28 campos legales de cada tutela:
- Radicado de 23 digitos, FOREST, accionante, accionados, vinculados
- Juzgado, ciudad (municipio de afectacion), derechos vulnerados
- Fallos de primera y segunda instancia, impugnaciones
- Incidentes de desacato (hasta 3 por caso)
- Abogado responsable, oficina, observaciones

### 2. Pipeline Autosuficiente
Cuando el agente procesa una carpeta de tutela:
- **Clasifica** cada documento por tipo (DOCX_RESPUESTA, PDF_AUTO_ADMISORIO, PDF_SENTENCIA, etc.)
- **Verifica** si cada documento pertenece al caso usando radicado de 23 digitos + accionante
- **Mueve automaticamente** documentos que no pertenecen a su carpeta correcta
- **Crea casos nuevos** si detecta un radicado que no existe en la base de datos
- **Extrae el abogado** SOLO del DOCX de respuesta (Proyectó > Elaboró), nunca de PDFs de oficios
- **Valida** cada campo post-extraccion (fechas, fallos validos, FOREST no alucinado)
- **No deja nada en pendiente** — todo se resuelve en un solo paso

### 3. Aprendizaje por Correcciones
Cuando el usuario corrige un campo:
- La correccion se almacena en la base de datos
- La proxima extraccion incluye las correcciones como ejemplos (few-shot learning)
- Si el mismo error se repite 3+ veces, el sistema detecta el patron y sugiere una regla nueva
- El agente mejora con cada uso

### 4. 15 Herramientas Juridicas
El agente tiene herramientas especializadas que puede ejecutar por instrucciones en lenguaje natural:

| Herramienta | Que hace |
|-------------|----------|
| buscar_caso | Busca por radicado, accionante, juzgado o texto libre |
| buscar_conocimiento | Busqueda full-text en 2389 entradas (PDFs, emails, DOCX) |
| buscar_email | Busca emails por subject, remitente o contenido |
| verificar_plazo | Calcula dias restantes para cumplimiento de fallo |
| predecir_resultado | Predice resultado basado en datos historicos |
| analizar_abogado | Rendimiento: casos, activos, tasa de favorabilidad |
| obtener_contexto | Contexto completo de un caso (todos los documentos y datos) |
| ver_razonamiento | Cadena de razonamiento de la ultima extraccion |
| estadisticas_generales | Resumen del sistema completo |
| listar_alertas | Alertas activas (plazos, anomalias) |
| escanear_alertas | Ejecutar deteccion de alertas |
| casos_por_municipio | Agrupacion con conteo |
| consumo_tokens | Consumo y ahorro vs APIs de pago |
| extraer_caso | Extraccion inteligente completa de un caso |
| validar_forest | Verifica si un FOREST es real o alucinado |

### 5. Inteligencia Legal
- **Favorabilidad por juzgado**: Que juzgados conceden mas tutelas contra la Gobernacion
- **Rendimiento por abogado**: Carga de trabajo, tasa de favorabilidad
- **Predictor de resultados**: Basado en datos historicos, predice CONCEDE/NIEGA
- **Calendario de plazos**: Vencimientos de cumplimiento con semaforo
- **Deteccion de anomalias**: FOREST alucinados, radicados duplicados, emails sin caso

### 6. Smart Router Multi-Modelo
El agente selecciona automaticamente el mejor proveedor de IA segun la tarea:
- **PDFs multimodales** → Gemini Flash (lee PDFs directo)
- **Extraccion de campos** → DeepSeek V3.2 ($0.013/caso)
- **Razonamiento legal** → Cerebras Qwen 3 235B (gratis, top benchmarks)
- **Chat general** → Groq Llama 3.3 (gratis, rapido)

---

## Impacto como Herramienta de Ingenieria Legal

### Antes del agente (manual)
- Revisar 264 carpetas una por una
- Leer cada PDF judicial para extraer radicados, accionantes, fallos
- Copiar datos manualmente al Excel
- Verificar que cada documento este en la carpeta correcta
- Calcular plazos de cumplimiento manualmente
- Responder preguntas del grupo juridico buscando en carpetas

### Con el agente
- **Extraccion masiva**: 264 casos en ~11 dias (gratis) o ~2 horas ($3 con DeepSeek)
- **94% completitud** por caso (15+ campos llenados automaticamente)
- **Documentos reasignados** automaticamente a la carpeta correcta
- **Plazos calculados** y alertados con semaforo
- **Preguntas en lenguaje natural**: "cuantas tutelas de educacion en Bucaramanga?" → respuesta inmediata
- **Aprendizaje continuo**: cada correccion mejora las extracciones futuras

### Metricas de confiabilidad
- Abogado extraido correctamente del DOCX de respuesta (no de otros PDFs)
- FOREST validado contra blacklist (3634740 nunca aceptado)
- Radicado verificado por 23 digitos (no solo corto de 5 digitos)
- Documentos de otro caso detectados y movidos automaticamente
- Campos validados post-IA: fechas DD/MM/YYYY, fallos validos, cross-field

---

## Arquitectura Tecnica

### Backend
- **Python 3.10** + **FastAPI** + **SQLAlchemy** + **SQLite** + **Alembic**
- **95 API endpoints** con autenticacion JWT
- **Logging JSON** estructurado con request IDs

### Frontend
- **React 19** + **TypeScript** + **Vite** + **TailwindCSS**
- **12 modulos**: Dashboard, Tutelas, Cuadro, Extraccion, Correos, Reportes, Configuracion, Seguimiento, Inteligencia, Agente IA, Login, Alertas

### IA
- **7 proveedores**: Google Gemini, Groq, Cerebras, HF Router, DeepSeek, Anthropic, OpenAI
- **Smart Router**: Seleccion automatica por tipo de tarea
- **Token Manager**: Cache, budget, reporte de ahorro
- **Knowledge Base**: SQLite FTS5 con 2389 entradas indexadas

### Agente
- **Tool Registry**: 15 herramientas registradas dinamicamente
- **Agent Runner**: Recibe instrucciones en lenguaje natural
- **Context Engine**: Recopila todo el contexto antes de cualquier decision
- **Reasoning Chain**: Explica por que tomo cada decision
- **Memory**: Correcciones almacenadas como few-shot examples

---

## Como usar el Agente

### Chat flotante (todas las paginas)
Click en el boton "Agente IA" en la esquina inferior derecha. Escribir instrucciones en lenguaje natural.

**Ejemplos:**
- "Dame las estadisticas generales"
- "Buscar caso personero Guavata"
- "Analizar abogado Cruz"
- "Predecir resultado para Bucaramanga"
- "Escanear alertas criticas"

### Extraccion individual
Modulo Extraccion → seleccionar caso → "Extraer Caso Individual". Muestra resultados detallados: campos, tokens, docs movidos, casos creados.

### Extraccion por lotes
Modulo Extraccion → "Extraccion por lotes". Protegido contra doble-click. Cada caso que falla va a REVISION (nunca queda trabado).

### Inteligencia Legal
Modulo Inteligencia → Analytics (favorabilidad por juzgado), Calendario (plazos), Predictor (basado en historicos).

---

## Costo de operacion

| Operacion | Costo |
|-----------|:-----:|
| Chat con agente (15 herramientas locales) | $0 |
| Knowledge Base search | $0 |
| Estadisticas, alertas, plazos | $0 |
| Extraccion con Gemini Flash | $0 (20/dia) |
| Extraccion con Cerebras Qwen 3 | $0 (14,400/dia) |
| Extraccion con DeepSeek V3.2 | $0.013/caso |
| **264 casos completos con DeepSeek** | **~$3.50** |

---

*Agente Juridico IA v3.1 — Gobernacion de Santander — Abril 2026*
*Creado por Wilson — Ingeniero Legal*
