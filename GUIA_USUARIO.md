# GUIA DE USUARIO - Plataforma de Gestion Juridica de Tutelas
## Gobernacion de Santander - Secretaria Juridica - Grupo de Apoyo Juridico

---

## 1. REQUISITOS DEL SISTEMA

| Componente | Requisito |
|-----------|-----------|
| Sistema Operativo | Windows 10/11 con WSL2 habilitado |
| Python | 3.10 o superior |
| Node.js | 18 o superior |
| Navegador | Chrome, Edge o Firefox (version reciente) |
| RAM | Minimo 4 GB disponibles |
| Disco | ~500 MB para la aplicacion + espacio para documentos |

---

## 2. INICIAR LA APLICACION

### Opcion A: Script automatico
```bash
cd "/mnt/c/Users/wilso/Documents/GOBERNACION DE SANTANDER/TUTELAS 2026/tutelas-app"
bash start.sh
```

### Opcion B: Inicio manual (dos terminales)

**Terminal 1 - Backend:**
```bash
cd "/mnt/c/Users/wilso/Documents/GOBERNACION DE SANTANDER/TUTELAS 2026/tutelas-app"
python3 -m uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload
```

**Terminal 2 - Frontend:**
```bash
cd "/mnt/c/Users/wilso/Documents/GOBERNACION DE SANTANDER/TUTELAS 2026/tutelas-app/frontend"
npm run dev -- --host 0.0.0.0
```

### URLs de acceso
| Servicio | URL |
|----------|-----|
| **Interfaz principal** | http://localhost:5173 |
| **API Backend** | http://localhost:8000 |
| **Documentacion API (Swagger)** | http://localhost:8000/docs |
| **Documentacion API (Redoc)** | http://localhost:8000/redoc |

---

## 3. NAVEGACION DE LA INTERFAZ

### 3.1 DASHBOARD (Pagina de inicio)
La pagina principal muestra un resumen ejecutivo de todas las tutelas:

- **4 tarjetas KPI** en la parte superior:
  - Total de tutelas registradas
  - Casos activos
  - Casos inactivos
  - Porcentaje de completitud de datos

- **4 graficos interactivos:**
  - Casos por mes de ingreso (barras)
  - Distribucion de fallos: CONCEDE/NIEGA/IMPROCEDENTE (torta)
  - Top ciudades por numero de casos (barras horizontales)
  - Carga de trabajo por abogado (barras horizontales)

- **Actividad reciente:** ultimas acciones realizadas en el sistema

### 3.2 TUTELAS (Lista de casos)
Vista principal de gestion de casos:

- **Buscador:** Busca por nombre del accionante, radicado, juzgado o cualquier texto
- **Filtros:** Estado (ACTIVO/INACTIVO), Sentido del fallo, Ciudad
- **Tabla de resultados:** Muestra radicado, accionante, juzgado, ciudad, estado y fallo con colores:
  - Amarillo = ACTIVO
  - Verde = INACTIVO
  - Rojo = CONCEDE
  - Verde = NIEGA
  - Naranja = IMPROCEDENTE
- **Clic en una fila** para ver el detalle completo del caso

### 3.3 DETALLE DEL CASO
Al hacer clic en un caso se abre la vista de detalle con dos paneles:

**Panel izquierdo (60%) - Formulario editable:**
Los 28 campos organizados en 8 secciones colapsables:
1. Identificacion (radicado judicial y FOREST)
2. Partes (accionante, accionados, vinculados)
3. Proceso (juzgado, ciudad, fecha, derechos vulnerados)
4. Gestion (oficina, abogado, estado, fecha respuesta)
5. Fallo 1ra Instancia
6. Impugnacion y 2da Instancia
7. Incidente de Desacato
8. Observaciones

- Cada campo se puede editar directamente
- Clic en **"Guardar Cambios"** para persistir
- Todos los cambios quedan registrados en el historial de auditoria

**Panel derecho (40%) - Documentos:**
- Lista de todos los archivos del caso (PDFs, DOCX, DOC)
- Icono segun tipo de documento
- Clic para abrir/previsualizar el archivo en nueva pestana
- Boton para re-extraer texto de un documento especifico

