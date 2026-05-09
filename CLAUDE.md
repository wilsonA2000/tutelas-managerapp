# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

> Existe un CLAUDE.md padre en `../CLAUDE.md` con historial v3-v6 e instrucciones institucionales. Este documento cubre **el estado actual (v8.2) y los aspectos no derivables del código**. Léelos juntos.

## Versión actual

**v8.3 — Datos limpios para presentación + LoRA off** (mayo 2026). El README.md tiene métricas vivas. Branch principal de trabajo: `experiment-v5.5` (a pesar del nombre, contiene v8.x).

### Cambios v8.3 (sesión 2026-05-07/08)

- **Cleanup total**: 220 cases con `field_confidences_json`, 178/220 con `abogado_canonical`, 121/220 con `dependencia_canonical`, 4141 actuaciones del Excel CONTROL TUTELAS importadas, 81 archivos huérfanos reubicados.
- **Bug R6 fix**: extractor de `fecha_ingreso` (`backend/agent/extractors/registry.py`) ya no lee de doc_types `GMAIL/EMAIL_MD/INCIDENTE`. Antes leía fechas de emails recientes como fecha de admisión → 65 cases corregidos (R6 findings: 129 → 60).
- **LoRA iuris OFF por default**: A/B test mostró que el LoRA actual baja extracción 50% → 25%. Flag `LLM_LORA_ENABLED=false` en `.env`. `backend/services/llm_mutex.py` ahora omite `--lora` salvo que `LLM_LORA_ENABLED=true`.
- **`/no_think` obligatorio en prompts a Qwen3 base**: sin él gasta todos los tokens en `<think>` tags y devuelve content vacío. Agregado al `PROMPT_MULTI_FIELD` en `focused_field_extractors.py`.
- **Reglas F11/F12 en post_validator**: F11 limpia `sentido_fallo_2nd/juzgado_2nd/fecha_fallo_2nd` cuando `impugnacion=NO` (12 cases). F12 limpia `juzgado_2nd` cuando == `juzgado` (31 cases). F13 solo emite warning, no auto-corrige (causa raíz suele ser otra fecha mal extraída).
- **Auditor automatizado** `scripts/audit_cases.py` con 12 reglas jurídicas + 21 tests.
- **Cuadro con bandas** OK/REVISAR/BAJO + filtro "Solo findings". Endpoint `GET /api/cases/export-audit` con XLSX de 4 hojas.
- **Pipeline funnel + plazos cumplimiento** en `/ejecutivo`.

### v8.3 datos al cierre de sesión

| Métrica | Valor |
|---|---|
| Total findings | 302 (vs 373 inicial) |
| Cases con findings | 159 / 220 |
| R6 fechas inconsistentes | 60 (vs 129) |
| Tests verdes (módulos nuevos) | 47/47 |

## Comandos esenciales

### Arranque
```bash
bash start.sh                 # backend :8000 + frontend :5173 (mata procesos previos en esos puertos)
```
Login UI: `wilson / tutelas2026`.

### Backend
```bash
# Tests — pytest está en tests/pytest.ini (testpaths=tests)
python3 -m pytest tests/ -v
python3 -m pytest tests/test_timeline_classifier_v6.py tests/cognition/ -v   # cognitive v6
python3 -m pytest tests/test_<archivo>.py::test_<func> -v                    # single test

# Migraciones (alembic.ini en raíz)
alembic upgrade head

# Smoke local (no toca producción)
python3 scripts/smoke_test_pod.py

# Re-OCR / re-verify operacionales
python3 scripts/reocr_pending.py
python3 scripts/reverify_sospechosos.py
python3 scripts/reconcile_by_accionante.py
```

### Frontend (carpeta `frontend/`)
```bash
npm install                   # primera vez
npm run dev                   # vite (puerto 5173)
npm run build                 # tsc -b && vite build
npm run lint                  # eslint .
node ../scripts/e2e_<x>.mjs   # E2E Playwright (requiere frontend levantado)
```

### LLM local opcional (Qwen3-4B + LoRA iuris)
```bash
~/llama.cpp/build/bin/llama-server \
  -m data/lora-models/Qwen3-4B-Q4_K_M.gguf \
  --lora data/lora-models/iuris-lora-qwen3-4b.gguf \
  --port 8765 --ctx-size 4096 -t 6 --host 127.0.0.1
```
Sin LLM, el chat funciona con Tier 1 (templates determinísticos).

## Arquitectura — el "big picture"

### Pipeline cognitivo de 7 capas (v6.0+)
Activado por `USE_COGNITIVE_PIPELINE=true` en `.env`. Entry-point: `backend/extraction/unified_cognitive.py::unified_extract_dispatch`. Cada capa vive en `backend/cognition/`:

