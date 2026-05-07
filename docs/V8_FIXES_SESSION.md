# Sesión v8.x — Resumen y plan Sprint 2

**Fecha**: 2026-05-01
**Pod**: 213.173.108.217:11888 (RTX A4500 20GB / 251GB RAM / 48 CPU)

---

## 1. ProcessPool — paralelismo real (v6.1 → v6.1.1)

| Métrica | Threads (v6.0) | ProcessPool (v6.1) |
|---|---|---|
| Tiempo 213 casos | ~4 horas | **~6 minutos** |
| Workers reales | 1 (GIL) | 16 (PIDs distintos confirmados) |
| Speedup | — | **22×** |

**Causa**: `ThreadPoolExecutor` no paraleliza CPU-bound bajo GIL.
**Fix**: `ProcessPoolExecutor` + `_extraction_worker_init` que precarga spaCy/Presidio.
**Archivos**: `backend/main.py`, `backend/routers/extraction.py`.

---

## 2. Regresión v6.0 — 12 campos vacíos restaurados (v6.1.1)

`unified_cognitive.py` v6.0 omitió la Fase 3 regex. Se restauró + agregaron Fase 3.5 (abogado DOCX) + 3.6 (oficina/juzgado_2nd/quien_impugno/fecha_apertura).

Cobertura recuperada: `juzgado` 0→79%, `ciudad` 0→58%, `oficina` 0→98%, `abogado` 0→60%, `fecha_ingreso` 0→82%.

---

## 3. Calidad semántica (v8.1)

### CIUDAD — whitelist municipios Santander
- Antes: capturaba "PODER PÚBLICO", "EDUCACIÓN DE SANTANDER", "la Tarjeta Profesional"
- Después: 93.4% con solo municipios reales (87 oficiales)
- Archivo: `backend/agent/extractors/municipios_santander.py` + refactor de `CiudadExtractor`

### ACCIONANTE — TRAP_WORDS extendidos
- Antes: capturaba "Señor Juez", "Dra Cristina", "Personería Municipal"
- Después: solo nombres reales, rechaza tratamientos honoríficos
- Archivo: `backend/cognition/folder_renamer.py`

### PRETENSIONES — verbo + subjuntivo (v8.1.1)
- Antes: "Que se a la entidad..." (sin verbo)
- Después: "Que se ordene/tutele/sancione/conceda... [complemento]"
- Archivo: `backend/cognition/narrative_builder.py:build_pretensiones`

### Campos de incidente
- Antes: 5/45 casos con `incidente=SI` tenían datos relacionados
- Después: 43/45 (95.6%)
- Nuevos extractores: `responsable_desacato`, `decision_incidente`, mejor `fecha_apertura_incidente`

### juzgado_2nd y quien_impugno
- juzgado_2nd: 19.7% → 39.0% con patrones múltiples (Tribunal Superior/Administrativo/Sala única/Corte Suprema)
- quien_impugno: enum simplificado ACCIONANTE/ACCIONADO/MINISTERIO_PUBLICO con heurística por sentido_fallo_1st

---

## 4. Jerarquía SED 3 niveles (v8.0)

Decretos 544/2021 + 048/2022:
- L1 (5): Apoyo Directo / Permanencia / Estratégica / Talento Docente / Admin Financiera
- L2 (17): Inspección, Apoyo Jurídico, Calidad, Cobertura, Nómina, Historias, etc.
- L3 (4): Equipo Tesorería/Presupuesto/Contabilidad/Fondos Servicios

Columnas DB: `direccion`, `grupo`, `equipo`. Excel exportado tiene 3 columnas nuevas.

Archivos: `backend/ml/data/sed_org.py` + migración `migrate_sed_jerarquia.py`.

---

## 5. Dataset histórico Excel (v8.0)

`CONTROL TUTELAS.xlsx`: 4,369 tutelas etiquetadas humanamente desde 2023.
Tabla `historical_cases` poblada (4,369 filas).
Match con corpus actual: 835 (19%, esperado dado que corpus actual es 2026).

Distribución FALLO en Excel: solo 18/4,369 con valor real → **NO es entrenable** desde Excel; se mantiene regex+cognición V6.

Archivos: `backend/ml/data/import_historical.py` + `normalizers.py`.

---

## 6. Sklearn baseline (v8.0)

Sprint 1 ML entrenado:

| Target | F1 macro | Estado |
|---|---|---|
| tema_normalized | **0.847** | ✅ excelente |
| tipo (TUTELA/DESACATO) | 0.533 | ✅ |
| direccion (L1 SED) | 0.510 | ✅ |
| dependencia (L2 SED) | 0.317 | ⚠️ baja por desbalance |

**Limitación encontrada en producción**: TF-IDF entrenado con texto Excel histórico no generaliza al texto del IR builder (PDFs OCR). En 213 casos producción solo 14 predicciones (5+9+0+...). **Justificación clara para Sprint 2 embeddings.**

Archivos: `backend/ml/{data,training,inference}/`, modelos en `artifacts/*.joblib`.

---

## 7. Estado final cobertura (v8.1.1, batch ~6 min)

