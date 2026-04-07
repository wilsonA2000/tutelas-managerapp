# GUIA DE USUARIO - TUTELAS MANAGER v2.0
## Plataforma de Gestion Juridica de Acciones de Tutela
### Gobernacion de Santander - 2026

---

## TABLA DE CONTENIDO

1. [Inicio Rapido](#1-inicio-rapido)
2. [Dashboard](#2-dashboard)
3. [Tutelas](#3-tutelas)
4. [Detalle de Tutela](#4-detalle-de-tutela)
5. [Extraccion IA](#5-extraccion-ia)
6. [Correos](#6-correos)
7. [Reportes](#7-reportes)
8. [Configuracion](#8-configuracion)
9. [Seguimiento de Cumplimientos](#9-seguimiento-de-cumplimientos)
10. [Flujo de Trabajo Diario](#10-flujo-de-trabajo-diario)
11. [Solucion de Problemas](#11-solucion-de-problemas)
12. [Informacion Tecnica](#12-informacion-tecnica)

---

## 1. INICIO RAPIDO

### Requisitos
- Windows 10/11 con WSL2 (Ubuntu)
- Python 3.10+
- Node.js 18+
- Conexion a internet (para Gmail API y Gemini IA)

### Arrancar la plataforma
```bash
cd "tutelas-app" && bash start.sh
```

### URLs de acceso
| Servicio | URL |
|----------|-----|
| Plataforma web | http://localhost:5173 |
| API Backend | http://localhost:8000 |
| Documentacion API (Swagger) | http://localhost:8000/docs |

### Navegacion
La plataforma tiene una barra lateral izquierda con 7 modulos:
- **Dashboard** — Panel principal con metricas y controles
- **Tutelas** — Lista y gestion de todos los casos
- **Extraccion** — Extraccion masiva o individual con IA
- **Correos** — Bandeja de notificaciones judiciales
- **Reportes** — Generacion y descarga de Excel
- **Configuracion** — Estado de servicios y sistema
- **Seguimiento** — Control de cumplimiento de fallos

La barra lateral se puede colapsar haciendo click en "Colapsar" en la parte inferior.

En todas las paginas hay un **boton circular azul** en la esquina inferior derecha para volver al inicio de la pagina.

---

## 2. DASHBOARD

El Dashboard es el panel principal de control. Desde aqui se ejecutan las operaciones mas importantes.

### 2.1 Centro de Control

Cuatro tarjetas con las acciones principales:

#### Revisar Gmail
- **Funcion:** Conecta a Gmail via API REST, descarga correos nuevos con adjuntos, clasifica cada email en su caso correspondiente, y ejecuta extraccion de datos con IA.
- **Boton:** "Revisar Gmail Ahora"
- **Progreso:** Muestra el estado en tiempo real: "Conectando a Gmail...", "15 emails encontrados", "Analizando caso X..."
- **Nota:** Procesa maximo 15 emails por revision. Si hay mas, pulse nuevamente.

#### Extraccion IA
- **Funcion:** Procesa todos los casos pendientes con inteligencia artificial (Gemini). Lee documentos PDF (multimodal), DOCX y emails para extraer los 28 campos del protocolo.
- **Boton:** "Extraer Pendientes" (morado)
- **Boton cancelar:** "Detener Extraccion" (rojo, aparece cuando hay extraccion en curso)
- **Progreso:** Barra de progreso con porcentaje, caso actual, exitosos/errores

#### Corte Excel
- **Funcion:** Genera un archivo Excel con el estado actual de todos los casos. Contiene los 28 campos del protocolo.
- **Boton:** "Descargar Corte Excel" (verde)
- **Nota:** El Excel se genera en el momento — refleja los datos mas recientes.

#### Flujo de Trabajo
- Indicador visual del estado del sistema
- Gmail: revision manual por operador
- IA: extrae datos de documentos + emails
- Datos se actualizan en tiempo real
- Excel: solo cuando usted lo solicite

### 2.2 Proveedor de IA y Consumo de Tokens

#### Modelo de IA Activo
Lista todos los proveedores de IA disponibles:
- **Google Gemini 2.5 Flash** (principal, gratuito) — Lee PDFs directamente como imagenes
- **Google Gemini 2.5 Pro** — Mayor precision, con costo
- **Claude Haiku 4.5 / Sonnet 4.6** (Anthropic) — Requiere creditos
- **GPT-4o Mini / GPT-4o** (OpenAI) — Requiere creditos

Para cambiar de modelo: haga click en el modelo deseado. Quedara resaltado en azul como "ACTIVO".

**Nota:** Solo se cobra del proveedor que tenga activo. Los demas no generan costo.

#### Consumo de Tokens
- **Total tokens:** Tokens de entrada + salida acumulados
- **Llamadas:** Numero total de llamadas a la IA
- **Costo USD:** Costo acumulado (Gemini Flash = $0.00)
- **Por Modelo:** Desglose de consumo por cada proveedor/modelo usado

#### Historial de Llamadas
- Ultimas 10 llamadas exitosas
- Muestra: proveedor, hora, tokens, campos extraidos, duracion
- Errores recientes al final (si los hay)

### 2.3 Resumen General (KPIs)

Cuatro tarjetas con metricas:
- **Total Tutelas:** Numero de casos registrados en la base de datos
- **Activos:** Casos en tramite (estado ACTIVO)
- **Inactivos:** Casos finalizados (estado INACTIVO)
- **Completitud:** Porcentaje promedio de campos diligenciados

### 2.4 Distribucion de Casos (Graficas)

- **Casos por Mes:** Grafica de barras con la cantidad de tutelas por mes de ingreso
- **Distribucion por Fallo:** Grafica circular (CONCEDE en rojo, NIEGA en verde, IMPROCEDENTE en naranja, PENDIENTE en gris)
- **Top 10 Ciudades:** Grafica horizontal con las ciudades con mas tutelas
- **Top 10 Abogados:** Grafica horizontal con los abogados mas frecuentes

### 2.5 Actividad Reciente

Linea de tiempo con las ultimas 20 acciones del sistema:
- Extracciones de IA (icono morado)
- Emails importados (icono verde)
- Ediciones manuales (icono azul)
- Casos creados (icono gris)

Cada entrada muestra: descripcion, carpeta del caso, abogado, fecha y hora (hora Colombia).

### 2.6 Modal de Progreso

Cuando se ejecuta cualquier proceso largo (Gmail, Extraccion, Sincronizacion), aparece un **modal oscuro** con:
- Icono giratorio
- Nombre del proceso activo
- Barra de progreso con efecto de brillo animado
- Porcentaje en numero grande
- Conteo: "X de Y"
- Exitosos/errores (si aplica)
- Paso actual (nombre del caso que se esta procesando)
- Boton de cancelar (X) para procesos cancelables

El modal **persiste entre modulos** — puede navegar a otras paginas y el modal sigue visible hasta que el proceso termine.

---

## 3. TUTELAS

### 3.1 Lista de Casos

Muestra todos los casos registrados en formato de tabla con paginacion.

#### Boton Sincronizar
- **Ubicacion:** Esquina superior derecha
- **Funcion:** Escanea las carpetas locales y actualiza la base de datos:
  - Registra documentos nuevos que se hayan agregado manualmente a las carpetas
  - Corrige paths rotos si una carpeta fue renombrada
  - Detecta carpetas nuevas creadas manualmente
- **Cuando usarlo:** Despues de agregar archivos manualmente a las carpetas, o si nota que un caso no muestra sus documentos.

#### Buscador
- Busca por: accionante, radicado, juzgado, observaciones
- La busqueda es en tiempo real (mientras escribe)

#### Filtros
- **Estado:** Todos / Activo / Inactivo
- **Fallo:** Todos / Concede / Niega / Improcedente
- **Ciudad:** Lista dinamica de todas las ciudades registradas

#### Tabla de Casos
| Columna | Descripcion |
|---------|-------------|
| # | Numero de fila |
| RADICADO | Nombre de la carpeta del caso |
| ACCIONANTE | Nombre de quien interpone la tutela |
| JUZGADO | Juzgado que admitio la tutela |
| CIUDAD | Ciudad del juzgado |
| ESTADO | ACTIVO (amarillo) o INACTIVO (verde) |
| FALLO | CONCEDE (rojo), NIEGA (verde), IMPROCEDENTE (naranja) |
| ABOGADO | Abogado responsable de la respuesta |

Haga click en cualquier fila para ver el detalle del caso.

#### Paginacion
- 20 casos por pagina
- Botones Anterior/Siguiente
- Indicador: "Pagina X de Y — N casos"

---

## 4. DETALLE DE TUTELA

### 4.1 Panel Izquierdo: Formulario Editable

Los 28 campos estan organizados en 8 secciones colapsables:

#### Identificacion
- **RADICADO 23 DIGITOS:** Numero judicial completo (formato XX-XXX-XX-XX-XXX-YYYY-NNNNN-NN)
- **RADICADO FOREST:** Numero interno del sistema FOREST de la Gobernacion (7-11 digitos)

#### Partes
- **ACCIONANTE:** Persona o entidad que interpone la tutela
- **ACCIONADOS:** Entidades demandadas (separadas por " - ")
- **VINCULADOS:** Terceros llamados al proceso

#### Proceso
- **JUZGADO:** Nombre completo del juzgado
- **CIUDAD:** Ciudad donde se ubica el juzgado
- **FECHA INGRESO:** Fecha de admision (DD/MM/YYYY)
- **DERECHO VULNERADO:** Derechos fundamentales invocados
- **ASUNTO:** Resumen breve de la tutela
- **PRETENSIONES:** Lo que pide el accionante al juez

#### Gestion
- **OFICINA RESPONSABLE:** Oficina de la Gobernacion que prepara la respuesta
- **ABOGADO RESPONSABLE:** Nombre del abogado que redacto la respuesta
- **ESTADO:** ACTIVO o INACTIVO
- **FECHA RESPUESTA:** Fecha del documento de respuesta

#### Fallo Primera Instancia
- **SENTIDO FALLO 1ST:** CONCEDE / NIEGA / IMPROCEDENTE / CONCEDE PARCIALMENTE
- **FECHA FALLO 1ST:** Fecha de la sentencia

#### Impugnacion
- **IMPUGNACION:** SI o NO
- **QUIEN IMPUGNO:** Accionante / Accionado / Vinculado
- **FOREST IMPUGNACION:** Numero FOREST de la impugnacion
- **JUZGADO 2ND:** Juzgado de segunda instancia
- **SENTIDO FALLO 2ND:** CONFIRMA / REVOCA / MODIFICA
- **FECHA FALLO 2ND:** Fecha del fallo de segunda instancia

#### Incidente de Desacato
- **INCIDENTE:** SI o NO
- **FECHA APERTURA INCIDENTE:** Fecha del desacato
- **RESPONSABLE DESACATO:** Abogado que respondio
- **DECISION INCIDENTE:** Decision del juez sobre el desacato

#### Observaciones
- **OBSERVACIONES:** Resumen general del caso (generado por IA o editable manualmente)

### 4.2 Edicion y Guardado

- Modifique cualquier campo directamente en el formulario
- Aparecera un indicador amarillo "Cambios sin guardar"
- Haga click en **"Guardar"** (boton azul superior derecho) para guardar
- Todos los cambios quedan registrados en el historial de auditoria

### 4.3 Panel Derecho: Documentos

#### Lista de Documentos
Cada documento muestra:
- Icono segun tipo (📄 PDF, 📝 Word, 🖼️ Imagen)
- Nombre del archivo (truncado si es muy largo, hover para ver completo)
- Tipo clasificado: Auto Admisorio, Sentencia, Respuesta, Correo, Captura, Impugnacion, Incidente, Otro

#### Previsualizacion
- Haga click en cualquier documento para ver la previsualizacion inline
- **PDF:** Se muestra el visor nativo del navegador dentro del panel
- **DOCX:** Se convierte a HTML y se muestra con formato (parrafos, tablas, negritas, pies de pagina)
- **DOC:** Se extrae el texto con antiword y se muestra
- **Imagenes:** Se muestran directamente
- Boton "Abrir en pestaña" para ver en pantalla completa
- Boton "Cerrar" para ocultar la previsualizacion

#### Panel Redimensionable
- La linea divisora entre el formulario y los documentos es **arrastrable**
- Ponga el cursor sobre la linea (se pone azul) y arrastre a la izquierda o derecha
- Ambos paneles se ajustan en tiempo real
- Limites: minimo 30% formulario, maximo 80%

---

## 5. EXTRACCION IA

### 5.1 Extraccion por Lotes
- Procesa automaticamente todos los casos con campos incompletos
- Lee documentos PDF (multimodal — la IA ve el documento directamente), DOCX, y cuerpo de emails
- Extrae los 28 campos del protocolo
- Muestra cantidad de casos pendientes en cola de revision

### 5.2 Extraccion Individual
- Seleccione un caso especifico del desplegable
- Util para re-procesar un caso que tuvo errores o que recibio documentos nuevos

### 5.3 Cola de Revision
Tabla con los casos que necesitan revision:
- **Caso:** Nombre de la carpeta
- **Accionante:** Nombre (si se extrajo)
- **Completitud:** Barra de progreso con porcentaje
- **Campos Faltantes:** Etiquetas rojas con los campos vacios
- **Acciones:** Boton "Extraer" para re-procesar, flecha para ir al detalle

### 5.4 Como funciona la IA (Gemini Multimodal)

La plataforma usa Google Gemini 2.5 Flash para analizar documentos:

1. **PDFs:** Se envian directamente a Gemini como imagenes. La IA "ve" el documento completo: texto, tablas, sellos, marcas de agua, firmas, documentos escaneados.
2. **DOCX/DOC:** Se extrae el texto incluyendo pies de pagina (nombre del abogado) y encabezados (datos FOREST). Se envia como texto a la IA.
3. **Emails:** El subject, remitente, fecha y body completo se incluyen como contexto. Contienen informacion valiosa como el RADICADO FOREST.
4. **PDFs grandes (>30 paginas):** Se recortan automaticamente a las primeras 10 + ultimas 10 paginas.

La IA analiza TODO el expediente junto y extrae los 28 campos con niveles de confianza (ALTA, MEDIA, BAJA).

---

## 6. CORREOS

### 6.1 Lista de Emails
Muestra todos los correos recibidos desde Gmail:
- **Asunto:** Titulo del correo
- **Remitente:** Quien envio el correo
- **Fecha:** Fecha y hora (hora Colombia)
- **Estado:** Pendiente (amarillo), Asignado (verde), Ignorado (gris)
- **Caso Asignado:** A que carpeta se vinculo el email

### 6.2 Revisar Bandeja
- Boton "Revisar Bandeja" en la esquina superior derecha
- Conecta a Gmail via API REST (no IMAP)
- Descarga hasta 15 correos nuevos por revision
- Clasifica cada email y lo asigna a su caso
- Descarga adjuntos a las carpetas correspondientes
- Si no encuentra caso existente, crea una carpeta nueva con formato "[PENDIENTE REVISION]"

### 6.3 Filtros
- **Busqueda:** Por asunto o remitente
- **Estado:** Todos / Pendiente / Asignado / Ignorado

---

## 7. REPORTES

### 7.1 Generar Excel
- Boton "Generar Excel" crea un archivo con todos los datos actuales
- El archivo incluye los 28 campos de cada caso
- Formato profesional con encabezados coloreados
- Compatible con Microsoft Excel y Google Sheets

### 7.2 Archivos Generados
- Lista de todos los archivos Excel creados
- Cada uno muestra: nombre, fecha de creacion (hora Colombia), tamano
- Boton "Descargar" para obtener el archivo

### 7.3 Metricas
Resumen estadistico de los datos:
- Total de casos, activos, inactivos
- Distribucion de fallos
- Completitud de campos
- Casos con impugnacion/incidente

---

## 8. CONFIGURACION

### 8.1 Estado de Servicios
Cuatro tarjetas muestran el estado de cada componente:

| Servicio | Descripcion | Indicador |
|----------|-------------|-----------|
| Gmail API | Conexion al correo oficial | Verde = configurado |
| Google Gemini (IA) | Motor de inteligencia artificial | Verde = API key valida |
| Base de Datos SQLite | Almacenamiento local | Verde = archivo existe |
| Carpetas de Casos | Directorio de tutelas | Verde = ruta accesible |

### 8.2 Informacion del Sistema
- Entidad: Gobernacion de Santander
- Modulo: Gestion de Tutelas 2026
- Version: 2.0.0
- Motor IA: Google Gemini 2.5 Flash (Multimodal)
- Casos en DB y Documentos en DB (conteo actual)

### 8.3 Variables de Entorno
El archivo `.env` contiene las credenciales necesarias:
```
GMAIL_USER=correo@gmail.com
GMAIL_APP_PASSWORD=xxxx xxxx xxxx xxxx
GOOGLE_API_KEY=AIza...           # Gemini (principal)
ANTHROPIC_API_KEY=sk-ant-...     # Claude (opcional)
OPENAI_API_KEY=sk-proj-...       # GPT (opcional)
BASE_DIR=/ruta/a/carpetas/tutelas
```

---

## 9. SEGUIMIENTO DE CUMPLIMIENTOS

### 9.1 Proposito
Controlar los fallos desfavorables (CONCEDE) y sus plazos de cumplimiento para evitar incidentes de desacato.

### 9.2 Escanear Fallos
- Boton "Escanear Fallos" revisa todos los casos con fallo CONCEDE
- Crea automaticamente registros de seguimiento para cada uno
- Detecta si el fallo fue confirmado en segunda instancia (mas urgente)

### 9.3 Semaforo de Estado

| Color | Estado | Significado |
|-------|--------|-------------|
| 🔴 Rojo | VENCIDO | El plazo ya paso sin cumplimiento |
| 🟠 Naranja | URGENTE | Faltan menos de 3 dias |
| 🟡 Amarillo | POR VENCER | Faltan menos de 7 dias |
| 🟢 Verde | EN PLAZO | Aun hay tiempo para cumplir |
| 🔵 Azul | CUMPLIDO | Ya se ejecuto la orden |
| 🟣 Morado | IMPUGNADO | En segunda instancia |

### 9.4 Informacion por Caso
- **Accionante y juzgado** del caso
- **Instancia:** 1ra, 2da, o 2da (CONFIRMADO)
- **Sentido del fallo:** CONCEDE / CONCEDE PARCIALMENTE
- **Orden Judicial:** Que ordeno el juez (extraido por IA o editable)
- **Plazo:** Fecha limite y dias restantes
- **Responsable:** Oficina que debe cumplir

### 9.5 Extraer Orden con IA
- Si la columna "Orden Judicial" esta vacia, aparece el boton "Extraer con IA"
- La IA lee la sentencia del caso y extrae:
  - Que ordeno el juez
  - Plazo en dias
  - Responsable del cumplimiento
  - Efecto de la impugnacion

### 9.6 Marcar como Cumplido
- Boton "Cumplido" en cada fila
- Registra la fecha de cumplimiento
- Cambia el semaforo a azul (CUMPLIDO)

### 9.7 Acceso Directo al Caso
- Icono de flecha en cada fila
- Lleva directamente al detalle de la tutela

---

## 10. FLUJO DE TRABAJO DIARIO

### Rutina recomendada para el operador:

#### Al iniciar el dia:
1. Abrir http://localhost:5173
2. En el **Dashboard**, hacer click en **"Revisar Gmail Ahora"**
3. Esperar a que el modal de progreso termine
4. Revisar el resumen: cuantos emails nuevos, cuantos casos actualizados

#### Cuando llegan correos nuevos:
1. Ir al **Dashboard** y pulsar **"Revisar Gmail Ahora"** nuevamente
2. Los correos se descargan, clasifican y procesan automaticamente
3. Si el correo tiene radicado reconocible, se asigna al caso existente
4. Si es un caso nuevo, se crea una carpeta con formato "[PENDIENTE REVISION]"

#### Para verificar datos:
1. Ir a **Tutelas** y buscar el caso por accionante o radicado
2. Hacer click para ver el detalle
3. Verificar los 28 campos (la IA los lleno automaticamente)
4. Corregir manualmente si algo esta mal
5. Guardar cambios

#### Para extraer datos pendientes:
1. Ir al **Dashboard** y pulsar **"Extraer Pendientes"**
2. O ir a **Extraccion** para procesar casos individuales
3. La IA lee los PDFs directamente (multimodal) + DOCX + emails

#### Para generar reporte:
1. Ir al **Dashboard** y pulsar **"Descargar Corte Excel"**
2. O ir a **Reportes** y pulsar **"Generar Excel"**
3. El Excel se descarga con los datos mas recientes

#### Para controlar cumplimientos:
1. Ir a **Seguimiento**
2. Pulsar **"Escanear Fallos"** para detectar nuevos fallos desfavorables
3. Revisar el semaforo: rojo = urgente, amarillo = por vencer
4. Marcar como "Cumplido" cuando se ejecute la orden del juez

#### Si agrega archivos manualmente:
1. Copiar los archivos a la carpeta del caso en el directorio local
2. Ir a **Tutelas** y pulsar **"Sincronizar"**
3. Los nuevos archivos se registran en la base de datos

---

## 11. SOLUCION DE PROBLEMAS

### La pagina no carga o dice "Error al cargar"
- Verifique que el backend este corriendo: abra http://localhost:8000/api/health
- Si dice `{"status":"ok"}`, el problema es el frontend. Recargue con Ctrl+Shift+R
- Si no responde, reinicie los servidores: `bash start.sh`

### Gmail no descarga correos
- Verifique la conexion a internet
- Revise que las credenciales OAuth2 esten vigentes (archivo `gmail_token.json`)
- Si el token expiro, elimine `gmail_token.json` y re-autorice

### La IA no extrae campos correctamente
- Verifique que la API key de Gemini este configurada en `.env`
- Revise el consumo de tokens en el Dashboard (puede haber excedido la cuota)
- Intente con otro modelo desde el selector de proveedores

### Un caso no muestra documentos
- Vaya a **Tutelas** y pulse **"Sincronizar"**
- Esto registra documentos que se agregaron manualmente a las carpetas

### El Excel no tiene datos actualizados
- El Excel se genera con los datos del momento. Si falta informacion, ejecute primero la extraccion de IA y luego genere el Excel.

### El modal de progreso se queda atascado
- Si un proceso se cuelga, use el boton de cancelar (X) en el modal
- Si no responde, recargue la pagina con Ctrl+Shift+R

### Las fechas aparecen incorrectas
- Todas las fechas se muestran en hora Colombia (UTC-5)
- Si ve fechas en otro huso horario, reinicie el backend

---

## 12. INFORMACION TECNICA

### Stack Tecnologico
| Componente | Tecnologia |
|-----------|------------|
| Backend | Python 3.10 + FastAPI + SQLAlchemy |
| Frontend | React 19 + TypeScript + Vite 8 + TailwindCSS 4 |
| Base de datos | SQLite (local) |
| IA Principal | Google Gemini 2.5 Flash (multimodal, gratuito) |
| IA Alternativas | Claude Haiku/Sonnet, GPT-4o Mini/4o |
| Email | Gmail API REST (OAuth2) |
| PDF | PyMuPDF + pdfplumber (fallback) |
| DOCX | python-docx + antiword (DOC) |
| Reportes | openpyxl (Excel) |
| Graficas | Recharts |

### Estructura de Archivos
```
tutelas-app/
├── backend/
│   ├── main.py              # Servidor FastAPI + endpoints principales
│   ├── config.py             # Configuracion (.env)
│   ├── database/
│   │   ├── models.py         # 7 tablas: cases, documents, emails, etc.
│   │   ├── database.py       # Motor SQLite + SQLAlchemy
│   │   └── seed.py           # Importacion inicial CSV + escaneo carpetas
│   ├── email/
│   │   └── gmail_monitor.py  # Gmail API REST (OAuth2)
│   ├── extraction/
│   │   ├── ai_extractor.py   # Multi-proveedor IA (Gemini multimodal)
│   │   ├── pipeline.py       # Orquestador: docs → IA → DB
│   │   ├── pdf_extractor.py  # Extraccion texto PDF (pdfplumber)
│   │   ├── pdf_splitter.py   # Recorte PDFs grandes (PyMuPDF)
│   │   ├── docx_extractor.py # Extraccion DOCX + footer abogado
│   │   ├── doc_extractor.py  # Extraccion DOC (antiword)
│   │   └── ocr_extractor.py  # OCR con Tesseract
│   ├── routers/              # 7 routers REST API
│   ├── services/             # Logica de negocio
│   └── reports/              # Generacion Excel
├── frontend/
│   └── src/
│       ├── pages/            # 8 paginas React
│       ├── components/       # Modal de progreso
│       └── services/api.ts   # Cliente API (Axios)
├── data/
│   ├── tutelas.db            # Base de datos SQLite
│   └── exports/              # Archivos Excel generados
├── gmail_credentials.json    # Credenciales OAuth2
├── gmail_token.json          # Token de acceso Gmail
├── .env                      # Variables de entorno
├── start.sh                  # Script de inicio
└── requirements.txt          # Dependencias Python
```

### Los 28 Campos del Protocolo

| # | Campo | Fuente |
|---|-------|--------|
| 1 | RADICADO_23_DIGITOS | Auto admisorio |
| 2 | RADICADO_FOREST | Emails, archivos FOREST |
| 3 | ABOGADO_RESPONSABLE | Footer del DOCX de respuesta |
| 4 | ACCIONANTE | Auto admisorio |
| 5 | ACCIONADOS | Auto admisorio |
| 6 | VINCULADOS | Auto admisorio |
| 7 | DERECHO_VULNERADO | Auto admisorio |
| 8 | JUZGADO | Auto admisorio |
| 9 | CIUDAD | Auto admisorio |
| 10 | FECHA_INGRESO | Auto admisorio |
| 11 | ASUNTO | Resumen de la IA |
| 12 | PRETENSIONES | Auto admisorio |
| 13 | OFICINA_RESPONSABLE | DOCX de respuesta |
| 14 | ESTADO | ACTIVO / INACTIVO |
| 15 | FECHA_RESPUESTA | DOCX de respuesta |
| 16 | SENTIDO_FALLO_1ST | Sentencia primera instancia |
| 17 | FECHA_FALLO_1ST | Sentencia primera instancia |
| 18 | IMPUGNACION | SI / NO |
| 19 | QUIEN_IMPUGNO | Documentos de impugnacion |
| 20 | FOREST_IMPUGNACION | Email o documento FOREST |
| 21 | JUZGADO_2ND | Auto segunda instancia |
| 22 | SENTIDO_FALLO_2ND | Sentencia segunda instancia |
| 23 | FECHA_FALLO_2ND | Sentencia segunda instancia |
| 24 | INCIDENTE | SI / NO |
| 25 | FECHA_APERTURA_INCIDENTE | Auto de desacato |
| 26 | RESPONSABLE_DESACATO | DOCX de respuesta desacato |
| 27 | DECISION_INCIDENTE | Auto del juez |
| 28 | OBSERVACIONES | Resumen generado por IA |

### Base de Datos (7 Tablas)

| Tabla | Descripcion |
|-------|-------------|
| cases | Casos de tutela (28 campos + metadata) |
| documents | Documentos asociados a cada caso |
| emails | Correos recibidos via Gmail |
| extractions | Registro de cada campo extraido por IA |
| audit_log | Historial de cambios |
| token_usage | Consumo de tokens por llamada IA |
| compliance_tracking | Seguimiento de cumplimiento de fallos |

### API REST (Endpoints Principales)

| Metodo | Endpoint | Descripcion |
|--------|----------|-------------|
| GET | /api/health | Estado del servidor |
| GET | /api/cases | Listar casos con filtros |
| GET | /api/cases/{id} | Detalle de un caso |
| PUT | /api/cases/{id} | Actualizar campos |
| POST | /api/emails/check | Revisar Gmail |
| POST | /api/extraction/run-all | Extraccion masiva |
| POST | /api/extraction/single/{id} | Extraccion individual |
| POST | /api/reports/excel | Generar Excel |
| POST | /api/sync | Sincronizar carpetas |
| GET | /api/ai/providers | Proveedores IA disponibles |
| PUT | /api/ai/provider | Cambiar modelo IA |
| GET | /api/tokens/metrics | Metricas de consumo |
| GET | /api/seguimiento | Listado de seguimientos |
| POST | /api/seguimiento/scan | Escanear fallos desfavorables |

---

**Tutelas Manager v2.0** — Gobernacion de Santander, 2026
Desarrollado con: Python, React, Google Gemini AI