### 3.4 EXTRACCION (Motor de IA)
Pagina para procesar casos con inteligencia artificial:

- **"Extraer Todos los Pendientes"**: Procesa todos los casos que no han sido analizados
- **"Extraer Caso Individual"**: Seleccionar un caso especifico para extraer
- **Cola de revision**: Muestra casos con campos de baja confianza que necesitan verificacion manual

**Como funciona la extraccion:**
1. Lee TODOS los documentos de la carpeta (PDF completo, DOCX con footers y headers)
2. Envia el texto a Groq IA (Llama 3.3 70B) para analisis
3. La IA extrae los 28 campos con nivel de confianza (ALTA/MEDIA/BAJA)
4. Los resultados se guardan en la base de datos
5. Si algun campo tiene confianza BAJA, el caso aparece en la cola de revision

### 3.5 CORREOS (Bandeja de Gmail)
Gestion de emails entrantes:

- **"Revisar Bandeja"**: Consulta Gmail manualmente y descarga emails nuevos
- **Monitor automatico**: Cada 20 minutos revisa automaticamente tu bandeja
- **Tabla de emails**: Muestra asunto, remitente, fecha, estado y caso asignado
- **Clasificacion automatica**: El sistema identifica a que caso pertenece cada email por:
  1. Numero de radicado en el asunto o cuerpo
  2. Numero FOREST
  3. Nombre del accionante
  4. Contenido de los PDFs adjuntos

**Que pasa cuando llega un email nuevo:**
1. Se busca en la bandeja de Gmail emails no leidos con keywords juridicos
2. Se descargan los adjuntos PDF/DOCX
3. Se clasifica a que caso pertenece
4. Si es un caso nuevo: se crea carpeta automaticamente con formato "2026-XXXXX NOMBRE ACCIONANTE"
5. Los adjuntos se guardan en la carpeta correcta
6. Se marca como leido SOLO si se proceso exitosamente

### 3.6 REPORTES (Excel y metricas)
Generacion de reportes para entrega:

- **"Generar Excel"**: Crea un archivo Excel profesional con 3 hojas:
  1. **PORTADA**: Resumen ejecutivo con metricas clave
  2. **TUTELAS**: Tabla completa de 28 columnas con colores semanticos
  3. **ESTADISTICAS**: Graficos de barras, tablas de frecuencia, top ciudades y abogados
- **Historial de exportaciones**: Lista de Excel generados previamente con enlace de descarga
- **Metricas en pantalla**: Resumen rapido sin necesidad de descargar Excel

### 3.7 CONFIGURACION
Estado del sistema:

- Muestra si Gmail esta configurado y conectado
- Muestra si la API de Groq (IA) esta configurada
- Estado de la base de datos y carpetas

---

## 4. FLUJOS DE TRABAJO DIARIOS

### 4.1 Flujo matutino: Revisar nuevos casos
1. Abrir http://localhost:5173
2. Ir a **Correos** → clic en **"Revisar Bandeja"**
3. Ver emails nuevos descargados y clasificados
4. Si algun email quedo sin clasificar, asignarlo manualmente a un caso
5. Ir a **Extraccion** → clic en **"Extraer Todos los Pendientes"**
6. Revisar la cola de revision para validar campos con baja confianza

### 4.2 Flujo de respuesta a tutela
1. Ir a **Tutelas** → buscar el caso por radicado o nombre
2. Abrir el detalle del caso
3. Revisar los documentos descargados (panel derecho)
4. Completar o corregir los campos que falten
5. Guardar cambios

### 4.3 Flujo de entrega mensual
1. Ir a **Reportes** → clic en **"Generar Excel"**
2. Descargar el archivo generado
3. Revisar en Excel que los datos sean correctos
4. Entregar a la Secretaria Juridica

---

## 5. PROTOCOLO DE 28 CAMPOS

