# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Agente Juridico IA v5.2 - Forensic Analyzer + Cognición Mecánica (Sesion 20 abril noche 2026)

### Cambios v5.2 — Sprint 5+6 (limpieza disco + ingeniería inversa de cognición)

**Motivacion:** usuario preguntó "qué pasa con los residuales" (29 docs + 7 emails en DUPLICATE_MERGED + 32 file_paths) y reportó carpetas problemáticas en disco. Además pidió reducir dependencia de IA emulando análisis humano con código mecánico.

**Sprint 5 — Limpieza disco (2h):**
- Borradas 29 carpetas vacías + 3 `[PENDIENTE REVISION]` vacías
- `PARA TEST UI` borrada (archivos testing)
- `PENDIENTE DE UBICACION` (7 archivos) → caso 119 (2021-00047 ALCALDIA LA PAZ)
- `T-303-2024 DIEGO FRANCO` (2 archivos) → caso 413
- `T-142-2024 PLAYON` (12 archivos) → caso NUEVO 564 (2023-00021 PERSONERO PLAYON T-142/2024)
- `NO TUTELA LUIS FERNANDO` renombrada `_acciones_populares...` (no son tutelas)
- `2026-00000 [PENDIENTE IDENTIFICACION]` (4 archivos) → caso 253 HELVIA LUCIA CAMACHO
- `_emails_sin_clasificar` (44 archivos): 17 movidos a 10 casos existentes + 6 duplicados borrados + 3 reportes admin borrados + 6 casos nuevos creados (565-572: GILMA, ELVIRA, LEMOS+DIANA Caqueta, IVAN CAMILO, PAOLA ALCOCER, JORGE DUVAN, EDGAR DIAZ, ALIS YURLEDYS)
- Corrección crítica: caso 527 era DIANA LORENA RAMOS + MARIA VICTORIA LEMOS en Florencia-Caquetá (no Santander). Caso 567 consolidado con 527.

**Sprint 6 — Ingeniería inversa de cognición (2h):**

Propósito: emular mi análisis humano con código determinista para reducir dependencia IA.

Nuevos módulos:
- `backend/services/forensic_analyzer.py`: pipeline 7 etapas (extracción → clasificación contenido → entidades → identificadores → correlación → match DB → decisión). Soporta PDF/DOCX/DOC/MD/TXT/XLSX + footers DOCX + OCR imágenes. DOC legacy con cascada fitz→antiword→olefile.
- `backend/services/folder_correlator.py`: Etapa 5 (correlación de archivos). Detecta series `001_/002_/003_`, agrupa por accionante/CC, propone caso destino con confidence ALTA/MEDIA.

Nuevos patterns en `regex_library.py` (12→17):
- `CC_ACCIONANTE` — identificador MÁS confiable (antes no se usaba en matching)
- `TUTELA_ONLINE_NO` — sistema judicial (3645440, 3722226)
- `ACTA_REPARTO_NO`, `EXPEDIENTE_DISCIPLINARIO`, `NUIP_MENOR` (registro civil)

Patterns de metadata:
- `extract_md_metadata()` — lee subject, De, Fecha, Caso de emails .md
- `extract_docx_response_metadata()` — lee "Proyectó:", "FOREST N" de footers docx

Tools agente (+2, total 27):
- `analizar_forense_carpeta` (diagnostic) — pipeline completo sobre una carpeta
- `analizar_forense_documento` (diagnostic) — un solo archivo

Tests: `tests/test_forensic_analyzer.py` (16 casos) — 40/40 pasan (16 forensic + 15 audit_v50 + 9 integrity_v51).

**Documentos producidos:**
- `docs/INGENIERIA_INVERSA_COGNICION.md` — análisis del proceso mental + 4 gaps identificados en plataforma
- `docs/DIAGNOSTICO_POST_V50.md` — diagnóstico 3 preguntas usuario
- `docs/BENCHMARK_V50.md`, `docs/BENCHMARK_V51.md` — comparativas

**KPIs Sprint 5+6:**
- 355 carpetas en disco (antes 383), 0 vacías, 0 [PENDIENTE]
- 9 casos nuevos creados (id 564-572) en estado REVISION para seguimiento
- 574 casos totales (284 COMPLETO + 88 DUPLICATE_MERGED + 19 REVISION)
- Forensic analyzer probado sobre universe completo: soporta .pdf/.md/.docx/.doc/.xlsx
- Tools agente: 25→27, categorías: diagnostic (5), cleanup (4), search (5), management (6), analysis (5), extraction (2)

**Diagnóstico de los 4 gaps en la plataforma (vs cognición humana):**
1. Clasificaba por nombre de archivo, no por contenido → `classify_by_content()` nuevo
2. No correlacionaba archivos de misma carpeta (001/002/003 son serie) → `folder_correlator.py`
3. No usaba CC como identificador (el más confiable) → agregado en matching y regex
4. No extraía "Tutela en línea N°" (identificador específico judicial) → patron `TUTELA_ONLINE_NO`

**TODO proxima sesion:**
1. Integrar `forensic_analyzer` al pipeline principal (reemplazar `classify_doc_type` por `classify_by_content`)
2. Usar CC en `match_to_case()` de `gmail_monitor.py` (prioridad después de rad23)
3. Re-correr extracción IA sobre los 9 casos REVISION nuevos (565-572) para completar campos
4. Los 29 docs + 7 emails residuales en DUPLICATE_MERGED: decisión de diseño — dejar como tombstones o script manual

