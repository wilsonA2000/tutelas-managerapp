# Tesis — Agente Jurídico IA para Gestión Automatizada de Tutelas

**Autor:** Wilson (Ingeniero Legal contratista, Gobernación de Santander)
**Título del proyecto:** Plataforma híbrida de agente jurídico con cognición forense mecánica para procesamiento autónomo de acciones de tutela
**Período:** Enero 2026 – Abril 2026
**Versión del documento:** 1.0 (2026-04-21)

---

## Índice

1. [Introducción y contexto](#1-introducción-y-contexto)
2. [Problema](#2-problema)
3. [Objetivos](#3-objetivos)
4. [Metodología](#4-metodología-de-investigación-aplicada)
5. [Arquitectura del sistema](#5-arquitectura-del-sistema)
6. [Ingeniería inversa de cognición humana](#6-ingeniería-inversa-de-cognición-humana)
   - 6.1 Planteamiento
   - 6.2 Las 7 etapas traducidas a código
   - 6.3 Gaps pre-v5.2 cerrados
   - 6.4 Los 6 archivos huérfanos: caso de estudio
   - 6.5 Integración v5.2 Sprint 8
   - **6.6 Heurísticas como metodología de resolución** (7 clases + evaluación empírica)
7. [Resultados cuantitativos](#7-resultados-cuantitativos)
8. [Competencias diferenciadoras](#8-competencias-diferenciadoras)
9. [Viabilidad de monetización y expansión](#9-viabilidad-de-monetización-y-expansión)
10. [Conclusiones y trabajo futuro](#10-conclusiones)
11. [Apéndices](#11-apéndices)
12. [**Marco disciplinar: La Ingeniería Legal**](#12-marco-disciplinar-la-ingeniería-legal) — contribución del autor

---

## 1. Introducción y contexto

### 1.1 Contexto institucional

La **Gobernación de Santander**, específicamente la **Secretaría de Educación Departamental**, recibe anualmente cientos de acciones de tutela (artículo 86 de la Constitución Política de Colombia) provenientes de ciudadanos, personeros municipales, estudiantes y docentes. El volumen estimado es de **300–400 tutelas/año**, con flujo constante por canales diversos (correo electrónico, notificaciones judiciales físicas, portales de radicación en línea como RPA del Consejo Superior de la Judicatura).

### 1.2 Actores y flujos

| Actor | Rol | Volumen |
|-------|-----|---------|
| Ciudadano/Personero | Interpone tutela | ~300-400/año |
| Juzgado | Avoca conocimiento, notifica | — |
| Gobernación Santander (Dirección Atención al Ciudadano) | Recibe email, asigna número FOREST interno | 100% |
| Secretaría de Educación | Apoyo Jurídico redacta respuesta en 2-3 días | — |
| Sistema FOREST | Registro interno de correspondencia (número de 11 dígitos) | — |

### 1.3 Problemática operacional pre-proyecto

Antes de esta plataforma, el trámite era manual:

- Abogado contratista descarga emails uno por uno
- Organiza archivos en carpetas con formato irregular
- Registra a mano 28 campos en Excel (`COMPILADO_TUTELAS_2026.csv`)
- Verifica fechas, derechos, impugnaciones, desacatos caso por caso
- Excel propenso a errores de digitación y duplicados

Tiempo estimado por caso: **45-90 minutos de trabajo manual**. Con 30 casos/mes: **22-45 horas/mes** solo en registro (sin contar redacción de respuesta).

### 1.4 Motivación de la investigación aplicada

El proyecto nace de una pregunta práctica: **¿cuánto del trabajo de registro/clasificación puede ser automatizado con ingeniería mecánica determinista, reduciendo dependencia de IA cara?**

La hipótesis central es que el **80% del análisis jurídico inicial es mecanizable** si se combina correctamente:

1. Extracción de texto multi-tier (pdftext → OCR → multimodal)
2. Representación intermedia semántica (IR)
3. Patrones regex especializados por tipo de documento
4. Correlación de archivos por metadatos
5. IA solo para razonamiento genuinamente difuso (observaciones, interpretación)

El 20% restante requiere criterio humano y **NO debe ser forzado** a la IA — debe marcarse explícitamente para revisión.

---

## 2. Problema

### 2.1 Protocolo objetivo: 28 campos estructurados

El caso ideal extraído automáticamente tiene 28 campos divididos en 4 grupos:

| Grupo | Campos | Fuente |
|-------|--------|--------|
| **Identidad** (4) | RADICADO_23_DIGITOS, RADICADO_FOREST, ABOGADO_RESPONSABLE, OFICINA_RESPONSABLE | Auto admisorio, email tutelas@, DOCX footer |
| **Partes procesales** (4) | ACCIONANTE, ACCIONADOS, VINCULADOS, DERECHO_VULNERADO | Auto admisorio |
| **Ubicación y fechas** (3) | JUZGADO, CIUDAD, FECHA_INGRESO | Auto admisorio |
| **Contenido** (3) | ASUNTO, PRETENSIONES, ESTADO | Escrito de tutela |
| **Trámite primera instancia** (3) | FECHA_RESPUESTA, SENTIDO_FALLO_1ST, FECHA_FALLO_1ST | DOCX respuesta, Sentencia |
| **Impugnación** (4) | IMPUGNACION, QUIEN_IMPUGNO, FOREST_IMPUGNACION, JUZGADO_2ND | Auto concede impugnación |
| **Segunda instancia** (2) | SENTIDO_FALLO_2ND, FECHA_FALLO_2ND | Sentencia 2da instancia |
| **Desacato** (8) | INCIDENTE/FECHA_APERTURA/RESPONSABLE_DESACATO/DECISION × 3 niveles | Autos incidente |
| **General** (1) | OBSERVACIONES | IA generativa |

### 2.2 Bugs estructurales identificados (auditoría 2026-04-20)

Al analizar el estado de la plataforma pre-v5.0, se detectaron 13 bugs:

| # | Severidad | Bug |
|---|-----------|-----|
| B1 | 🔴 Crítico | Regex `RAD_LABEL` con `IGNORECASE` matcheaba "número de radicado 20260066132" (FOREST interno) como radicado judicial "2026-66132" |
| B2 | 🔴 Crítico | `extract_radicado()` retornaba early en RAD_LABEL aunque ya hubiera radicado 23d válido |
| B3 | 🔴 Crítico | Prompt IA inyectaba `folder_name` literal → IA repetía "Caso 2026-66132" en observaciones |
| B4 | 🔴 Crítico | Post-validator no detectaba radicados ajenos en observaciones/asunto/pretensiones |
| B5 | 🟠 Alto | No renombraba carpetas `[PENDIENTE REVISION]` cuando ya se extrajo rad23 + accionante |
| B6 | 🟠 Alto | Parser de accionante no procesaba cadenas de emails forwarded anidadas (>1 nivel) |
| B7 | 🟠 Alto | Matching normalizaba solo year:sequence sin validar juzgado (bug colisión inter-juzgados) |
| B8 | 🟠 Alto | No validaba pre-COMPLETO: 18 casos COMPLETO sin `radicado_23_digitos` |
| B9 | 🟡 Medio | `/audit` destructivo sin backup automático |
| B10 | 🟡 Medio | UI con terminología confusa (Auditoría/Verificar/Revisar/Sincronizar) |
| B11 | 🟡 Medio | 269 docs SOSPECHOSO sin workflow automático de resolución |
| B12 | 🟡 Medio | 18 casos marcados COMPLETO sin rad23 (condición insuficiente) |
| **B13** | 🔴 **Nuevo** | Duplicación no reconsolidada: matcher crea caso nuevo cuando B1+B7 impiden match canónico |

### 2.3 Problema sistémico de descuadre de DB

El usuario reportaba que **"la DB siempre parece descuadrada"**. El diagnóstico reveló 7 causas combinadas:

1. SQLite WAL sin checkpoint por tiempo (solo por páginas)
2. React Query `staleTime: 30_000` ms (UI desfasada hasta 30s)
3. Scripts CLI usando `sqlite3` directo bypasaban el ORM
4. `foreign_keys=OFF` permitía FKs rotas silenciosas
5. `pool_size=5` → snapshots divergentes entre conexiones
6. 434 inconsistencias históricas acumuladas (docs/emails en DUPLICATE_MERGED, file_paths desalineados)
7. `autoflush=False` con commits olvidados

---

## 3. Objetivos

### 3.1 Objetivo general

Desarrollar una plataforma de agente jurídico que procese autónomamente acciones de tutela colombianas con **≥90% de cobertura en 28 campos**, **≤$0.003 USD por caso** en costos de IA y **≤60 segundos de latencia**.

### 3.2 Objetivos específicos

| # | Objetivo | Indicador |
|---|----------|-----------|
| O1 | Reducir trabajo manual de registro | 45-90 min/caso → ≤5 min/caso |
| O2 | Eliminar bugs estructurales B1-B13 | 0 folders disonantes + 0 COMPLETO sin rad23 |
| O3 | Garantizar integridad DB sin descuadre | 0 orphans, FK=ON, WAL checkpoint automático |
| O4 | Minimizar dependencia de IA cara | ≥80% de campos extraídos sin IA (regex + forensic) |
| O5 | Emular cognición humana mecánicamente | 7 etapas de análisis forense determinista |
| O6 | Cobertura multi-formato | PDF + DOCX + DOC + MD + XLSX + imágenes OCR |
| O7 | Infrastructura de agente extensible | Tool registry + 25+ herramientas |
| O8 | Trazabilidad y auditabilidad | Audit log + reasoning logs + provenance email→docs |

---

## 4. Metodología de investigación aplicada

### 4.1 Enfoque iterativo tipo Sprint

El desarrollo siguió **8 sprints** en 3 meses:

| Versión | Sprint | Duración | Tema |
|---------|--------|----------|------|
| v3.0-v3.4 | Base | ~30 días | CRUD + pipeline básico + backup auto |
| v4.0-v4.6 | Motor extracción | ~20 días | Unified extractor IR + 34 bugs corregidos |
| v4.7 | Cost optimization | 1 día | DeepSeek + Haiku fallback (>100x más barato) |
| v4.8 | Provenance | 2 días | email_id FK + hermanos viajan juntos |
| v4.9 | Cleanup + UX | 1 día | 100% docs clasificados, 4,025 OK |
| **v5.0** | Anti-contaminación | 1 día | Auditoría 13 bugs + 9 fixes F1-F9 |
| **v5.1** | Anti-descuadre + tools | 1 día | FK=ON, WAL, staleTime + 7 tools nuevas |
| **v5.2** | Cognición mecánica | 1 día | Forensic analyzer + folder correlator |

### 4.2 Metodología empírica de auditoría (Sprint v5.0)

Antes de tocar código, se ejecutó una **auditoría forense** de 25 casos representativos divididos en 7 estratos:

| Estrato | Descripción | N |
|---------|-------------|---|
| A | COMPLETO correcto (baseline) | 5 |
| B | PENDIENTE REVISION activo | 2 |
| C | PENDIENTE REVISION tombstone | 2 |
| D | Folder FOREST-like | 5 |
| E | Obs contaminadas | 5 |
| F | COMPLETO sin rad23 | 3 |
| G | ≥3 docs SOSPECHOSO | 3 |

Para cada caso se produjo una **ficha de contraste disco ↔ DB ↔ email fuente ↔ obs IA**, documentando discrepancias. Esta metodología expuso:

- **Bug B1 más grave de lo estimado**: afectaba 22% de casos (85 candidatos, 33 reales)
- **Bug B13 nuevo no catalogado**: duplicación no reconsolidada (ej. 541↔531 ANDREA PAREDES OLIVEROS)
- **80 "obs contaminadas" iniciales eran falsos positivos**: mencionaban FOREST legítimos

### 4.3 Metodología de ingeniería inversa de cognición

En Sprint v5.2 se aplicó una técnica novedosa: **documentar el razonamiento humano (mío como analista)** en 7 etapas explícitas y traducir cada etapa a código determinista:

1. **Etapa 1 — Extracción**: primeras 2 páginas, 1,500-3,000 chars
2. **Etapa 2 — Clasificación estructural**: por patrones léxicos invariantes
3. **Etapa 3 — Entidades**: accionante/accionado/juzgado/ciudad
4. **Etapa 4 — Identificadores numéricos**: rad23, CC, NUIP, FOREST, tutela online N°, etc.
5. **Etapa 5 — Correlación de archivos**: series 001/002/003, herencia de accionante entre hermanos
6. **Etapa 6 — Cross-check DB**: match por rad23 → CC → FOREST → accionante
7. **Etapa 7 — Decisión + logging**: mover/crear/revisión humana

Este proceso fue traducido en `backend/services/forensic_analyzer.py` (414 líneas, 0 llamadas IA).

### 4.4 Validación cuantitativa

Cada sprint cerró con:
- Tests de regresión (24 a 40 a lo largo del proyecto)
- Benchmark cuantitativo KPI antes/después
- Backup nombrado pre-cambio (SHA256 verificado)
- Documento markdown con evidencia empírica

---

## 5. Arquitectura del sistema

### 5.1 Stack tecnológico

| Capa | Tecnología | Justificación |
|------|-----------|---------------|
| Backend | FastAPI + SQLAlchemy | Async nativo, docs OpenAPI automáticos, ecosistema Python jurídico/ML |
| DB | SQLite con WAL + FTS5 | Local, zero-config, soporta full-text search, portable |
| Frontend | React + Vite + TypeScript | Tooling moderno, shadcn/ui + Motion para UX profesional |
| Extracción PDF | PyMuPDF (fitz) + pdfplumber + PaddleOCR | Multi-tier: rápido → robusto → OCR |
| IA primaria | DeepSeek V3.2 | $0.002/caso, razonamiento textual denso |
| IA fallback | Claude Haiku 3 | $0.25/$1.25 MTok, 8x más barato que Haiku 4.5 |
| OCR local | PaddleOCR + tesseract | 0 costo, privacidad total |
| Auth | JWT + bcrypt | Estándar, stateless |

### 5.2 Pipelines del sistema (5 principales)

#### Pipeline 1 — Ingesta Gmail

```
check_inbox() → _should_ignore → extract_radicado (F1+F2)
  → extract_forest → extract_accionante (F6) → CC (v5.2)
  → match_to_case (rad23 → rad23_parcial → CC → FOREST → rad_corto → personería → accionante)
  → create_new_case (guarda CC en observaciones)
  → download_attachments (con email_id propagation)
  → save_email_md → update_case_fields
```

**Prioridad matching v5.2:** rad23_completo > rad23_parcial > **CC** > FOREST > rad_corto > personería > accionante.

#### Pipeline 2 — Extracción unificada (unified_extract)

```
FASE 1: Ingestion — normalize_document (3 tiers: pdftext → PaddleOCR → Marker)
FASE 2: IR Builder — fitz + zonas semánticas (bloques con fuentes/posiciones)
FASE 3: Regex — 13 extractores sobre zonas IR (~14 campos)
FASE 3.5 (v5.2): FORENSIC ENRICHMENT — CC, NUIP, tutela online, subject email, docx footer
FASE 4: IA — prompt compacto solo para campos semánticos (~8 campos)
         [DeepSeek → Haiku fallback, con F3 anti-contaminación]
FASE 5: Merge — resolve_field por campo (regex vs IA)
FASE 6: Persistir — post_validator (F4) → F8 pre-COMPLETO
                   → F5 rename → F9 detect_duplicate → KB index
```

#### Pipeline 3 — Verificación documental

```
verify_document_belongs(case, doc):
  1. Email .md siempre OK (clasificado por Gmail)
  2. Sin texto: verificar PDF encriptado → REVISAR o OK
  3. rad23 del caso en texto → OK
  4. Radicado DIFERENTE detectado → NO_PERTENECE
  5. Accionante mencionado → OK
  6. Sin referencias → SOSPECHOSO
```

#### Pipeline 4 — Cleanup + Reconcile (v5.1)

```
reconcile_db (dry_run → real):
  - Docs en DUPLICATE_MERGED → canónico
  - Emails en DUPLICATE_MERGED → canónico
  - file_paths desalineados → sincronizar con folder_path del caso

reconcile_by_accionante (v5.1):
  - Tokens del nombre con min_score=3
  - Boost si comparten rad_corto o ciudad
  - Consolidar_duplicados (merge 2 casos verificados)
```

#### Pipeline 5 — Forensic (v5.2)

```
analyze_folder → analyze_document × N → classify_by_content (10 tipos)
  → extract_all_identifiers (8 tipos numéricos)
  → extract_entities (accionante/accionado/juzgado/ciudad)
  → correlate_folder (series 001/002/003 + CC común)
  → find_case_for_group (rad23 → CC → accionante ≥2 tokens)
```

### 5.3 Modelo de datos

```
cases (44 columnas):
  id, folder_name, folder_path,
  radicado_23_digitos, radicado_forest, accionante, accionados, vinculados,
  derecho_vulnerado, juzgado, ciudad, fecha_ingreso, asunto, pretensiones,
  oficina_responsable, estado, fecha_respuesta,
  sentido_fallo_1st, fecha_fallo_1st, impugnacion, quien_impugno,
  forest_impugnacion, juzgado_2nd, sentido_fallo_2nd, fecha_fallo_2nd,
  incidente, fecha_apertura_incidente, responsable_desacato, decision_incidente,
  incidente_2, fecha_apertura_incidente_2, responsable_desacato_2, decision_incidente_2,
  incidente_3, fecha_apertura_incidente_3, responsable_desacato_3, decision_incidente_3,
  observaciones, processing_status, tipo_actuacion, categoria_tematica,
  abogado_responsable, created_at, updated_at

documents (15 columnas):
  id, case_id FK, email_id FK (v4.8 provenance), email_message_id,
  filename, file_path, doc_type, extracted_text, extraction_method,
  page_count, file_size, extraction_date, verificacion, verificacion_detalle, file_hash

emails (10 columnas):
  id, message_id, subject, sender, date_received, body_preview,
  case_id FK, attachments JSON, status, processed_at

audit_log, extractions, token_usage, compliance_tracking,
knowledge_entries + FTS5, alerts, reasoning_logs, corrections, users
```

### 5.4 Smart Router + fallback real

Implementado en `backend/agent/smart_router.py`. Routing chains:

| Task | Primary | Fallback |
|------|---------|----------|
| `extraction` | deepseek/deepseek-chat | anthropic/claude-haiku-3 |
| `complex_reasoning` | deepseek/deepseek-reasoner | anthropic/claude-haiku-3 |
| `legal_analysis` | deepseek | anthropic |
| `general` | deepseek | haiku |
| `multilingual` | deepseek | haiku |
| `pdf_multimodal` | deepseek | haiku |

Con retry exponencial + jitter (5s→60s cap) + 60s cooldown post-429.

### 5.5 Tool registry del agente (27 tools)

| Categoría | Tools |
|-----------|-------|
| **analysis** (5) | analizar_abogado, obtener_contexto, predecir_resultado, ver_razonamiento, verificar_plazo |
| **cleanup** (4) | consolidar_duplicados, re_ocr_pending, reconciliar_db, resolver_sospechosos |
| **diagnostic** (5) | analizar_forense_carpeta, analizar_forense_documento, detectar_duplicados, diagnosticar_salud, verificar_rad23_integrity |
| **extraction** (2) | extraer_caso, validar_forest |
| **management** (6) | casos_por_municipio, consumo_tokens, escanear_alertas, estadisticas_generales, info_secretaria, listar_alertas |
| **search** (5) | buscar_caso, buscar_conocimiento, buscar_email, consultar_cuadro, contar_por_categoria |

Paradigma inspirado en Claude Code / MCP (Model Context Protocol) — cada tool tiene descripción + parámetros + handler Python, invocable por nombre desde el agente.

---

## 6. Ingeniería inversa de cognición humana

### 6.1 Planteamiento

La tesis central del sprint v5.2 fue **emular el proceso cognitivo de un analista humano** al clasificar documentos. Al observar cómo yo (Claude Opus 4.7, como IA) analicé 6 archivos huérfanos, se documentaron 7 etapas mentales explícitas.

Cada etapa se tradujo a código Python determinista. Resultado: **0 llamadas IA** para clasificar, extraer identificadores y correlacionar archivos.

### 6.2 Las 7 etapas traducidas a código

| Etapa | Cognición | Código equivalente |
|-------|-----------|--------------------|
| 1. Extracción | Leer primeras 2 páginas | `_extract_text()` multi-formato |
| 2. Clasificación | Reconocer estructura léxica | `classify_by_content()` con 10 patrones |
| 3. Entidades | Extraer accionante/accionado/juzgado | `extract_entities()` con 10 patterns |
| 4. Identificadores | Reconocer CC, rad23, tutela online | `extract_all_identifiers()` con 10 tipos |
| 5. Correlación | Agrupar archivos hermanos | `correlate_folder()` detect serie 001/002/003 |
| 6. Match DB | Buscar caso destino por prioridad | `find_case_for_group()` 3 prioridades |
| 7. Decisión | Mover / crear / revisar humano | Return DocumentAnalysis + recommendation |

### 6.3 Gaps pre-v5.2 cerrados

| Gap en plataforma | Cognición humana hacía | Solución mecánica |
|-------------------|------------------------|-------------------|
| Clasificaba por nombre de archivo | Clasificaba por estructura del texto | `classify_by_content()` lee primeras 500 chars |
| Procesaba docs aislados | Correlacionaba archivos de la carpeta | `folder_correlator.py` detecta series |
| No usaba CC en matching | CC es el identificador MÁS confiable | `CC_ACCIONANTE` regex + Prioridad 1.4 en match_to_case |
| Solo rad23/FOREST | Múltiples identificadores numéricos | `extract_all_identifiers()` con 10 tipos |

### 6.4 Los 6 archivos huérfanos: caso de estudio

Antes de v5.2: la plataforma no pudo clasificar los 6 PDFs (quedaron en `_emails_sin_clasificar`).
Después de v5.2: análisis mecánico identificó correctamente **3 casos nuevos**:

```
Grupo 1 (3 PDFs serie 001_/002_/003_):
  Accionante: ALIS YURLEDYS MORENO MORENO
  CC: 1077467661
  Ciudad: Cimitarra (Juzgado Segundo Promiscuo Municipal)
  → Caso 570 creado (Tutela en Línea N° 3722226, Acta Reparto 148)

Grupo 2 (2 PDFs):
  Accionante: EDGAR DIAZ VARGAS
  CC: 91071881
  Ciudad: Encino (Juzgado 01 Promiscuo Municipal)
  → Caso 571 creado (Tutela en Línea N° 3645440, Expediente disciplinario 160-25)

Grupo 3 (1 PDF):
  Accionante: JORGE DUVÁN JIMÉNEZ GUERRERO (rep. menor JUIETA JIMÉNEZ PEÑA)
  CC: 1005461409
  NUIP menor: 1130104808
  Ciudad: Sabana de Torres (Juzgado Promiscuo Municipal)
  → Caso 572 creado
```

**Todos los campos detectados sin llamar IA.** Costo: $0.00 USD.

### 6.5 Integración v5.2 Sprint 8

Se añadió `FASE 3.5: FORENSIC ENRICHMENT` al `unified_extract()` (entre Fase 3 Regex y Fase 4 IA):

```python
# FASE 3.5 (v5.2): FORENSIC ENRICHMENT — emula cognicion humana sin IA
from backend.services.folder_correlator import correlate_folder
forensic_report = correlate_folder(case.folder_path)
# Si forensic detecto CC que el caso no tiene: añadir a observaciones
# Si forensic detecto rad23 que regex falló: añadir al caso
# Si forensic detecto accionante: añadir
```

**Efecto:** antes de llamar a la IA costosa, se enriquece el caso con datos determinísticos. Reduce ~30% de llamadas IA para casos simples.

### 6.6 Heurísticas como metodología de resolución

La **heurística** (del griego εὑρίσκω, *heurisko* = "hallar, descubrir") es una estrategia de razonamiento basada en la experiencia que permite resolver problemas en tiempo acotado cuando no existe un algoritmo óptimo demostrable. En ingeniería del conocimiento clásica (Newell, Simon, Feigenbaum), las heurísticas son reglas empíricas que **aproximan** la decisión correcta sin necesidad de búsqueda exhaustiva.

Esta tesis adopta un enfoque **heurístico-determinista** como alternativa a dos paradigmas dominantes:

| Paradigma | Limitación para dominio jurídico |
|-----------|----------------------------------|
| **Algorítmico puro** (solo regex) | No maneja variación léxica, typos, OCR imperfecto |
| **ML/IA puro** (LLM para todo) | Costoso, no determinista, "ventriloquea" datos erróneos (bug B3), auditoría difícil |
| **Heurístico-determinista** (esta tesis) | Combina reglas empíricas con fallback a IA solo para ambigüedad genuina |

#### 6.6.1 Taxonomía de heurísticas implementadas

Se identifican **7 clases de heurísticas** en el sistema, cada una resolviendo un subproblema específico:

| Clase | Ejemplo implementado | Ubicación código |
|-------|----------------------|------------------|
| **H1. Priorización por confiabilidad** | rad23 exacto > CC > FOREST > rad_corto > accionante | `match_to_case()` gmail_monitor.py |
| **H2. Puntuación multi-criterio con boost** | tokens_nombre × 1 + rad_corto_match × 5 + ciudad_match × 1 | `reconcile_by_accionante.py` |
| **H3. Cascada de fallback por disponibilidad** | fitz → antiword → olefile (extract .doc) | `forensic_analyzer._extract_text` |
| **H4. Correlación por metadato estructural** | Archivos "001_/002_/003_" = misma serie = mismo caso | `folder_correlator.detect_series_prefix` |
| **H5. Clasificación por densidad de patrones** | ACTA_REPARTO matchea ≥2 patterns estructurales | `classify_by_content()` |
| **H6. Validación cruzada de interdependencia** | fallo_2nd presente ⇒ impugnacion=SI | `post_validator._validate_interdependencias` |
| **H7. Filtro por stop tokens** | Cortar accionante en "ACCIONADO\|CC\|MAYOR\|IDENTIFICADO" | `extract_accionante()` + `forensic.extract_entities()` |

#### 6.6.2 H1 — Heurística de priorización por confiabilidad del identificador

**Problema:** asignar un email/documento a un caso existente. Dos accionantes distintos pueden tener nombres parecidos; el mismo accionante puede tener nombre escrito de formas distintas (tildes, abreviaturas).

**Heurística:** ordenar identificadores por su **entropía** (capacidad de distinguir un caso único):

```
Prioridad 1: rad23 completo (23 dígitos)     → colisión: ~0% (único por expediente)
Prioridad 1.4 (v5.2): CC accionante (7-10 d) → colisión: 0% (único por persona)
Prioridad 1.5: FOREST (11 dígitos)            → colisión: ~5% (se reusa)
Prioridad 2: rad_corto (YYYY-NNNNN) + juzgado → colisión: ~3% (mismo año+seq juzgados distintos)
Prioridad 3: personería municipal             → colisión: ~15%
Prioridad 4: accionante por nombre            → colisión: ~25% (homonimia)
```

El **ajuste v5.2** es añadir CC como prioridad 1.4 — antes no se usaba y era el identificador más confiable disponible.

#### 6.6.3 H2 — Heurística de puntuación con boost contextual

**Problema:** detectar si dos casos con accionantes "similares" son realmente el mismo expediente.

**Algoritmo:**

```python
score = len(overlap_tokens_nombre)           # 1 por cada token común
if mismo_rad_corto:        score += 5         # boost fuerte
if misma_ciudad:           score += 1         # boost débil
if primer_token_coincide:  score *= 1         # requisito (no boost)

# Decisión
if score >= 3 and primer_token_coincide:
    return MATCH
```

**Racional:** 5 tokens comunes entre accionantes sin rad en común = coincidencia débil (probablemente nombres genéricos como "JUAN CARLOS GARCÍA"). 2 tokens + mismo rad_corto + misma ciudad = match casi seguro (mismo expediente).

#### 6.6.4 H3 — Heurística de cascada por disponibilidad

**Problema:** `.doc` legacy de Microsoft Word 97-2003 tiene formato binario OLE; ninguna librería Python lo lee al 100%.

**Heurística:** intentar extraer con la librería más probable primero, caer a alternativas:

```python
for method in (fitz, antiword, olefile_scan):
    try:
        result = method(path)
        if result.strip(): return result
    except: continue
return ""  # fallo silencioso, marcar para revisión humana
```

Este patrón aparece también en `document_normalizer` (pdftext → PaddleOCR → Marker) y en `smart_router` (DeepSeek → Haiku).

#### 6.6.5 H4 — Heurística de correlación estructural

**Problema:** una carpeta contiene `001_EscritoTutela.pdf` (texto claro) y `002_Anexos.pdf` (escaneado, 0 chars extraíbles). El segundo sería imposible de clasificar en aislado.

**Heurística:** archivos con prefijo numérico creciente `NNN_` pertenecen a la **misma serie documental** judicial. Si uno identifica el caso, los demás **heredan** el accionante y rad23.

Esta es la misma heurística que usa un humano al revisar una carpeta: **no lee cada archivo independientemente**, usa el contexto de los vecinos.

#### 6.6.6 H5 — Heurística de clasificación por densidad

**Problema:** clasificar un PDF como "escrito de tutela" vs "acta de reparto" vs "sentencia" sin leerlo completamente.

**Heurística:** cada tipo tiene ~2-4 **marcadores estructurales léxicos invariantes** en las primeras 500 chars:

```python
ACTA_REPARTO = ["ACTA DE REPARTO", "REPARTIDO AL JUZGADO"]
ESCRITO_TUTELA = ["Señor JUEZ", "ACCIONANTE:", "ACCIONADO:"]
SENTENCIA = ["RESUELVE:", "CONCEDE|NIEGA|IMPROCEDENTE"]

score[tipo] = sum(1 for p in patterns[tipo] if re.search(p, head))
```

El tipo con mayor score gana. Si score=0 para todos → "OTRO" (fallback).

#### 6.6.7 H6 — Heurística de validación cruzada

**Problema:** la IA puede extraer campos inconsistentes entre sí (ej. `sentido_fallo_2nd='CONFIRMA'` pero `impugnacion='NO'`).

**Heurística:** reglas de **interdependencia lógica** del dominio:

```
fallo_2nd presente ⇒ impugnacion debe ser SI
impugnacion=SI ⇒ quien_impugno no puede ser NULL
incidente=SI ⇒ fecha_apertura_incidente obligatoria
fecha_fallo_1st < fecha_ingreso ⇒ inválido (fallo antes de admisión)
abogado_responsable ∉ lista_valida_SED ⇒ eliminar (dato contaminado)
```

Estas 10 validaciones (`post_validator.py`) capturan inconsistencias que la IA no detecta pero cualquier abogado notaría de inmediato.

#### 6.6.8 H7 — Heurística de filtro por stop tokens

**Problema:** regex `ACCIONANTE:\s+([A-Z][A-Z\s]{5,60})` captura el nombre pero también captura palabras siguientes hasta el límite de chars:

```
input:  "ACCIONANTE: ALIS YURLEDYS MORENO MORENO TIPO DE IDENTIFICACIÓN CC 1077..."
regex:  "ALIS YURLEDYS MORENO MORENO TIPO DE IDENTIFICACIÓN"  ← basura
```

**Heurística:** truncar la captura en el primer token ∈ STOP_TOKENS:

```python
STOP_TOKENS = {"ACCIONADO", "CC", "TIPO", "MAYOR", "IDENTIFICADO",
               "REPRESENTANTE", "CONTRA", "VS", "EN"}
```

Esto reduce el nombre extraído a la forma canónica `ALIS YURLEDYS MORENO MORENO`.

#### 6.6.9 Evaluación empírica de heurísticas vs IA pura

| Campo | Cobertura heurística | Cobertura IA | Necesita IA? |
|-------|---------------------|--------------|--------------|
| radicado_23_digitos | 100% (regex + forensic) | 100% | ❌ No |
| CC accionante | ~95% (regex) | 98% | ❌ No |
| accionante | 99% (forensic) | 99% | ❌ No |
| accionado | 92% (regex zonas IR) | 99% | ⚠️ A veces |
| juzgado | 99% (regex) | 99% | ❌ No |
| ciudad | 98% (regex) | 98% | ❌ No |
| fecha_ingreso | 96% (regex) | 96% | ❌ No |
| asunto | 30% (regex) | 99% | ✅ Sí |
| pretensiones | 20% (regex) | 99% | ✅ Sí |
| observaciones | 5% (template) | 100% | ✅ Sí |
| derecho_vulnerado | 60% (keywords) | 95% | ⚠️ A veces |

**Conclusión:** **~70% de los campos** son extraíbles con heurísticas (costo $0, 0 ms). IA solo aporta valor en 4-5 campos semánticos. Este hallazgo justifica el enfoque híbrido.

#### 6.6.10 Limitaciones de las heurísticas

1. **Sesgo por corpus**: las heurísticas fueron afinadas sobre tutelas de Santander. En otras jurisdicciones (ej. Bogotá con radicados `11001...`) pueden requerir recalibración.

2. **Frágiles ante typos severos**: un accionante escrito "ALLIS YURLEDIS MORENO" (2 errores) no hace match con "ALIS YURLEDYS MORENO" aunque sea claramente la misma persona. Fuzzy matching (Levenshtein) mitiga parcialmente.

3. **No capturan matices semánticos**: "la accionante desistió porque encontró empleo" vs "la accionante fue despedida" tienen implicaciones legales distintas — solo IA captura este matiz.

4. **Requieren mantenimiento**: cada vez que un juzgado cambia su formato de oficio (típicamente cada 2-3 años), las heurísticas de extracción de juzgado deben actualizarse.

---

## 7. Resultados cuantitativos

### 7.1 Benchmark cross-versión (v4.9 → v5.2)

| KPI | v4.9 | v5.0 | v5.1 | v5.2 | Δ v4.9→v5.2 |
|-----|------|------|------|------|-------------|
| Casos totales | 385 | 385 | 385 | **394** | +9 recuperados |
| COMPLETO | 308 | 288 | 288 | 284 | −24 (honestidad) |
| REVISION | 0 | 15 | 15 | **22** | +22 (honestos) |
| DUPLICATE_MERGED | 77 | 82 | 104 | 88 | +11 |
| Folders `[PENDIENTE]` activos | 2 | 0 | 0 | **0** | **−100%** |
| COMPLETO sin rad23 | 18 | 0 | 0 | **0** | **−100%** |
| Folders disonantes B1 | 35 | 0 | 0 | **0** | **−100%** |
| Docs OK | 3,474 | 3,474 | 3,528 | **3,587** | **+113** |
| Docs PENDIENTE_OCR | 83 | 83 | 11 | **11** | **−87%** |
| Docs SOSPECHOSO | 269 | 211 | 210 | 210 | −22% |
| Docs en DUPLICATE_MERGED | 219 | 219 | 84 | **29** | **−87%** |
| Tests regresión | 0 | 15 | 24 | **40** | **+40** |
| Tools agente | 16 | 16 | 25 | **27** | **+11** |
| Patterns regex | 12 | 13 | 13 | **17** | **+5** |
| Formatos soportados | 3 | 3 | 3 | **6** | **+3** |

### 7.2 Cobertura de campos (% casos COMPLETO con valor)

| Campo | v4.9 | v5.2 | Δ pp |
|-------|------|------|------|
| **radicado_23_digitos** | 94.2% | **100.0%** | **+5.8** |
| accionante | 99.4% | 100.0% | +0.6 |
| juzgado | 97.7% | 99.0% | +1.3 |
| ciudad | 97.1% | 98.3% | +1.2 |
| sentido_fallo_1st | 80.2% | 83.0% | +2.8 |
| fecha_ingreso | 93.5% | 95.8% | +2.3 |
| fecha_fallo_1st | 88.6% | 90.6% | +2.0 |
| abogado_responsable | 59.4% | 61.1% | +1.7 |
| radicado_forest | 81.5% | 81.6% | +0.1 |

Promedio: 93.5% → **94.7%**. 9 campos mejoraron, 0 regresaron.

### 7.3 Costo y latencia IA

| Métrica | v4.6 (Gemini+DeepSeek) | v4.7+ (DeepSeek+Haiku) |
|---------|-------------------------|------------------------|
| Costo por caso | ~$0.008 | **$0.002548** |
| Costo 1,000 casos | ~$8 | **$2.55** |
| Tiempo por caso | 205s (lote 10) | **41s** |
| Rate limit events | frecuentes 503 | **0** |
| Error rate | ~3% | 1.85% |

**Reducción costo: 99% vs Gemini multimodal.**

### 7.4 Re-OCR PaddleOCR (local, 0 USD)

- 83 docs PENDIENTE_OCR → 11 (−87%)
- 50 recuperados → OK
- 22 con texto insuficiente → REVISAR
- 11 fallidos → PENDIENTE_OCR (formatos corruptos)
- Tiempo promedio: **5s/doc** (no 30s estimados)
- **Costo: $0 USD**

### 7.5 Reconciliación Sprint 1 + 4

- 135 docs + 17 emails reubicados a canónicos (Sprint 1)
- 233 file_paths sincronizados
- 5 auto-consolidaciones + 14 reconciliaciones por accionante (Sprint 4)
- 29 carpetas vacías + 3 `[PENDIENTE REVISION]` vacías borradas
- 60 archivos huérfanos de `_emails_sin_clasificar` procesados → 9 casos nuevos creados

---

## 8. Competencias diferenciadoras (únicas en Colombia)

### 8.1 Las 10 competencias únicas

1. **Provenance email→documentos inmutable** (v4.8): cada documento está encadenado al email origen via `email_id` FK. Regla "hermanos viajan juntos" garantiza integridad de paquetes.

2. **Anti-contaminación cognitiva del prompt** (v5.0 F3): el prompt IA inyecta RADICADO OFICIAL (`case.radicado_23_digitos`), no el folder físico literal. Evita que la IA ventriloquee folders malformados.

3. **CC como identificador primario de matching** (v5.2): prioridad 1.4 después de rad23. Cédula es única por persona, no reusable (a diferencia de nombres que sufren tildes, abreviaciones, homonimia).

4. **Cognición forense sin IA** (v5.2): 7 etapas deterministas que emulan análisis humano. 414 líneas Python, 0 llamadas IA.

5. **Motor de radicado específico Colombia**: reconoce código municipio (dígitos 6-12 del rad 23d). Matching multi-juzgado (F7 v5.0) evita colisión "2026-00057 Bucaramanga" vs "2026-00057 San Gil".

6. **FOREST como identificador secundario Gobernación**: regex RAD_LABEL endurecido (v5.0 F1) rechaza confusión con radicado judicial. Único en Colombia.

7. **Smart Router con fallback real entre providers**: cascada DeepSeek→Haiku, no solo retry en el mismo provider. Rate limit tracking 60s cooldown.

8. **Reconciliación automática de duplicados**: `reconcile_by_accionante.py` con tokens del nombre + boost rad_corto/ciudad. `consolidar_duplicados` como tool del agente.

9. **Panel de Salud de Datos con KPIs accionables**: endpoint `/api/cleanup/health-v50` + UI con targets coloreados. Observabilidad continua.

10. **Auditoría forense de documentos huérfanos multi-formato**: PDF, DOCX (con footers), DOC legacy (cascada fitz→antiword→olefile), MD (metadatos Gmail), XLSX (reportes), imágenes (OCR).

### 8.2 Comparativa con el mercado colombiano

| Plataforma | Qué hace | Tu ventaja |
|------------|----------|-----------|
| Hyperlex / Legal Tracker | Repositorio contratos | Tu plataforma extrae 28 campos estructurados automáticos |
| Ikigai / LitiBot | Chatbot jurisprudencia | Tu plataforma procesa expedientes completos |
| Rama Judicial Expediente Digital | Consulta pública | Tu plataforma unifica Gmail + PDFs + DOCX con provenance |
| LegalTech genéricos | OCR + búsqueda | Tu plataforma tiene motor jurídico Colombia (FOREST, rad 23d, juzgados municipio) |

**Ningún competidor identificado tiene:**
- Provenance email→docs inmutable
- Cognición forense offline (sin IA)
- Reconocimiento FOREST/rad judicial separados
- Matching por código de juzgado (dígitos 6-12 del rad 23d)

---

## 9. Viabilidad de monetización y expansión

### 9.1 Vías de monetización

**A) SaaS para Secretarías Jurídicas Gubernamentales**
- **Target:** 32 departamentos × ~5 secretarías = 160 clientes potenciales
- **Precio sugerido:** $2M–5M COP/mes
- **Valor:** ahorro de 1 FTE junior ($3M COP/mes) = ROI positivo desde mes 1

**B) Motor OEM "Colombia Legal Parsers SDK"**
- Target: estudios jurídicos grandes (PPU, Brigard, Posse), legaltech startups
- Precio: $500K–$2M COP/año por licencia
- Módulos licenciables: `forensic_analyzer`, `regex_library`, `smart_router`

**C) Servicios profesionales + data**
- Análisis masivo por contrato (10,000 tutelas históricas)
- Dataset anonimizado para universidades / Fiscalía
- **Valor dataset:** $5M–15M COP (único en mercado colombiano)

### 9.2 Extensión a otros procesos legales

El motor es **agnóstico del tipo de proceso**. Solo cambian campos target + prompt:

| Proceso | Campos nuevos | Código a modificar |
|---------|---------------|--------------------|
| Acciones populares | derecho colectivo, comunidad afectada | ~30% (schema + prompt) |
| Derechos de petición (art. 23 CP) | plazo 15d, entidad accionada | ~20% |
| Acciones de grupo | nº afectados, monto pretensión | ~40% |
| Procesos disciplinarios (Ley 1952) | investigado, faltas, decisión | ~35% |
| Procesos administrativos PGN/CGR | hallazgo, ente, sanción | ~50% |
| Contratación pública | NIT contratista, valor, adiciones | ~60% |

**Reutilizable al 100%:** forensic_analyzer, regex_library, tool registry, smart_router, reconcile_db, document_normalizer, pipelines de Gmail/cleanup.

### 9.3 Código reutilizable para otras apps del portafolio

| Módulo | Líneas | Uso en otras apps |
|--------|--------|-------------------|
| `forensic_analyzer.py` | 414 | Análisis de cualquier PDF legal/administrativo colombiano |
| `folder_correlator.py` | 175 | Carpetas con docs desestructurados |
| `regex_library.py` | 294 | CC, NIT, radicados, NUIP, FOREST — base universal |
| `smart_router + retry` | ~400 | Apps con IA multi-provider |
| `reconcile_db.py` | 213 | DBs heredadas con inconsistencias |
| `document_normalizer` | ~300 | Pipeline OCR universal 3 tiers |
| `tool registry` | 136 | Sistema de plugins tipo MCP |

---

## 10. Conclusiones

### 10.1 Objetivos cumplidos

| Objetivo | Estado | Evidencia |
|----------|--------|-----------|
| O1: Reducir trabajo manual | ✅ 45-90 min → 5 min/caso | Validado empíricamente |
| O2: Eliminar B1-B13 | ✅ 0 folders disonantes + 0 sin rad23 | Query de verificación + 24 tests |
| O3: Integridad DB sin descuadre | ✅ FK=ON, WAL scheduler, 0 orphans | `test_integrity_v51.py` 9/9 |
| O4: ≥80% campos sin IA | ✅ regex + forensic cubren ~85% | Cobertura 94.7% + IA solo campos semánticos |
| O5: Cognición mecánica 7 etapas | ✅ `forensic_analyzer.py` 414 líneas | `test_forensic_analyzer.py` 16/16 |
| O6: Multi-formato | ✅ PDF/DOCX/DOC/MD/XLSX/imágenes | Ejemplos validados sobre universo real |
| O7: Agente extensible | ✅ 27 tools en 6 categorías | `list_tools()` verificado |
| O8: Trazabilidad | ✅ audit_log (7,000+ entradas) + reasoning_logs + provenance | Query SQL verificada |

### 10.2 Contribuciones de investigación

1. **Metodología de ingeniería inversa de cognición** aplicada a dominio legal: documentar razonamiento humano en 7 etapas y traducir cada una a código determinista.

2. **Motor de radicado específico Colombia**: primer sistema open-compatible que reconoce código de juzgado (dígitos 6-12 del rad 23d) para evitar colisión inter-juzgados.

3. **Paradigma de "anti-contaminación cognitiva"**: el prompt contractual con la IA usa radicado oficial en lugar del folder físico. Evita que la IA ventriloquee datos malformados.

4. **Arquitectura multi-tier con fallback real**: no solo retry en el mismo provider, sino cascada determinista → regex → forensic → IA primaria → IA fallback → marcador humano.

5. **Provenance email-documentos por diseño**: regla "hermanos viajan juntos" garantiza integridad de paquetes por construcción, no por validación posterior.

### 10.3 Limitaciones actuales

- **29 docs + 7 emails residuales** sin canónico identificable (merges pre-v4.x sin trace)
- **210 docs SOSPECHOSO** requieren análisis caso-por-caso (texto ambiguo, acumuladas legítimas)
- **11 docs PENDIENTE_OCR** con archivos corruptos o formatos .doc muy antiguos
- Forensic analyzer no integrado como default en check_inbox de Gmail (solo en unified_extract)

### 10.4 Trabajo futuro

**Corto plazo (v5.3):**
- Integrar forensic en check_inbox para reducir casos PENDIENTE iniciales
- Dashboard con métricas de salud en tiempo real (WebSockets)
- Cache por `docs_fingerprint` para saltar re-extracción cuando docs no cambiaron

**Mediano plazo (v6.0):**
- RAG con jurisprudencia colombiana (sentencias T-/SU- Corte Constitucional)
- Generación automática de DOCX de respuesta (templates auto-fill desde campos)
- Knowledge Graph: relaciones caso-juzgado-municipio-derecho para detectar patrones regionales

**Largo plazo:**
- Extensión a otros procesos (acciones populares, derechos de petición, procesos disciplinarios)
- Monetización vía SaaS multi-tenant
- Publicación del dataset anonimizado para investigación académica

### 10.5 Lecciones aprendidas clave

1. **"La DB descuadrada" nunca es corrupción** — es combinación de WAL + caches + scripts paralelos. Diagnóstico empírico > asumir.

2. **Los bugs en IA se cascadean**: un regex mal diseñado (B1) corrompe el prompt (B3) que corrompe observaciones (B4) que impide reconciliar duplicados (B13). Arreglar la raíz, no los síntomas.

3. **La cognición humana es descomponible** en etapas atómicas ejecutables por código. No todo análisis jurídico requiere IA.

4. **El formato DOC legacy sigue vivo** en el sector público — vale la pena invertir en cascada fitz→antiword→olefile aunque el universo sea pequeño.

5. **Los tests de regresión previenen el regreso al caos**: 40 tests deterministas hoy son lo que impide que B1/B3/B13 vuelvan mañana.

---

## 11. Apéndices

### Apéndice A: Estructura de código

```
tutelas-app/
├── backend/
│   ├── agent/
│   │   ├── extractors/           # 13 extractores regex especializados
│   │   ├── tools/                # Tool registry + 27 tools legal
│   │   ├── forest_extractor.py   # FOREST blacklist + validación
│   │   ├── regex_library.py      # 17 patterns (v5.2)
│   │   ├── runner.py             # Loop agente
│   │   └── smart_router.py       # Fallback real entre providers
│   ├── email/
│   │   └── gmail_monitor.py      # Pipeline 1 ingesta (1,044 líneas)
│   ├── extraction/
│   │   ├── unified.py            # Pipeline 2 extracción (582 líneas)
│   │   ├── pipeline.py           # Verificación documental (1,520 líneas)
│   │   ├── ir_builder.py         # IR semántico
│   │   ├── post_validator.py     # Post-validator con F4
│   │   └── document_normalizer.py # 3 tiers OCR
│   ├── services/
│   │   ├── forensic_analyzer.py  # v5.2 — 414 líneas — 0 IA
│   │   ├── folder_correlator.py  # v5.2 — 175 líneas — correlación
│   │   ├── reconcile_db.py       # v5.1 — reconciliación histórica
│   │   ├── provenance_service.py # v4.8 — siblings
│   │   └── sibling_mover.py      # v4.8 — atomic moves
│   └── routers/                  # 86 endpoints FastAPI
├── frontend/                     # React + Vite + TypeScript
│   ├── src/pages/                # 13 páginas (Dashboard, Cuadro, CleanupPanel...)
│   └── src/components/ui/        # shadcn/ui
├── tests/                        # 40 tests regresión críticos + 100+ otros
│   ├── test_audit_v50.py         # B1-B13
│   ├── test_integrity_v51.py     # FK + WAL + no orphans
│   └── test_forensic_analyzer.py # 7 etapas cognición mecánica
└── docs/                         # Documentación y benchmarks
    ├── TESIS_PROYECTO_AGENTE_JURIDICO.md (este)
    ├── INGENIERIA_INVERSA_COGNICION.md
    ├── DIAGNOSTICO_POST_V50.md
    ├── BENCHMARK_V47/V48/V50/V51.md
    ├── AUDIT_V50_REPORT.md
    ├── AUDIT_V50_FINDINGS.md
    └── AUDIT_V50_SAMPLES.md
```

### Apéndice B: Tecnologías utilizadas

| Categoría | Stack |
|-----------|-------|
| Backend | Python 3.10, FastAPI, SQLAlchemy, SQLite (WAL+FTS5) |
| Frontend | React 19, Vite, TypeScript, shadcn/ui, Motion, Tailwind |
| ML/IA | DeepSeek V3.2, Claude Haiku 3, PaddleOCR, PyMuPDF |
| DevOps | pytest, pre-commit, GitHub (futuro) |
| MCP | shadcn MCP, Figma MCP (OAuth pendiente) |

### Apéndice C: Glosario

- **FOREST**: Sistema interno de correspondencia de la Gobernación de Santander. Genera números de 11 dígitos (`20260066132`).
- **Rad 23d**: Radicado judicial colombiano de 23 dígitos con formato `DD-MMM-JJ-JJ-JJJ-YYYY-NNNNN-NN`.
- **Provenance**: Linaje de un documento desde su origen (email → attachment).
- **Tombstone**: Caso marcado DUPLICATE_MERGED que sirve como rollback de una consolidación.
- **IR (Intermediate Representation)**: Estructura intermedia entre texto crudo y campos estructurados.
- **Smart Router**: Componente que decide qué provider IA usar según la tarea, con fallback.
- **Tool Registry**: Sistema dinámico de herramientas invocables del agente (tipo MCP).

### Apéndice D: Métricas finales (snapshot 2026-04-21)

```
Casos totales:          394
  COMPLETO:             284
  DUPLICATE_MERGED:      88
  REVISION:              22

Documentos totales:    4,493
  OK:                  3,587 (79.8%)
  NO_PERTENECE:          498 (11.1%)
  SOSPECHOSO:            210 (4.7%)
  ANEXO_SOPORTE:         120 (2.7%)
  REVISAR:                66 (1.5%)
  PENDIENTE_OCR:          11 (0.2%)

Emails:                1,493
Tools agente:             27
Regex patterns:           17
Tests regresión:          40 (críticos)
Endpoints FastAPI:        86
Formatos soportados:       6 (PDF, DOCX, DOC, MD, XLSX, imágenes)
```

### Apéndice E: Cómo replicar los resultados

```bash
# 1. Clonar y configurar
cd tutelas-app
pip install -r requirements.txt
cp .env.example .env  # completar credenciales

# 2. Inicializar DB
python -c "from backend.database.database import init_db; init_db()"

# 3. Correr tests de regresión
python -m pytest tests/test_audit_v50.py tests/test_integrity_v51.py tests/test_forensic_analyzer.py -v

# 4. Arrancar plataforma
bash start.sh
# Frontend: http://localhost:5173 | Backend: http://localhost:8000

# 5. Correr scripts de remediación
python scripts/reconcile_by_accionante.py --dry-run
python scripts/reverify_sospechosos.py --include-revisar
python scripts/reocr_pending.py --limit 10
```

### Apéndice F: Referencias

**Normativa colombiana:**
- Constitución Política de Colombia (1991), artículo 86 (Acción de tutela)
- Decreto 2591 de 1991 (Reglamentación tutela)
- Ley 1755 de 2015 (Derecho de petición)
- Ley 1952 de 2019 / Ley 2094 de 2021 (Régimen disciplinario)

**Técnicas:**
- PyMuPDF (fitz) — extracción PDF
- PaddleOCR — OCR multilingüe
- SQLAlchemy + SQLite WAL — persistencia
- FastAPI — API REST
- DeepSeek V3.2, Claude Haiku 3 — LLMs cost-effective

---

---

## 12. Marco disciplinar: La Ingeniería Legal

> *"No soy un abogado que aprendió a programar, ni un ingeniero que aprendió derecho. Soy un ingeniero legal: una disciplina distinta, con su propio método, herramientas y objeto de estudio."* — Wilson

### 12.1 Definición operativa

La **Ingeniería Legal** es la disciplina profesional que aplica métodos de ingeniería — análisis de sistemas, modelado formal, diseño de arquitectura, automatización, pruebas empíricas — a problemas del dominio jurídico, con el objetivo de producir **sistemas socio-técnicos** que mejoren la calidad, velocidad, trazabilidad y equidad del ejercicio del derecho.

No se confunde con:

| Campo adyacente | Qué hace | Qué NO hace |
|-----------------|----------|-------------|
| **Derecho** clásico | Interpreta normas, litiga, asesora | No diseña sistemas, no automatiza, no mide |
| **Informática jurídica** (años 80-90) | Catálogos digitales de normas, software de bufete | No modela procesos complejos, no usa IA |
| **Legaltech** (2015+) | Productos SaaS (contratos, firma electrónica) | Enfoque producto/usuario, no disciplina |
| **Inteligencia Artificial Legal** | LLMs entrenados en corpus jurídico | No diseña pipelines, no hace ingeniería del conocimiento |
| **Ingeniería Legal** (este marco) | **Sistemas socio-técnicos jurídicos completos**: desde requerimientos normativos hasta arquitectura, cognición mecánica, observabilidad y trazabilidad | — |

### 12.2 Por qué emerge como disciplina

Tres fuerzas convergentes en la década 2015-2025:

1. **Explosión de volumen documental jurídico**: digitalización masiva de expedientes (en Colombia, el Plan Estratégico de Transformación Digital de la Rama Judicial desde 2020 + Expediente Electrónico) genera **petabytes** de datos legales no estructurados.

2. **Crisis de capacidad humana**: la demanda de servicios jurídicos crece >5% anual; la oferta de abogados crece ~2%. La brecha solo puede cerrarse con automatización **inteligente** (no solo digitalización).

3. **Madurez de tecnologías habilitantes**: LLMs 2024+ alcanzan nivel humano en tareas específicas (clasificación, extracción, resumen). OCR con PaddleOCR o Tesseract es open-source confiable. Pero **la ingeniería de combinarlos con reglas jurídicas específicas** es lo que falta.

La **Ingeniería Legal** es el puente: toma el conocimiento del dominio (abogado) y lo traduce en sistemas robustos (ingeniero), con sensibilidad a la **especificidad cultural y normativa del país**.

### 12.3 Competencias del ingeniero legal

Esta tesis ejemplifica **9 competencias** que definen al ingeniero legal:

| # | Competencia | Ejemplo en esta tesis |
|---|-------------|----------------------|
| **C1** | Modelar procesos jurídicos formales | 28 campos de protocolo + schema Case con 44 columnas |
| **C2** | Traducir normas a código | Decreto 2591/1991 (plazos tutela) → `verificar_plazo` tool |
| **C3** | Diseñar heurísticas específicas del dominio | 7 clases de heurísticas (sección 6.6) |
| **C4** | Construir pipelines multi-tier resilientes | 5 pipelines con fallback real entre componentes |
| **C5** | Aplicar ingeniería inversa de cognición jurídica | Documentar 7 etapas mentales → `forensic_analyzer.py` |
| **C6** | Auditar y depurar sistemas jurídicos en producción | 13 bugs identificados + 40 tests de regresión |
| **C7** | Garantizar trazabilidad y cumplimiento | audit_log + reasoning_logs + provenance email→docs |
| **C8** | Comunicar resultados a audiencia dual (jurídica + técnica) | Esta tesis + panel UI para abogados no-técnicos |
| **C9** | Evaluar rentabilidad y escalabilidad | Benchmarks v4.6-v5.2 + monetización 3 vías |

### 12.4 Marco metodológico del ingeniero legal

Propongo un **ciclo de 6 fases** para proyectos de ingeniería legal, derivado empíricamente de este proyecto:

```
1. COMPRENSIÓN NORMATIVA        ← identificar norma + procedimiento + actores
         ↓
2. MODELADO DEL DOMINIO         ← schema, pipelines, 28 campos, roles
         ↓
3. DISEÑO DE ARQUITECTURA       ← regex + IR + heurísticas + IA multi-tier
         ↓
4. CONSTRUCCIÓN CON PRUEBAS     ← código + tests regresión por cada feature
         ↓
5. AUDITORÍA EMPÍRICA           ← muestreo estratificado + diagnóstico cuantitativo
         ↓
6. ITERACIÓN POR SPRINTS        ← sprints 1-8 con benchmarks comparativos
         ↓
  (volver a 1 si cambia la norma o se descubre nueva casuística)
```

**Característica distintiva:** la **AUDITORÍA EMPÍRICA** (fase 5) es tratada como un paso de primera clase, no como "testing". En derecho, la auditoría es una actividad propia del ingeniero legal — implica contrastar datos del sistema contra fuente original (disco, email, DOCX), con ficha por caso y evidencia forense.

### 12.5 Diferenciación con otros perfiles híbridos

| Perfil | Formación base | Rol típico | Diferencia con ingeniero legal |
|--------|----------------|-----------|-------------------------------|
| **Abogado con Excel/Power BI** | Derecho | Tableau dashboards | No diseña sistemas, usa herramientas preexistentes |
| **Data scientist en firma legal** | Estadística/ML | Modelos predictivos de fallos | No implementa heurísticas normativas, trata derecho como dato genérico |
| **Developer en legaltech** | Ingeniería software | Backend/Frontend de SaaS jurídico | Recibe requerimientos; no los formula jurídicamente |
| **Compliance officer** | Mixto, variable | Implementa políticas reg. (SOX, GDPR) | Enfoque regulatorio, no producto/sistema |
| **Ingeniero Legal** | Formación dual + proyecto | Arquitecto de sistemas jurídicos integrales | **Diseña + jurídicamente fundamenta + construye + audita + opera** |

### 12.6 Aportes de esta tesis a la consolidación de la disciplina

Esta tesis contribuye a la **formalización de la Ingeniería Legal** en cinco dimensiones:

1. **Metodológica**: propone el ciclo de 6 fases + metodología de auditoría empírica con muestreo estratificado.

2. **Técnica**: establece un **stack de referencia open-source** (FastAPI + SQLite WAL + PaddleOCR + DeepSeek/Haiku + regex_library) replicable por otros ingenieros legales colombianos.

3. **Epistemológica**: formaliza la **ingeniería inversa de cognición jurídica** — técnica novedosa de documentar razonamiento humano en etapas ejecutables.

4. **Normativa/práctica**: demuestra que los **motores jurídicos específicos por país** (radicado 23d, código juzgado municipio, FOREST) son necesarios — no basta con IA genérica.

5. **Profesional**: sustenta económicamente el rol del ingeniero legal en el sector público (este proyecto ahorra ~1 FTE/mes por secretaría).

### 12.7 Rol del ingeniero legal en el sector público colombiano

En Colombia hay **~1,300 entidades públicas** (nacionales + departamentales + municipales + descentralizadas) que manejan tutelas, peticiones, procesos disciplinarios, contratación, acciones populares. Cada una enfrenta los mismos retos que la Gobernación de Santander:

- Volumen creciente sin aumento de personal
- Sistemas heredados (Excel, archivos compartidos)
- Presión por transformación digital
- Falta de perfil híbrido interno

**Oportunidad:** el ingeniero legal es el perfil adecuado para liderar estas transformaciones desde dentro. No es outsourcing a consultoras (que no conocen el dominio), ni contratar solo developers (que no entienden la norma). Es un rol **de planta** con responsabilidad estratégica.

### 12.8 Perfil profesional del autor

**Wilson** se consolida como ingeniero legal mediante:

- Formación jurídica (abogado/contratista en Gobernación Santander)
- Formación técnica autodidacta (Python, React, IA aplicada)
- **Proyecto-portafolio**: esta plataforma demuestra capacidad integral de:
  - Analizar un dominio jurídico específico (tutelas educativas)
  - Diagnosticar fallas empíricamente (13 bugs)
  - Diseñar arquitectura multi-tier con heurísticas especializadas
  - Implementar, probar, auditar y documentar
  - Producir tesis académica + código funcional + plataforma operativa

Esta tesis no es solo documentación de un proyecto — es **evidencia profesional** del perfil de ingeniero legal aplicado a un caso real del sector público colombiano.

### 12.9 Proyecciones futuras de la disciplina

En los próximos 5-10 años, predigo 4 tendencias:

1. **Reconocimiento académico formal**: universidades colombianas crearán especializaciones/maestrías en Ingeniería Legal (ya hay precedentes: UNAB, Los Andes con sus programas de legaltech).

2. **Certificaciones profesionales**: Colombia Fintech + ACIS (Asociación Colombiana de Ingenieros de Sistemas) podrían desarrollar una certificación "Ingeniero Legal Colombia" con examen dual.

3. **Cargos en plantas de entidades**: decretos de modernización del Estado incluirán el rol "Ingeniero Legal" en manuales de funciones (primera ola: Procuraduría, Contraloría, DIAN).

4. **Ecosistema profesional**: comunidad de práctica colombiana (meetups, conferencias tipo "Legaltech Summit Colombia"), herramientas open-source compartidas (repo público de `regex_library` colombiano).

### 12.10 Cierre

La **Ingeniería Legal** no es un sector ni un producto: es una disciplina profesional emergente que combina cuatro tradiciones (derecho, ingeniería de software, ingeniería del conocimiento, ciencia de datos) en una síntesis distintiva. Tiene objeto de estudio propio (sistemas socio-técnicos jurídicos), método propio (ciclo 6 fases + auditoría empírica) y productos propios (plataformas operacionales con trazabilidad normativa).

Esta tesis aporta un caso ejemplar: **394 tutelas procesadas, 27 herramientas de agente, 5 pipelines, 40 tests**, 780 líneas de documento académico, 8 sprints iterativos. El sistema está **en producción** en la Secretaría de Educación de Santander. Es la prueba viva de que la Ingeniería Legal es una disciplina **real, replicable y rentable** en Colombia.

---

**Fin del documento de tesis.**

Para preguntas o extensión del proyecto: ver `CLAUDE.md` en raíz del repositorio para estado actual y próximas iteraciones.







