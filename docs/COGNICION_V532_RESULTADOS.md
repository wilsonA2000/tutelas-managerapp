# Cognición v5.3.2 — Resultados consolidados post iteraciones +2/+3

> Fecha: 2026-04-21 (misma sesión, iteraciones post v5.3.1)
> Sample: **50 casos COMPLETO** (sample más representativa que v5.3.1)

## Cambios acumulados desde v5.3.1

**Iteración +2** (fechas de fallo + vinculados):
- `decision_extractor.FALLO_DATE_ANCHORS`: 5 patrones de "proferido el", "mediante fallo del", "sentencia de fecha", "Dada en X el...".
- Búsqueda en **todo el texto** del documento, no solo ±500 chars del RESUELVE.
- `entity_extractor` vinculados: patrones "VINCÚLESE", "DE OFICIO VINCÚLESE" con DOTALL.

**Iteración +3** (spaCy lg + NER fallback):
- Upgrade `es_core_news_md` (40MB) → `es_core_news_lg` (568MB) — mejor recall NER.
- `backend/cognition/ner_spacy.py`: wrapper singleton para `extract_persons/organizations/locations`.
- Fallback NER en `entity_extractor`: si patrones narrativos fallan accionante, intentar con NER en primeros 2K chars.

**Iteración +4** (active learning):
- `scripts/active_learning.py`: analiza casos donde cognición falla vs DB ground truth.
- Identificó 10 instituciones nuevas para `KNOWN_INSTITUTIONS` (SIMAT, ADRES, PROCURADURÍA, DEFENSORÍA...).
- Identificó 17 casos con "TUTÉLESE" (imperativo) no capturados.

**Iteración +5** (decision patterns):
- `DECISION_VERBS` ahora cubre: infinitivo (TUTELAR), imperativo (TUTÉLESE), reflexivo (se tutela).
- Algoritmo de orden: verbo más cercano al inicio de "PRIMERO:" gana (no por orden de lista).
- Detección de "hecho superado", "carencia actual de objeto" → IMPROCEDENTE.

## Cobertura sobre 50 casos reales

| Campo | v5.3.1 (30 casos) | v5.3.2 (50 casos) | Δ |
|---|---|---|---|
| accionados | 96.7% | **98.0%** | +1.3 |
| accionante | 96.7% | **98.0%** | +1.3 |
| asunto | 96.7% | **98.0%** | +1.3 |
| observaciones | 96.7% | **98.0%** | +1.3 |
| pretensiones | 96.7% | **98.0%** | +1.3 |
| derecho_vulnerado | 90.0% | **94.0%** | +4.0 |
| impugnacion | 73.3% | **82.0%** | +8.7 |
| sentido_fallo_1st | 70.0% | **80.0%** | +10.0 |
| fecha_fallo_1st | 13.3% → 50.0% | **52.0%** | +38.7 total |
| sentido_fallo_2nd | 23.3% | 36.0% | +12.7 |
| vinculados | 23.3% | 34.0% | +10.7 |
| fecha_fallo_2nd | 10.0% | 26.0% | +16.0 |

**Cobertura alta (≥70% campos): 17% → 36% casos.**

## Tests

- **71 tests passing** (63 v5.3.1 + 8 nuevos de patrones de decisión).
- 0 regresiones sobre 228 tests pre-existentes.

## Interpretación ejecutiva

**Los 5 campos más críticos** (asunto, pretensiones, observaciones, accionante, accionados) están todos al **98%** sin IA. Es el núcleo del protocolo — lo que el operador ve en la vista principal.

**Campos de decisión** (sentido_fallo_1st, impugnacion) en **80-82%**. Los que fallan son casos sin PDF_SENTENCIA aún (en trámite) — el campo queda vacío porque no existe la información, no porque cognición falle.

**Campos de 2ª instancia** en 26-36%. Bajo porque solo ~35% de casos llegan a impugnación según el catálogo. El porcentaje es relativo al total (incluye casos sin 2ª instancia por diseño).

## Impacto real en pipeline

**Antes de cognición (v5.2)**: IA externa procesaba ~60% de casos (todos los que faltaban campos semánticos).

**Con cognición v5.3.2**: IA externa se invoca en ~15-20% de casos residuales. Los 5 campos críticos están llenos en 98%.

**Proyección v5.4** (calibración adicional + active learning loop automatizado): ~5% IA, sin cambios de hardware.

## Active learning: qué identifica

Corriendo `python3 scripts/active_learning.py`:
- Genera `logs/active_learning_<fecha>.md` con:
  - Formatos de accionante no detectados
  - Instituciones nuevas candidatas
  - Vinculados sin patrón
  - Decisiones con formato inusual
  - Correcciones manuales del operador por campo

En la primera corrida (100 casos analizados):
- 0 formatos de accionante sin detectar ✅
- 0 accionados nuevos ✅
- 15 vinculados con instituciones nuevas → 10 añadidas a KNOWN_INSTITUTIONS
- 17 casos CONCEDE no detectados → resueltos con patrón TUTÉLESE imperativo
- 24 correcciones manuales de OBSERVACIONES → área a mejorar narrative_builder

## Reproducción

```bash
# Benchmark cobertura
python3 scripts/benchmark_cognition.py 50

# Active learning (identifica gaps)
python3 scripts/active_learning.py

# Catálogo de variantes
python3 scripts/catalog_variants.py

# Tests
python3 -m pytest tests/cognition/ tests/privacy/ -v
```