---

## Agente Juridico IA v5.1 - Anti-Descuadre + Tools Ampliadas (Sesion 20 abril tarde 2026)

### Cambios v5.1 — Sprint 1+2+3 (20 abril 2026 tarde)

**Motivacion:** usuario reporto "DB siempre descuadrada" tras v5.0. Investigacion revelo que NO hay corrupcion — son 7 causas combinadas (WAL sin checkpoint por tiempo, staleTime React Query 30s, scripts CLI fuera del ORM, FK=OFF, 219+30+185 inconsistencias historicas).

**Sprint 1 (DB descuadre, 2h):**
- `backend/database/database.py`: `pool_size=5→1` single-user, `foreign_keys=ON` garantizado en cada connect, `synchronous=NORMAL`, `busy_timeout=10000`. Nueva funcion `wal_checkpoint(mode)`.
- `backend/main.py`: scheduler WAL checkpoint cada 5 min (thread daemon)
- `frontend/src/main.tsx`: `staleTime: 30_000→5_000` ms
- `backend/services/reconcile_db.py` (nuevo): mueve docs/emails de DUPLICATE_MERGED a canonicos + sincroniza file_paths
- `backend/routers/cleanup.py`: endpoints nuevos `POST /cleanup/reconcile` + `POST /cleanup/wal-checkpoint`
- `tests/test_integrity_v51.py`: 9 tests (FK ON, WAL, no orphans, no docs/emails en DUPLICATE_MERGED)

**Resultado Sprint 1:** 135 docs + 17 emails reubicados, 233 file_paths sincronizados. 24/24 tests integridad OK.

**Sprint 2 (mejoras, 1h):**
- `scripts/reocr_pending.py`: re-OCR para 83 docs PENDIENTE_OCR via PaddleOCR local (no API). Tambien como tool `re_ocr_pending`.
- `scripts/reverify_sospechosos.py`: re-corre verify_document_belongs con datos v5.0 actualizados. Tambien como tool `resolver_sospechosos`.

**Sprint 3 (7 tools nuevas agente IA, 1.5h):**
- `diagnosticar_salud` (diagnostic): consume `/api/cleanup/health-v50`
- `detectar_duplicados` (diagnostic): lista pares con mismo rad23+juzgado (22 pares reales detectados, mas precisos que los 51 sin filtro de juzgado)
- `verificar_rad23_integrity` (diagnostic): valida rad_corto(folder) vs rad23 oficial
- `reconciliar_db` (cleanup): llama reconcile_db service
- `re_ocr_pending` (cleanup): re-OCR pendientes en batch
- `resolver_sospechosos` (cleanup): re-verify con datos v5.0
- `consolidar_duplicados` (cleanup): merge 2 casos con confirmacion
- `estadisticas_generales` actualizada: ahora incluye `casos_por_status`, `salud_v50`, `docs_por_verificacion`

**Total tools agente: 16 → 25** (7 nuevas + 2 categorias nuevas: `diagnostic`, `cleanup`)

**Archivos nuevos:**
- `backend/services/reconcile_db.py`
- `scripts/reocr_pending.py`
- `scripts/reverify_sospechosos.py`
- `tests/test_integrity_v51.py`
- `docs/DIAGNOSTICO_POST_V50.md` (3 preguntas del usuario + hoja de ruta)
- `docs/BENCHMARK_V50.md` (comparativa v4.9 vs v5.0)

**KPIs post Sprint 1-3:**
- Docs en DUPLICATE_MERGED: 219 → 84 (los 84 restantes son casos viejos sin canonico identificable)
- Emails en DUPLICATE_MERGED: 30 → 13
- file_paths desalineados: 185 → 32
- Docs SOSPECHOSO: 211 → 210 (re-verify encontro 1 adicional)
- Docs REVISAR: 47 → 44 (3 pasaron a OK)
- Docs OK: 3474 → 3478
- Tools agente: 16 → 25

**TODO proxima sesion:**
1. Ejecutar `scripts/reocr_pending.py` en batch completo (83 docs × ~30s = ~40 min)
2. Revisar manualmente los 22 pares duplicados detectados por `detectar_duplicados` y consolidar con `consolidar_duplicados`
3. Los 84 docs + 13 emails "sin canonico" requieren revision humana (merges viejos sin trace)

---

## Agente Juridico IA v5.0 - Audit + Anti-Contaminacion (Sesion 20 abril 2026)

### Cambios v5.0 — Auditoria integral + 9 fixes criticos (20 abril 2026)

**Problema raiz descubierto:** email "RV: URGENTE!!! 2026-00057" termino en carpeta "2026-66132 [PENDIENTE REVISION]" porque el regex `RAD_LABEL` matcheaba "numero de radicado 20260066132" (FOREST 11d) como radicado judicial corto 2026-66132. Bug B1 sistemico: afectaba 22% de casos (85 candidatos, 33 reales tras filtrar forest-like legitimos).