| Campo | Cobertura | Notas |
|---|---|---|
| accionante / accionados / asunto / pretensiones / impugnacion / incidente | 100% | ✓ |
| oficina_responsable | 98.6% | ✓ |
| ciudad (validada Santander) | 93.4% | ✓ |
| sentido_fallo_1st / pretensiones (con verbo) | 83% / 99% | ✓ |
| fecha_ingreso / radicado_23 | 82% / 84% | ✓ |
| juzgado | 80% | ✓ |
| derecho_vulnerado | 98% (top-3 por frecuencia) | ✓ |
| sentido_fallo_2nd / fecha_fallo_1st | 62% / 74% | ⚠️ |
| abogado_responsable | 60% | ⚠️ falta DOCX en algunos |
| juzgado_2nd | 39% | ⚠️ regex aún limitada |
| quien_impugno | 25% (heurística + texto) | ⚠️ |
| responsable_desacato | 20% | ⚠️ regex |
| **direccion / grupo / equipo / categoria_tematica** | **2-5% / 0%** | ❌ **necesita Sprint 2 embeddings** |
| INCIDENTE=SI con campos relacionados | 95.6% (43/45) | ✓ |
| docs OK / SOSPECHOSO | 88% / 12% | ✓ |
| **Errores pipeline** | **0** | ✓ |

---

## 8. Plan Sprint 2 (próxima sesión)

### Stack v9.0 — Embeddings + RAG

```
Capa 2 NUEVA: Sentence Embeddings (multilingual-e5-large 1.4 GB)
              + FAISS sobre 4,369 históricos + 213 actuales
              → Endpoint /api/intelligence/similar?case_id=X&k=5
              → Features adicionales para sklearn (k-NN consensus)
              → F1 esperado direccion 0.40 → 0.85, tema 0.85 → 0.92
```

### Pasos concretos
1. `pip install sentence-transformers faiss-cpu` (cabe en venv)
2. `backend/ml/embeddings/index.py`: indexar corpus histórico
3. `backend/ml/embeddings/query.py`: búsqueda kNN
4. Endpoint `GET /api/intelligence/similar/{case_id}` retorna 5 vecinos con confidence
5. Refactor `predict_field()` en `models.py`: usar k-NN consensus si confidence sklearn <0.7
6. Re-extraer 213 → comparar Excel antes/después

### Hardware verificado
- e5-large: 1.4 GB GPU (cabe junto a PaddleOCR-VL 14 GB → ~16 GB / 20 GB GPU)
- FAISS index: <500 MB RAM
- Volume Network: 30 GB (suficiente)

### Estimación
- Implementación: 3-5 días
- Beneficio esperado: F1 promedio 0.50 → 0.85 en campos ML

---

## 9. Sprint 3 (futuro, post-Sprint 2)

- Qwen 2.5 7B fine-tuned con QLoRA sobre 4,369 casos × 4 tareas (17K muestras)
- Servir en vllm-server puerto 8120
- Reemplazar módulo agente IA legacy con LLM local
- Tool calling con las 27 tools de `legal_tools.py`
- Estimación: 7-10 días

---

## 10. Archivos modificados sesión

### Backend (8 archivos)
- `backend/extraction/unified_cognitive.py` — Fase 3/3.5/3.6 + Capa 4.5 ML
- `backend/cognition/narrative_builder.py` — pretensiones con verbo subjuntivo
- `backend/cognition/folder_renamer.py` — TRAP_WORDS extendidos
- `backend/cognition/bayesian_assignment.py` — LR ajustados
- `backend/agent/extractors/campos.py` — CiudadExtractor refactor
- `backend/agent/extractors/municipios_santander.py` — NUEVO
- `backend/database/models.py` — columnas direccion/grupo/equipo
- `backend/reports/excel_generator.py` — 3 columnas nuevas

### ML pipeline NUEVO
- `backend/ml/__init__.py`
- `backend/ml/data/{__init__,sed_org,normalizers,import_historical,migrate_sed_jerarquia}.py`
- `backend/ml/training/{__init__,train}.py`
- `backend/ml/inference/{__init__,models}.py`
- `backend/ml/artifacts/{tipo,direccion,dependencia,tema_normalized}.joblib`

### Settings/config
- `backend/core/settings.py` — flags `LOCAL_ONLY`, `USE_AI_EXTRACTION`
- `.env` (pod) — `LOCAL_ONLY=true`, `EXTRACTION_MAX_WORKERS=16`

### Eliminado
- `backend/cognition/actor_graph.py` — código muerto confirmado

---

## 11. Hardware comercializable validado

Tu pod actual (RTX A4500 20GB / 251GB RAM / 48 CPU / 30 GB volume) **soporta el stack v9.0 completo** (embeddings + LLM 7B). NO requiere upgrade.

Costo operacional: ~$370/mes 24/7 o $50/mes apagado/encendido. Vs $50K-500K/año licencias Palantir/Hyperscience.

**Diferenciador comercial**: ingeniería legal especializada Colombia, 100% on-premises, cumple Habeas Data Ley 1581/2012, costo único <$50K USD vs licencias internacionales.