0. **Visual** — `pdf_visual_analyzer.VisualSignature` (sello/firma/maquetación). Persiste a `documents.visual_signature_json` y `institutional_score`.
1. **Tipología** — `case_classifier` + contradicciones filename↔contenido.
2. **Identificadores canónicos** — `canonical_identifiers.harvest_identifiers` (rad23, rad_corto, FOREST, cédula) con LR por zona del documento.
3. **Actor graph** — `actor_graph` (correferencia, litisconsorcio, dedup nombre normalizado).
4. **Timeline procesal** — `procedural_timeline` + `case_classifier` puebla `cases.origen` ∈ {TUTELA, INCIDENTE_HUERFANO, AMBIGUO} y `cases.estado_incidente`.
5. **Bayesian assignment** — `bayesian_assignment.infer_assignment` con priors + LRs calibrados; umbrales OK≥0.92, NO_PERTENECE≤0.08; expone `reasons_for/against` que la UI muestra textualmente.
6. **Live consolidator** — `live_consolidator.consolidate_case` dentro del pipeline (NO post-hoc); fusiona huérfano→padre y F9 duplicados con score≥0.85.
7. **Persist** — `cognitive_persist.persist_case` con entropy gate (umbral `COGNITIVE_ENTROPY_THRESHOLD=2.2`); contradicciones SIEMPRE fuerzan REVISION.

Hay un fallback a v5.5 legacy en `backend/extraction/unified.py` (6 fases) si el flag está apagado. **No mezclar capas entre pipelines** — cada uno tiene su propio contrato de IR.

### Capas v8.2 sobre el pipeline
- **Catálogos canónicos** — `backend/data/abogados_canonicos.json` (17 oficiales con aliases) y `backend/data/dependencias_resolver.py` (mapeo Excel ↔ SED_ORG L1/L2/L3). Resuelven typos antes de persistir.
- **Importador Excel** — `backend/services/control_tutelas_importer.py` reconcilia el cuadro `CONTROL TUTELAS.xlsx` con la DB y registra disensos. La bitácora va a `case_actuaciones` SIN sobrescribir extracción.
- **Auditoría** — `routers/auditoria_fallos.py` + página `/auditoria` con vistas por etapa procesal/abogado/dependencia.
- **EarlyWarning 10 reglas** — `backend/alerts/` agrega R8 (plazo cumplimiento), R9 (apercibimiento en sentencia), R10 (drift de asignación).
- **Chat híbrido** — `routers/chat.py` Tier 1 (≈18 templates determinísticos, <10ms) + Tier 2 (Qwen 4B local en `127.0.0.1:8765`).

### Ingesta Gmail (multi-criterio, no IMAP)
- `backend/email/gmail_monitor.py` corre cada 20 min (configurable). OAuth2 REST con `tutelas@santander.gov.co` — **NUNCA IMAP**.
- `email/matcher.py` puntúa 0-160 con 6 señales: thread+50, rad23+40, FOREST+25/15, CC+20, rad_corto+juzgado+15, nombre+10. Umbrales HIGH≥70 / MEDIUM 40-69 / LOW<40.
- `email/rad_utils.py` provee `normalize/canonicalize/reconcile/juzgado_code` y tiene 37 unit tests. Bug histórico: secuencia rad exige 5 dígitos exactos (`{5}`), no `{2,5}` (zfill bug producía duplicados 407/619).
- `email/case_lookup_cache.py` mantiene KB en memoria con 4 dicts para O(1) lookup.

### Smart Router IA
- `backend/agent/smart_router.py`. Primary: DeepSeek (~$0.28/1M). Fallback: Anthropic Haiku 4.5 (~$1/1M). En v6.1.1+ con `LLM_LOCAL_PRIMARY=true` el primary es Qwen3-4B local.
- **Solo 2 providers activos**. Gemini, OpenAI, Cerebras, Groq, HuggingFace fueron eliminados en v5.4 (cero llamadas en `token_usage`).
- Capa PII (`backend/privacy/`) anonimiza ANTES de salir a IA externa. Modos `selective` (solo numéricos) / `aggressive` (también nombres). `LOCAL_ONLY=true` skip-ea Presidio porque los datos no salen.

### Persistencia
- SQLite en `data/tutelas.db` (~150 MB). FK siempre ON, WAL checkpoint cada 5 min — ver `backend/database/database.py`.
- Path desacoplado: `BASE_DIR` controla raíz de carpetas de casos; `app_dir` (computado, fijo) controla DB y exports. Cambiar `BASE_DIR` no migra la DB.
- Modelos en `backend/database/models.py`. Tablas v8.2: `cases`, `documents`, `emails`, `case_actuaciones`, `corte_revision`, `directorio_correos`, `pii_mappings`, `token_usage`, `audit_log`.

### Frontend
- React 19 + Vite 8 + Tailwind 4 + shadcn 4 + base-ui + Motion. Páginas en `frontend/src/pages/`.
- API client centralizado en `frontend/src/services/api.ts`. Estado global vía `@tanstack/react-query`.
- Backups `.pre_v94.bak` en `pages/` deben ignorarse — son históricos no consumidos.