**9 Fixes aplicados con 15 tests pasando (0 regresiones):**
- **F1** `agent/regex_library.py` — RAD_LABEL/RAD_GENERIC exigen separador guion + negative lookahead anti-FOREST
- **F2** `email/gmail_monitor.py` — `extract_radicado` prioriza rad_corto derivado del rad23 sobre labels
- **F3** `extraction/ai_extractor.py` — nuevo `_build_anti_contamination_block(folder, radicado_oficial)` inyecta RADICADO OFICIAL al prompt cuando existe
- **F4** `extraction/post_validator.py` — regla 8: detecta radicados ajenos en obs/asunto/pretensiones, elimina oraciones "Caso 20YY-NNNNN" contaminadas (tolera acumuladas)
- **F5** `extraction/pipeline.py` — `_rename_folder_if_needed` usa rad_corto(rad23) como fuente de verdad, fuerza rename si folder difiere
- **F6** `email/gmail_monitor.py` — `_split_forwarded_blocks` + STOP_TOKENS detectan accionante en niveles profundos del forwarded chain
- **F7** `email/gmail_monitor.py` — `match_to_case` rechaza match por rad_corto cuando digitos 6-12 del rad23 (juzgado) difieren
- **F8** `extraction/unified.py` — pre-COMPLETO exige rad23 ≥18d o (folder nombrado + accionante); si no, REVISION
- **F9** `extraction/unified.py` — detecta duplicados por rad23/rad_corto+juzgado, registra en `stats["potential_duplicate_of"]`

**Remediacion historica aplicada:**
- R1: caso 560 renombrado `2026-66132 [PENDIENTE REVISION]` → `2026-00057 LIBIA INES PATIÑO ROMÁN`; caso 541 consolidado con 531 (DUPLICATE_MERGED)
- R2: 6 casos con obs contaminadas limpiadas via F4 (478, 489, 491, 495, 541, 560)
- R3: 29 folders renombrados + 4 merges auto (529→519, 542→504, 550→193, 556→504)
- R4: 3 rad23 extraidos por regex desde docs (272, 531, 554); 15 casos marcados REVISION
- R5: 69 docs reclasificados SOSPECHOSO → ANEXO_SOPORTE por keyword administrativa

**Criterios de exito cumplidos:**
- Folders `[PENDIENTE REVISION]` activos: **0** (antes 2)
- COMPLETO sin rad23: **0** (antes 18)
- Folders disonantes rad_corto(folder) vs rad23: **0** (antes 33 reales)
- Tests regresion: **15/15** + **110/110** suite completa
- Docs SOSPECHOSO: 269 → 211 (-22%, pendiente reduccion <30 en proxima iteracion)

**Bug B13 nuevo identificado (no en plan original):** duplicacion no reconsolidada. El matcher crea casos nuevos cuando B1+B7 impiden match a canonico existente. En R1/R3 se detectaron y consolidaron 5 pares (529/519, 542/504, 550/193, 556/504, 541/531).

**Archivos generados:**
- `tutelas-app/docs/AUDIT_V50_SAMPLES.csv` + `.md` (25 casos muestreo)
- `tutelas-app/docs/AUDIT_V50_FINDINGS.md` (matriz prevalencia + queries agregadas)
- `tutelas-app/docs/AUDIT_V50_REPORT.md` (reporte antes/despues)
- `tutelas-app/tests/test_audit_v50.py` (15 tests regresion B1-B13)
- `data/tutelas_preaudit_v50_20260420_193555.db` (backup pre-audit, SHA256 verificado)
- `backend_preaudit_v50_20260420_193557/` (snapshot codigo)

**Estado final:** 385 casos (288 COMPLETO, 82 DUPLICATE_MERGED, 15 REVISION), 4,434 docs (3,474 OK + 120 ANEXO_SOPORTE + 211 SOSPECHOSO + ...). Caso raiz 560 (LIBIA INES PATIÑO ROMÁN) completamente corregido.

**Fase 4 UX — completada:**
- U1 tooltips en botones Auditoria/Sincronizar/Clasificar (Extraction.tsx) con hint de accion
- U3 modal warning al activar Clasificar (avisa que mueve archivos fisicos)
- U4 modal warning al ejecutar Auditoria (explica 4 subacciones que ejecuta)
- U5 panel "Salud de Datos" en CleanupPanel.tsx con 6 KPIs post-audit + top sospechosos + duplicados detectables
- Endpoint nuevo `GET /api/cleanup/health-v50` retorna summary con targets, folders_bugged, obs_contaminated, duplicate_pairs, top_sospechosos

**TODO proxima sesion:**
1. R5 complemento: reducir 211 SOSPECHOSO residuales <30 con analisis caso-a-caso (no solo heuristica keywords)
2. Re-ejecutar pipeline IA sobre los 15 casos REVISION para recuperar campos (si hay docs con info)
3. Monitoreo: verificar que nuevos emails no reintroducen B1 (F1/F2 en produccion)
4. Limpieza warnings TS6133 preexistentes (Dashboard imports unused) y `reextCandidates` en CleanupPanel

---

## Agente Juridico IA v4.9 - Tutelas Manager (Sesion 10 abril 2026)

### Cambios v4.9 — Cleanup Total + UX (10 abril 2026)

**Cleanup documentos (11 criterios de matching, 0 IA):**
- 100% clasificados: 3,896 OK + 129 ANEXO_SOPORTE = 4,025/4,025
- SOSPECHOSO 112→0, NO_PERTENECE 80→0, PENDIENTE_OCR 9→0, SIN_TEXTO 6→0
- 11 criterios: radicado 23d, radicado corto, accionante, juzgado, accionados, FOREST, content hash, filename sibling, doc generico, doc judicial, multi-juzgado
- Casos: REVISION 22→2, DUPLICATE_MERGED 24→30