| # | Campo | Descripcion | Fuente |
|---|-------|-------------|--------|
| 1 | RADICADO_23_DIGITOS | Numero judicial de 23 digitos | Auto admisorio PDF |
| 2 | RADICADO_FOREST | Numero interno FOREST (~11 digitos) | Header DOCX / Gmail PDFs |
| 3 | ABOGADO_RESPONSABLE | Abogado que proyecto la respuesta | Footer DOCX ("Proyecto:") |
| 4 | ACCIONANTE | Persona que interpone la tutela | Auto admisorio |
| 5 | ACCIONADOS | Entidades demandadas | Auto admisorio |
| 6 | VINCULADOS | Terceros llamados al proceso | Auto admisorio |
| 7 | DERECHO_VULNERADO | Derechos fundamentales invocados | Auto admisorio |
| 8 | JUZGADO | Juzgado de primera instancia | Auto admisorio |
| 9 | CIUDAD | Ciudad del juzgado | Auto admisorio |
| 10 | FECHA_INGRESO | Fecha de admision (DD/MM/YYYY) | Auto admisorio |
| 11 | ASUNTO | Resumen de la demanda | Analisis IA |
| 12 | PRETENSIONES | Que pide el accionante | Auto admisorio |
| 13 | OFICINA_RESPONSABLE | Oficina que prepara respuesta | Header DOCX FOREST |
| 14 | ESTADO | ACTIVO o INACTIVO | Inferido del proceso |
| 15 | FECHA_RESPUESTA | Fecha del documento de respuesta | DOCX metadata |
| 16 | SENTIDO_FALLO_1ST | CONCEDE / NIEGA / IMPROCEDENTE | Sentencia PDF |
| 17 | FECHA_FALLO_1ST | Fecha del fallo 1ra instancia | Sentencia PDF |
| 18 | IMPUGNACION | SI o NO | Autos PDF |
| 19 | QUIEN_IMPUGNO | Quien apelo el fallo | Autos PDF |
| 20 | FOREST_IMPUGNACION | FOREST de la impugnacion | Header DOCX |
| 21 | JUZGADO_2ND | Juzgado de segunda instancia | Autos PDF |
| 22 | SENTIDO_FALLO_2ND | CONFIRMA / REVOCA / MODIFICA | Sentencia 2da instancia |
| 23 | FECHA_FALLO_2ND | Fecha fallo 2da instancia | Sentencia 2da instancia |
| 24 | INCIDENTE | SI o NO (desacato) | Autos PDF |
| 25 | FECHA_APERTURA_INCIDENTE | Fecha apertura desacato | Auto de apertura |
| 26 | RESPONSABLE_DESACATO | Abogado del desacato | Footer DOCX desacato |
| 27 | DECISION_INCIDENTE | Decision del juez | Auto de decision |
| 28 | OBSERVACIONES | Resumen general del caso | Analisis IA |

---

## 6. ENDPOINTS DE LA API (Para pruebas manuales)

### Salud y configuracion
```
GET  http://localhost:8000/api/health
GET  http://localhost:8000/api/settings/status
GET  http://localhost:8000/api/monitor/status
POST http://localhost:8000/api/monitor/toggle
```

### Casos
```
GET  http://localhost:8000/api/cases?search=GARCIA&page=1&per_page=10
GET  http://localhost:8000/api/cases/filters
GET  http://localhost:8000/api/cases/232
PUT  http://localhost:8000/api/cases/232  (body: {"ESTADO": "ACTIVO"})
```

### Documentos
```
GET  http://localhost:8000/api/documents/1
GET  http://localhost:8000/api/documents/1/preview
POST http://localhost:8000/api/documents/1/reextract
```

### Extraccion
```
POST http://localhost:8000/api/extraction/single/232
POST http://localhost:8000/api/extraction/batch  (body: {"case_ids": [1,2,3]})
GET  http://localhost:8000/api/extraction/review
```

### Dashboard
```
GET  http://localhost:8000/api/dashboard/kpis
GET  http://localhost:8000/api/dashboard/charts
GET  http://localhost:8000/api/dashboard/activity
```