## Reglas críticas (no derivables del código)

1. **Inteligencia local primero** — 80% del trabajo se resuelve con regex + forensic; IA externa SOLO para razonamiento semántico que requiera lenguaje natural.
2. **Multi-criterio obligatorio** — nunca clasificar un doc por un solo regex. Ver `verify_document_belongs` (5 criterios).
3. **CIUDAD = municipio de afectación del derecho**, no la ciudad del juzgado.
4. **FOREST solo de emails de `tutelas@santander.gov.co`** — nunca inventarlo desde texto del documento.
5. **Carpetas siguen `<rad_corto> <ACCIONANTE>`** (ej. `2026-00095 PAOLA ANDREA GARCIA NUÑEZ`). El `folder_renamer` lo enforce-a.
6. **Backup antes de operaciones pesadas** — usar `auto_backup()` o backups nombrados en `backups/` antes de migraciones masivas.
7. **DrvFs + SQLite + ProcessPool** produce "disk I/O error" no determinístico en `/mnt/c/`. Workers tienen retry x3 + `busy_timeout=30s` (último commit).

## Feature flags clave (`.env`)

| Flag | Default | Activa |
|---|---|---|
| `USE_COGNITIVE_PIPELINE` | false | Pipeline v6 7-capas (vs v5.5 legacy 6-fases) |
| `USE_FIELD_CONFIDENCE` | false | Scoring por campo + bandas OK/REVISAR/BAJO (F2) |
| `LLM_LOCAL_PRIMARY` | false | Qwen 4B local como primary IA |
| `LOCAL_ONLY` | false | Modo airgapped: skip Presidio + skip route() externo |
| `USE_AI_EXTRACTION` | true | False = nunca llamar IA en extracción |
| `USE_REMOTE_EXTRACTION` | false | Delegar capas 0-5 a un pod RunPod GPU |
| `EXPERIMENT_MODE` | false | DB fresca + workspace paralelo (no toca prod) |
| `GMAIL_READ_ONLY` | false | No marcar emails leídos en Gmail |
| `PII_REDACTION_ENABLED` | true | Anonimización pre-IA externa |

`TUTELAS_ENV_FILE=/path/to/.env.experiment` permite cambiar el `.env` cargado sin tocar el de producción. Si existe `/workspace/tutelas-app/.env.pod`, se autocarga (RunPod).

## Mapa "necesito X → voy a Y"

| Necesito... | Voy a |
|---|---|
| Patterns regex Colombia (radicado, FOREST, cédula) | `backend/agent/regex_library.py` |
| Cognición forense sin IA (7 etapas) | `backend/services/forensic_analyzer.py` |
| Pipeline extracción legacy v5.5 | `backend/extraction/unified.py` |
| Pipeline cognitivo v6 (7 capas) | `backend/extraction/unified_cognitive.py` |
| Tools del agente IA | `backend/agent/tools/` |
| Post-validator con F4 (10 reglas) | `backend/extraction/post_validator.py` |
| Config DB (FK, WAL, pool) | `backend/database/database.py` |
| Matching Gmail→caso | `backend/email/gmail_monitor.py::match_to_case` |
| Reconciliación histórica | `backend/services/reconcile_db.py` |
| Importador Excel CONTROL TUTELAS | `backend/services/control_tutelas_importer.py` |
| KPIs ejecutivos | `backend/services/executive_kpis.py` |
| Chat NL→DB intents | `backend/routers/chat.py` |
| 10 reglas EarlyWarning | `backend/alerts/` |
| Catálogos canónicos | `backend/data/abogados_canonicos.json`, `backend/data/dependencias_resolver.py` |

## Tests críticos

```bash
# Cognitivo v6 completo
python3 -m pytest tests/cognition/ tests/test_*_v6.py tests/test_*_v62.py -v

# Forense + integridad legacy
python3 -m pytest tests/test_forensic_analyzer.py tests/test_audit_v50.py tests/test_integrity_v51.py -v

# Gmail matcher
python3 -m pytest tests/test_rad_utils.py tests/test_monitor_matcher.py -v

# E2E Playwright (frontend levantado)
cd frontend && node ../scripts/e2e_auditoria.mjs
node ../scripts/e2e_v6016_validation.mjs
```

## Documentación viva

| Doc | Para qué |
|---|---|
| `README.md` | Estado actual + arranque |
| `AGENTE_JURIDICO_IA.md` | Detalle del agente Qwen + tools |
| `GUIA_USUARIO.md` | Manual operativo del abogado |
| `BENCHMARK_PIPELINE_VS_AGENT.md` | Comparativa cuantitativa |
| `docs/V8_FIXES_SESSION.md` | Cambios v8 |
| `docs/TESIS_PROYECTO_AGENTE_JURIDICO.md` | Tesis 12 caps + protocolo 28 campos |
| `docs/iuris/` | LoRA training y dataset |
| `../CLAUDE.md` | Instrucciones del proyecto + historial v3-v6 |