**OCR ligero en document_normalizer.py:**
- `_ocr_pdf_page_by_page()`: fitz render → PaddleOCR, DPI 72, secuencial con gc.collect()
- Auto-lightweight: PDFs >8MB fuerzan modo ligero automaticamente
- `normalize_pdf_lightweight()`: funcion publica para batch processing
- `normalize_document(lightweight=True)`: parametro para forzar modo ligero

**Extraccion campos local (+246 sin IA):**
- sentido_fallo 58%→88%, fecha_fallo 59%→98%, fecha_ingreso 69%→84%, radicado_23d 81%→86%
- Cobertura total campos: 89.1% solo con regex

**UX/UI para abogados no tecnicos:**
- Tildes corregidas en 13 archivos (Extracción, Configuración, Contraseña, etc.)
- Traducido: "Dashboard"→"Panel Principal", "Analytics"→"Estadísticas", "Preview"→"Vista Previa"
- Leyenda fallos: "CONCEDE = Desfavorable | NIEGA = Favorable" + tooltips en badges
- Cuadro: texto 10px→12px legible
- CleanupPanel: labels humanizados ("Verificar Integridad", "Fusionar Casos Duplicados")
- Settings: eliminado stack tecnico y .env
- Nav reordenado: Seguimiento en posicion 4 (era 10)
- Extraction: "Pipeline"→"Estándar", "Agente IA"→"Avanzado"
- Emails: "Paquete inmutable"→"Documentos del correo"
- PENDIENTE: Dashboard graficas feas + seccion tokens IA visible (necesita debug visual con Playwright)

**Diagnostico visual con Playwright + correcciones UX (sesion 2):**
- Playwright MCP funcional: symlink /opt/google/chrome → chromium 141, distro Ubuntu-22.04
- ELIMINADA seccion "Opciones avanzadas de IA" del Dashboard (mostraba Gemini obsoleto)
- ELIMINADAS secciones "Gestion de Tokens" e "Info tecnica" de Agente IA (stack tecnico no para abogados)
- Configuracion: "Google Gemini" → "Inteligencia Artificial — DeepSeek V3.2 + Claude Haiku 3"
- Graficas Dashboard: sin CartesianGrid, sin flechas (radius=0), ejes minimalistas, altura 380px
- Extraccion: purple → azul institucional, campos humanizados ("RADICADO_23_DIGITOS" → "Radicado 23d")
- Seguimiento: "Sin plazo definido"→"Pendiente", "Extraer con IA"→"Obtener datos"
- Tutelas lista: radicado/accionante truncados, columnas Estado/Fallo visibles sin scroll
- Inteligencia Calendario: paginacion 10 items + boton "Ver todos"