### Reportes
```
POST http://localhost:8000/api/reports/excel
GET  http://localhost:8000/api/reports/excel/list
GET  http://localhost:8000/api/reports/metrics
```

### Correos
```
GET  http://localhost:8000/api/emails
POST http://localhost:8000/api/emails/check
PUT  http://localhost:8000/api/emails/1/assign/232
PUT  http://localhost:8000/api/emails/1/ignore
```

---

## 7. SOLUCION DE PROBLEMAS

| Problema | Solucion |
|----------|---------|
| Puerto 8000 ocupado | `fuser -k 8000/tcp` y reiniciar |
| Puerto 5173 ocupado | `fuser -k 5173/tcp` y reiniciar |
| Error IMAP Gmail | Verificar App Password en .env y que 2FA este activo en Google |
| Error Groq API | Verificar GROQ_API_KEY en .env, confirmar en console.groq.com |
| PDFs sin texto | Instalar tesseract: `sudo apt install tesseract-ocr tesseract-ocr-spa` |
| Archivos .doc no se leen | Instalar antiword: `sudo apt install antiword` |
| Base de datos corrupta | Eliminar data/tutelas.db y reiniciar (se re-importa del CSV) |
| Frontend no carga | Verificar `npm install` en carpeta frontend/ |

---

## 8. ARQUITECTURA TECNICA

```
tutelas-app/
├── backend/                    # Python 3.10 + FastAPI
│   ├── main.py                # Servidor + monitor Gmail background
│   ├── config.py              # Variables de entorno
│   ├── database/              # SQLAlchemy + SQLite
│   │   ├── models.py          # 5 tablas: cases, documents, extractions, emails, audit_log
│   │   ├── database.py        # Engine y sesiones
│   │   └── seed.py            # Importador CSV + escaner de carpetas
│   ├── extraction/            # Motor de extraccion documental
│   │   ├── pdf_extractor.py   # pdfplumber (todas las paginas)
│   │   ├── docx_extractor.py  # python-docx + footers + headers XML
│   │   ├── doc_extractor.py   # antiword/libreoffice para .doc
│   │   ├── ocr_extractor.py   # pytesseract para escaneados
│   │   ├── ai_extractor.py    # Groq API (Llama 3.3 70B)
│   │   └── pipeline.py        # Orquestador del flujo completo
│   ├── email/                 # Integracion Gmail IMAP
│   │   ├── gmail_monitor.py   # Descarga y clasificacion automatica
│   │   └── classifier.py      # Match email -> caso
│   ├── reports/               # Generacion de reportes
│   │   ├── excel_generator.py # Excel profesional 3 hojas
│   │   └── metrics.py         # Calculos estadisticos
│   ├── routers/               # 6 routers FastAPI (24 endpoints)
│   └── services/              # Logica de negocio
├── frontend/                  # React 19 + TypeScript + TailwindCSS
│   └── src/
│       ├── pages/             # 7 paginas: Dashboard, Cases, Detail, Extraction, Emails, Reports, Settings
│       ├── services/api.ts    # Cliente HTTP
│       └── App.tsx            # Layout + rutas
├── data/
│   └── tutelas.db            # Base de datos SQLite
├── .env                      # Credenciales (NUNCA compartir)
├── requirements.txt          # Dependencias Python
└── start.sh                  # Script de inicio
```

---

## 9. METRICAS ACTUALES DEL SISTEMA

| Metrica | Valor |
|---------|-------|
| Total archivos fuente | 52 |
| Lineas de codigo Python | 3,139 |
| Lineas de codigo TypeScript | 2,417 |
| Total lineas de codigo | 5,556 |
| Endpoints API | 24 |
| Paginas frontend | 7 |
| Tablas en base de datos | 5 |
| Casos registrados | 357 |
| Documentos indexados | 1,576 |
| Registros de auditoria | 510 |
| Emails procesados | 112 |
| Tamanio base de datos | 4.7 MB |

---

*Documento generado automaticamente - Tutelas Manager v1.0*
*Gobernacion de Santander - 2026*