**Tooling profesional frontend instalado:**
- shadcn/ui v4: 7 componentes (button, card, badge, table, tabs, tooltip, dialog)
- Motion v12 (animaciones React 19), Geist Variable (tipografia)
- class-variance-authority + clsx + tailwind-merge, cn() utility en src/lib/utils.ts
- Path alias @/* en tsconfig + vite.config.ts
- CSS variables oklch en index.css
- .mcp.json: shadcn MCP + Figma MCP (OAuth pendiente)
- Frontend Design Skill en .claude/skills/frontend-design.md

**Nuevos archivos:**
- `frontend/src/pages/CleanupPanel.tsx`: panel de limpieza con 4 acciones + diagnostico visual
- `frontend/src/lib/utils.ts`: cn() helper (clsx + tailwind-merge)
- `frontend/src/components/ui/`: button, card, badge, table, tabs, tooltip, dialog (shadcn/ui)
- `frontend/components.json`: configuracion shadcn/ui v4
- `.mcp.json`: shadcn + Figma MCP servers
- `.claude/skills/frontend-design.md`: skill estetico anti-slop

**Estado final:** 305 COMPLETO, 4,025 docs 100% clasificados, TypeScript sin errores, build OK

### Cambios v4.8 — Provenance + Cleanup (9-10 abril 2026)

**F0 Provenance (cambio arquitectonico):** la tabla `documents` ahora esta encadenada al correo de origen mediante `email_id` FK inmutable + `email_message_id`. Cada paquete (body.md + adjuntos) es una unidad atomica. Regla "hermanos viajan juntos": al mover un Document con email_id, TODOS sus hermanos del mismo paquete se mueven automaticamente. Garantia por diseño de que los PDFs de un correo no se pueden separar de su body.

- Migracion `backend/database/migrations/v48_add_email_provenance.py` (idempotente)
- Backfill retroactivo: 798 docs (19.96%) vinculados en 160s
- `backend/services/provenance_service.py`: get_siblings, get_package_by_email, list_packages_in_case
- `backend/services/sibling_mover.py`: move_document_or_package con rollback atomico
- `backend/email/gmail_monitor.py`: ingesta nueva crea Email ANTES de Documents (invertido) para propagar email_id

**F1 Cleanup Diagnosis:** reporte read-only con regla de identidad `(radicado_23d, accionante_norm, tipo_representacion)`. Detecta grupos auto-mergeables, fragmentos, typos de folder, docs sin hash, NO_PERTENECE.
- `backend/services/cleanup_diagnosis.py` + `scripts/diagnosis.py` CLI
- `GET /api/cleanup/diagnosis` y `.md`

**F2 Hash backfill:** 1,516 → 0 docs sin `file_hash` (100% cobertura MD5). 713 grupos de duplicados por contenido descubiertos.

**F3 Merge identidad:** 8 grupos auto-mergeables fusionados, 12 casos duplicados consolidados, 70 documents movidos a canonico (50 directos + 20 arrastrados por la regla de hermanos). Casos duplicados marcados `DUPLICATE_MERGED` (tombstones para rollback). Ejemplos: Ingrid Tatiana 46→70 docs, Nayibe Castaño 31→45 docs.

**F4 Emails .md backfill:** 28 emails .md generados + vinculados via email_id (los 349 existentes en disco se conservan).

**UI v4.8:**
- `Emails.tsx`: seccion "Paquete inmutable" en el detail con lista de documents vinculados
- `CaseDetail.tsx`: tabs Documentos / Correos con timeline cronologico de paquetes
- Nuevos endpoints: `GET /api/emails/{id}/package`, `GET /api/cases/{id}/email-packages`, `GET /api/extraction/docs/{id}/move-preview`, `POST /api/cleanup/hash-backfill`, `POST /api/cleanup/merge-identity`

**Tests v4.8:** `tests/test_provenance.py` con 10 casos (schema, siblings, package, preview, move atomico, legacy, idempotencia, relationship, timeline). Suite total: 52/52 verde, 0 regresiones.

**Estado final post-cleanup:**
- 337 casos (321 COMPLETO activos, 4 REVISION, 12 DUPLICATE_MERGED)
- 4,025 documents (100% con content_hash, 826 con email_id)
- 0 grupos auto-mergeables pendientes
- docs/BENCHMARK_V48.md documenta comparativa pre/post cleanup

### Cambios v4.7 (sesion 9 abril 2026 tarde)

Agente juridico IA local con **Extractor Unificado IR** (Intermediate Representation): 15 herramientas, 100+ endpoints, **pipeline sin Gemini** (v4.7), **IR Builder** (fitz + deteccion de zonas semanticas), **13 extractores regex** mejorados sobre zonas IR, **prompt compacto + Knowledge Base** (-82% tokens + contexto KB), normalizer 3 tiers (pdftext + PaddleOCR + Marker), **Smart Router con DeepSeek primary + Claude Haiku 3 fallback pagado**, retry exponencial con jitter, anti-contaminacion robusta, post-validator con interdependencia de campos, **Knowledge Base FTS5 integrada al pipeline de extraccion**, backup automatico, rebuild sandbox, **benchmark reusable via script CLI + endpoint HTTP**.

### Cambios v4.7 (sesion 9 abril 2026 tarde)
- **Eliminado Gemini multimodal**: auditoria revelo que consumia 17x mas tokens que DeepSeek, tocaba solo ~9 de 28 campos, y 97% de los PDFs son nativos (no requieren multimodal). Ver `docs/BENCHMARK_V47.md`
- **Claude Haiku 3** agregado como fallback pagado (`claude-3-haiku-20240307`, $0.25/$1.25 per MTok, 8x mas barato que Haiku 4.5). Presupuesto $5 cargado en Anthropic console
- **Smart Router v3**: DeepSeek V3.2 primary, Haiku 3 fallback en 6 routing chains (extraction, complex_reasoning, legal_analysis, general, multilingual, pdf_multimodal)
- **Nuevo `backend/reports/benchmark.py`**: logica pura para agregaciones de TokenUsage + Case, reusada por endpoint y script
- **Nuevo endpoint `GET /api/extraction/metrics/comparison`**: query params since/until/provider/version_tag, retorna JSON estructurado con cost, latency, coverage, errors, projection_1000_cases
- **Nuevo `scripts/benchmark_v47.py`**: CLI reusable con `--since --until --provider --version-tag --output {json|md|csv}`
- **Nuevo `docs/BENCHMARK_V47.md`**: reporte comparativo v4.6 vs v4.7 con tabla maestra (presupuestado/obtenido/proyeccion 1000 casos)
- **Bug fix**: `backend/extraction/ir_builder.py` `NameError: name 'filename' is not defined` (pre-existente, bloqueaba extraccion en algunos casos)
- **Feature flag `PARALLEL_AI_EXTRACTION`**: codigo inerte post-v4.7 (solo tenia sentido con Gemini+DeepSeek paralelos)
- **Benchmark real medido**:
  - Costo por caso: **$0.0015-$0.0025 USD** (vs ~$0.008 estimado v4.6)
  - Tiempo por caso: **44s avg, 39s p50** (vs 205s baseline lote 10 v4.6)
  - Proyeccion 1000 casos: **$1.49-$2.54 USD** y **~12.2h**
  - Rate limit events: **0** (vs frecuentes 503 UNAVAILABLE de Gemini en v4.6)

### Cambios v4.1-v4.6 (sesion 9 abril 2026 — 34 bugs corregidos en 5 fases)
- **v4.1:** Progreso unificado (progress_pct + elapsed_seconds en 3 procesos), Benchmark IR endpoint, fixes regex extractors (accionante, juzgado, ciudad, sentido_fallo), Email .md → Document table, anti-contaminacion adapter
- **v4.2:** Smart Router con fallback REAL (2do provider, no el mismo), retry exponencial+jitter (5s→60s cap, ConnectionError/Timeout retriable), Knowledge Base inyectada en prompt IA (top 5 entradas por caso)
- **v4.3:** Radicado 23d compara 17+ digitos (era 12), duplicados por contenido (trigram overlap >90%), FOREST confidence numerico 0-100 (era string), post-validator: rango fechas + interdependencia campos + abogado loggeado + English threshold 3
- **v4.4:** IR truncation con warning (DocumentZone.truncated), frontend polling deduplicado (hooks compartidos useProgressPolling)
- **v4.5:** Folder rename seguro (FileExistsError + sanitize_folder_name), PDF encriptado detectado, radicado ambiguo=REVISAR, DOCX footers completos (first_page + even_page), KB sync incremental
- **v4.6:** PDF tables validadas (max 5, min 20 chars), font detection via fitz flags, rate limit tracking (60s cooldown entre providers), KB index_case_incremental
- **Feature flags:** `UNIFIED_EXTRACTOR_ENABLED`, `KB_ENHANCED_EXTRACTION`
- **Estado:** 276 COMPLETO, 41 PENDIENTE, 4 REVISION (327 total). Lote 10: 10/10 OK en 34min

Documentacion completa del agente: `tutelas-app/AGENTE_JURIDICO_IA.md`

Plataforma web local en `tutelas-app/`. Memoria completa en `~/.claude/projects/.../memory/project_tutelas_platform.md`.
Login: wilson / tutelas2026

### Inicio rapido
```bash
cd "tutelas-app" && bash start.sh
# Frontend: http://localhost:5173 | Backend: http://localhost:8000 | Swagger: http://localhost:8000/docs
```

### Tests
```bash
cd "tutelas-app" && python3 -m pytest tests/ -v --tb=short
# 129 tests, 18 archivos, 0 dependencia de IA/Gmail, DB temporal en /tmp
```

### Reglas criticas de desarrollo
1. **Inteligencia local primero** — 80% del trabajo sin IA (regex, KB search, DB queries). IA solo para razonamiento
2. **Multi-criterio obligatorio** — NUNCA clasificar documentos por un solo regex. Usar arbol de decision ponderado
3. **Smart Router siempre activo** — Gemini para PDFs, Cerebras/Qwen3 para razonamiento, fallback automatico entre proveedores
4. **Gmail API REST** (OAuth2) — NUNCA usar IMAP (se bloquea)
5. **FOREST solo de emails** — NUNCA inventar, usar `backend/agent/forest_extractor.py` centralizado
6. **CIUDAD = municipio de afectacion** del derecho, NO ciudad del juzgado
7. **Context Engine** — Recopilar TODO el contexto antes de cualquier decision IA
8. **Validar post-IA:** fallos validos, fechas DD/MM/YYYY, cross-field, FOREST blacklist
9. **Carpetas = radicado abreviado + accionante** (ej: "2026-00095 PAOLA ANDREA GARCIA NUÑEZ")
10. **Aprendizaje** — Correcciones del usuario se almacenan como few-shot examples para proximas extracciones
11. **Backup antes de operaciones pesadas** — auto_backup() en sync, Gmail check, extraccion masiva

### Arquitectura del Agente (v4.6 - sesion 9 abril 2026)
- **Extractor Unificado IR:** Un motor para batch e individual. 6 fases: Ingestion → IR → Regex → IA(+KB) → Merge → Persistir
- **IR Builder (fitz/PyMuPDF):** Extrae bloques con fuentes/tamanos/posiciones. Detecta zonas semanticas. Truncation con warning (30K limit)
- **13 Extractores Regex mejorados:** radicados (2), fechas (4), juzgado (con cleanup), ciudad (con cleanup), accionante (trunca en Accionado/Contra), fallo (IMPROCEDENTE separado), impugnacion, incidente
- **Prompt Compacto + KB:** 455 tokens + contexto Knowledge Base (top 5 entradas). Solo 8 campos semanticos
- **Tool Registry:** 15 herramientas juridicas (buscar, analizar, predecir, extraer, validar, tokens)
- **Smart Router v2:** Fallback REAL (2do provider), validacion API key, rate limit tracking (60s cooldown), skip providers con 429
- **Retry v2:** Exponencial + jitter (5s→60s), ConnectionError/Timeout retriable, fallback automatico en ultimo intento
- **Document Normalizer:** 3 tiers — pdftext → Marker (opt-in) → pdfplumber + PaddleOCR. PDF encriptado detectado
- **Knowledge Base:** SQLite FTS5 integrada al pipeline de extraccion. Indexacion incremental post-sync. index_case_incremental()
- **Decision Engine:** resolve_field() por campo: regex vs IA, gana el de mayor confianza
- **Anti-Contaminacion:** Validacion radicado vs carpeta (regex estricto), SimpleNamespace adapter, limpieza cross-field
- **Post-Validator v2:** 10 validaciones: radicado, FOREST, fechas (rango+consistencia), fallo enum, interdependencia campos, abogado (con logging), English (threshold 3), radicado formato
- **FOREST v2:** Confidence numerico 0-100, +4 patrones, validacion digitos iguales, blacklist expandida
- **Verificacion Documental v2:** PDF encriptado=REVISAR, radicado ambiguo=REVISAR, radicado 17d, duplicados por contenido (trigram)
- **Folder Rename v2:** sanitize_folder_name (max 200 chars), FileExistsError handling, DOCX footers completos
- **Email .md → Document:** save_email_md registra como Document (doc_type=EMAIL_MD), retroactivo con /api/emails/register-md
- **Frontend:** Polling deduplicado con hooks compartidos (useProgressPolling), elapsed_seconds en tiempo real
- **Benchmark:** GET /api/extraction/benchmark — compara regex IR vs DB campo por campo
- **Agent Memory:** Aprende de correcciones del usuario como few-shot examples
- **Alertas Proactivas:** 122+ alertas detectadas (plazos, anomalias, emails sin caso)
- **Agent Runner:** Recibe instrucciones en lenguaje natural, planifica y ejecuta herramientas
- **Token Manager:** Cache, budget control, reporte de ahorro vs APIs de pago
- **Inteligencia Legal:** Favorabilidad por juzgado, predictor de resultados, calendario de plazos
- **Backup Automatico:** sqlite3 backup API, retencion 7, scheduler diario 6AM, auto pre-operaciones
- **Rebuild Sandbox:** Reconstruccion de DB desde carpetas en data/sandbox/ sin tocar original
- **Suite E2E:** 36+ tests passing, DB temporal, mocks IA/Gmail, 0 dependencias externas
- **7 Proveedores IA:** Google Gemini, Groq, Cerebras (Qwen3 235B), HF Router, DeepSeek, Anthropic, OpenAI

### Benchmark v4.6 vs v4.0 (9 abril 2026)
| Metrica | v4.0 | v4.6 | Mejora |
|---------|------|------|--------|
| Smart Router fallback | Roto (siempre None) | Real (2do provider) | Fix critico |
| Retry | Lineal 10s/20s/30s | Exponencial+jitter 5s→60s | -50% esperas |
| KB en extraccion | No consultada | Top 5 entradas inyectadas | +contexto |
| Radicado matching | 12 digitos sufijo | 17 digitos sufijo | +precision |
| FOREST confidence | String (ALTA/MEDIA) | Numerico 0-100 | +granularidad |
| Post-validaciones | 7 | 10 (+fechas, +interdep) | +robustez |
| English detection | 1 marcador | 3 marcadores | -falsos positivos |
| Duplicados | Solo hash MD5 | Hash + trigram >90% | +cobertura |
| IR truncation | Silencioso | Warning + flag | +transparencia |
| Rate limits | Sin tracking | 60s cooldown | -429 cascading |
| Folder rename | Race condition | FileExistsError + sanitize | +seguridad |

### Benchmark extraccion lotes (9 abril 2026)
| Lote | Casos | Exito | Tiempo | Promedio | Campos/caso |
|------|-------|-------|--------|----------|-------------|
| 5 | 5/5 | 100% | 692s (11:32) | 138s | 12.6 |
| 10 | 10/10 | 100% | 2049s (34:09) | 205s | 12.4 |

### Endpoints nuevos v4.1-v4.6
| Endpoint | Metodo | Descripcion |
|----------|--------|-------------|
| `/api/extraction/benchmark` | GET | Comparar regex IR vs DB campo por campo |
| `/api/emails/register-md` | POST | Registrar Email .md existentes como Documents |
| `/api/db/backup` | POST | Crear backup manual de la DB |
| `/api/db/backups` | GET | Listar backups disponibles |
| `/api/db/restore` | POST | Restaurar DB desde backup |
| `/api/db/rebuild` | POST | Reconstruir DB en sandbox desde carpetas (0 IA) |
| `/api/db/rebuild/status` | GET | Estado del rebuild en curso |
| `/api/db/sandbox/compare` | GET | Comparar sandbox vs DB principal |
| `/api/extraction/docs/{id}/suggest-target` | GET | Sugerir caso destino para doc NO_PERTENECE |

### Benchmark v3.3 (7 abril 2026)
| Caso | Docs | Bruto | Efectivo | Mejora |
|------|------|-------|----------|--------|
| Erika Paola (65) | 44 | 82% | 100% | +7% |
| Laura Chacon (93) | 42 | 71% | 80% | +67% |
| Paola Andrea (137) | 19 | 89% | 100% | +0% |
| Siprecol (76) | 28 | 79% | 110% | +8% |
| Blanca Aurora (73) | 94 | 64% | 90% | +0% |
| Ingrid Tatiana (95) | 41 | 82% | 92% | +0% |
| Dennis Meneses (80) | 94 | 86% | 96% | NEW |
| Juan Camilo (62) | 65 | 82% | 115% | NEW |
| Tania Vanessa (23) | 21 | 57% | 64% | NEW |

### TODO proxima sesion (post v4.9)
1. **Transformacion visual con frontend-design skill:** Aplicar shadcn/ui + Motion pagina por pagina. Migrar cards, tables, badges, dialogs existentes a componentes shadcn. Micro-animaciones en transiciones
2. **Figma MCP:** Autenticar OAuth, crear mockups para abogados, extraer tokens de diseno
3. **Generacion automatica de DOCX:** Templates para respuesta a tutela, impugnacion, desacato con auto-fill desde campos extraidos. Mayor valor operativo para el equipo juridico
4. **Dashboard en tiempo real:** WebSockets para actualizar KPIs y progreso sin polling
5. **RAG con jurisprudencia colombiana:** Indexar sentencias T-/SU- de la Corte Constitucional en Knowledge Base
6. **Dark mode:** Paleta oscura con CSS variables oklch ya preparadas en index.css
7. **Knowledge Graph:** Relaciones caso-juzgado-municipio-derecho para detectar patrones regionales

---

## Context

This is a legal document management workspace for **tutelas (acciones de tutela)** processed by the **Gobernación de Santander** in 2026. Contains both case folders/documents AND the `tutelas-app/` web platform that manages them.

## Repository Structure

- Each folder corresponds to one tutela case, named with the format `YYYY-NNNNN APELLIDO NOMBRE` (e.g., `2026-00095 PAOLA ANDREA GARCIA NUÑEZ`).
- Folder numbering is inconsistent: some use 5 digits (`2026-00095`), others use 4 (`2026-0014`) or 3 (`2026-097`), reflecting how they were registered.
- `COMPILADO_TUTELAS_2026.csv` — master spreadsheet with semicolons (`;`) as delimiter, containing all 28 data fields for each case (currently mostly empty — to be populated).
- `TUTELAS_PROCESADAS_20260220_2109.xlsx` — prior Excel export of processed cases.
- `GEMINI.md` — progress log from a prior AI session; lists folders already processed and the extraction protocol.
- `COMUNICACIONES/` — outgoing official communications (traslados por competencia, etc.).

## Document Types Inside Case Folders

Each case folder may contain:
- **PDF judicial documents** (numbered, e.g., `004AutoAvocaTutela.pdf`, `015SentenciaTutela.pdf`, `010SentenciaPrimeraInstancia.pdf`)
- **Email notifications** saved as PDF (always prefixed `Gmail - RV_ ...`)
- **Word response documents** (`.docx`) — the official response drafted by the Gobernación's lawyer. Typically named like `2026-95 FALLO TUTELA ... CON FOREST.docx` or `RESPUESTA FOREST.docx`
- **Screenshots** of the FOREST system (the internal case management software used to register incoming documents)

## Extraction Protocol (28 Fields)

The goal when processing each folder is to populate `COMPILADO_TUTELAS_2026.csv` with these fields (semicolons as delimiter):

| # | Field | Source |
|---|-------|--------|
| 1 | RADICADO_23_DIGITOS | Auto admisorio PDF — 23-digit judicial number |
| 2 | RADICADO_FOREST | `Gmail - RV_` PDFs or screenshots — ~11-digit internal number |
| 3 | ABOGADO_RESPONSABLE | End of `.docx` response — look for "Proyectó:", "Elaboró:", "Revisó:" |
| 4 | ACCIONANTE | Auto admisorio — person filing the tutela |
| 5 | ACCIONADOS | Auto admisorio — entities being sued |
| 6 | VINCULADOS | Auto admisorio — third parties called to the process |
| 7 | DERECHO_VULNERADO | Auto admisorio — fundamental rights invoked |
| 8 | JUZGADO | Auto admisorio — first-instance court |
| 9 | CIUDAD | Auto admisorio — city of the court |
| 10 | FECHA_INGRESO | Auto admisorio — date of admission |
| 11 | ASUNTO | Short summary of what is being demanded |
| 12 | PRETENSIONES | What the plaintiff is asking for |
| 13 | OFICINA_RESPONSABLE | Internal office that prepares the response |
| 14 | ESTADO | ACTIVO or INACTIVO |
| 15 | FECHA_RESPUESTA | Date of official response document |
| 16 | SENTIDO_FALLO_1ST | Sentence outcome: concede / niega / improcedente |
| 17 | FECHA_FALLO_1ST | Date of first-instance ruling |
| 18 | IMPUGNACION | SI or NO |
| 19 | QUIEN_IMPUGNO | Accionante / Accionado / Vinculado |
| 20 | FOREST_IMPUGNACION | FOREST number for the appeal |
| 21 | JUZGADO_2ND | Court or tribunal handling the appeal |
| 22 | SENTIDO_FALLO_2ND | Appeal outcome: Confirma / Revoca / Modifica |
| 23 | FECHA_FALLO_2ND | Date of second-instance ruling |
| 24 | INCIDENTE | SI or NO (desacato proceedings) |
| 25 | FECHA_APERTURA_INCIDENTE | Date the desacato was opened |
| 26 | RESPONSABLE_DESACATO | Lawyer who drafted the desacato response |
| 27 | DECISION_INCIDENTE | Judge's decision on the desacato |
| 28 | OBSERVACIONES | General summary and key notes |

## Reading DOCX Files

Word documents are binary. To extract text, use the "rename to .zip and read `word/document.xml`" technique:

```bash
cp "archivo.docx" "/tmp/archivo.zip"
unzip -p "/tmp/archivo.zip" "word/document.xml" | sed 's/<[^>]*>//g'
# For footers (lawyer name):
unzip -p "/tmp/archivo.zip" "word/footer1.xml" | sed 's/<[^>]*>//g'
```

## Key Conventions

- **Duplicate radicados** (e.g., multiple folders named `2026-00012`) are distinct cases from different municipalities. Verify by comparing digits 6–12 of the 23-digit judicial number, which encode the court's municipality.
- The 23-digit radicado format is: `AAAAMMDD-JJJJJJJ-NNNNNNN` (date + court code + sequence). Digits 6–12 identify the municipality.
- FOREST is the internal document management system of the Gobernación. The FOREST number (~11 digits) appears in `Gmail - RV_` email PDFs or in screenshots within the folder.
- Cases from years 2021–2025 with folders here are **impugnaciones or desacatos** still active in 2026, not new tutelas from those years.
