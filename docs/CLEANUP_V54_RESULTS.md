# Resultados v5.4 Cleanup — PRE vs POST

> Sesión: 2026-04-21
> Tag rollback: `pre-v5.4-cleanup` (commit `1d33dd0`)
> DB backup físico: `data/tutelas.db.pre_v54_20260421_221554.bak` (124M)

---

## Métricas comparativas

| Métrica | PRE | POST | Delta | % |
|---------|-----|------|-------|---|
| **Backend LOC** | 26,378 | 25,148 | -1,230 | **-4.7%** |
| **Frontend LOC** | 8,796 | 8,745 | -51 | -0.6% |
| **Endpoints backend** | ~110 | 97 | -13 | **-12%** |
| **Dependencias requirements.txt** | 36 | 34 | -2 | -5.6% |
| **Tests files** | 36 | 32 | -4 | -11% |
| **Tests collected** | 108 (con `sys.exit` bug) | 281 | +173 desenmascarados | +160% |
| **Docs activos** | 22 | 13 | -9 (archivados) | -41% |
| **Scripts (sin cambios fase 6)** | 20 | 20 | 0 | — |
| **Frontend páginas** | 13 | 13 | 0 | — |
| **Frontend componentes** | 8 | 8 | 0 | — |
| **`ai_extractor.py` LOC** | 1,080 | 534 | -546 | **-50.5%** |
| **Providers IA activos** | 7 | **2** (DeepSeek + Anthropic) | -5 | -71% |
| **Tests críticos passing** | 149 | **152** | +3 | ✅ |
| **Bundle JS** | 1,230 kB (gzip 373 kB) | 1,230 kB (gzip 373 kB) | 0 | (deps Python eliminadas no afectan bundle frontend) |

**Cambios netos**: +585 / **-3,016 LOC = -2,431 LOC netos**

---

## Fases ejecutadas

### ✅ Fase 1 (commit `d0f74bd`) — Docs legacy + tests obsoletos
- Archivados 9 docs en `docs/archive/{v4x, v5x_previous}/`
- Eliminados `tests/test_backend.py` + `tests/test_e2e.py` (606 LOC) que usaban `sys.exit` y bloqueaban pytest collection
- Fixes triviales TS: imports/vars sin uso (`AgentChat`, `Dashboard`, `CleanupPanel`)
- **Resultado clave**: pytest collect 60s → 8.5s, 108 → 303 tests visibles

### ✅ Fase 2 (commit `c01d8f8`) — Providers IA legacy
- `PROVIDERS` dict: 7 providers → 2 (DeepSeek + Anthropic)
- Funciones eliminadas: `_call_openai`, `_call_google`, `_call_huggingface`, `_call_cerebras`, `_call_groq`, `_extract_multimodal_google`, `_merge_ai_results`, `_run_single_provider`, `parallel_extract_with_ai`
- `ai_extractor.py`: 1,080 → 534 LOC (-50.5%)
- `smart_router.py`: ROUTING_CHAINS de 5 providers → 2
- Eliminadas env vars: `GOOGLE_API_KEY`, `OPENAI_API_KEY`, `GROQ_API_KEY`, `GROQ_MODEL`, `HF_TOKEN`, `CEREBRAS_API_KEY`, `PARALLEL_AI_EXTRACTION`
- Eliminados: `backend/extraction/pdf_splitter.py`, `tests/test_parallel_extraction.py`
- `requirements.txt`: removidas `groq` y `google-genai`
- Endpoint `/api/settings/status`: `groq` → `deepseek` (sincronizado UI)

### ✅ Fase 3 (commit `8d7ef03`) — Frontend api.ts
- 12 wrappers sin consumidor eliminados de `services/api.ts`
- Auditoría confirma: 13/13 páginas montadas, 8/8 componentes activos
- TypeScript strict (`noUnusedLocals: true`) ya cubre el 95% del código muerto frontend

### ✅ Fase 5 (commit `1dc68d3`) — Endpoints backend huérfanos
- Eliminado router completo `backend/routers/db.py` (6 endpoints + 96 LOC)
- Eliminado `tests/test_db_ops.py` (7 tests)
- Eliminados de `main.py`: `/api/ai/providers`, `/api/ai/provider`, `/api/tokens/metrics`
- Eliminados de `agent.py`: `/tokens`, `/tokens/budget`
- Eliminado de `cleanup.py`: `/audit` (duplicado de `/diagnosis`)
- Eliminado de `extraction.py`: `/docs/{id}/move-preview`

### ⏭ Fases pendientes (próxima sesión v5.5)
- **Fase 4 — WCAG accesibilidad**: contraste, focus visible, dark mode, aria labels (no destructivo, mejor con tiempo dedicado)
- **Fase 6 — Scripts archive + DB cleanup + logs**: mover scripts one-shot a `scripts/archive/`, VACUUM DB, retención `audit_log`, niveles log

---

## Hallazgos importantes

1. **`alerts/` sistema valioso conservado** — Wilson no sabía que existía pero detecta plazos venciendo, docs duplicados, anomalías. Fase 4/6 propuesta: hacer `NotificationCenter` más visible.
2. **Anthropic ya estaba al día** — código apuntaba a `claude-haiku-4-5-20251001` correctamente. Las 2 llamadas viejas en `token_usage` con `claude-3-haiku-20240307` son histórico pre-actualización (sin deriva real).
3. **`test_backend.py` con `sys.exit(1)`** ocultaba 173 tests. Ahora pytest ve toda la suite.
4. **0 referencias internas** a los 12 endpoints eliminados (verificado con grep en scripts/ y backend/ Python). Sin riesgo de cron/scheduler huérfano.
5. **`rebuild_service.py` (375 LOC)** conservado pese a router eliminado — feature completa solo le faltaba UI; valor latente alto.

---

## Comandos manuales recomendados (post-cleanup)

```bash
# Liberar disco + eliminar warning google.api_core
cd tutelas-app
pip uninstall -y google-genai groq

# Limpiar node_modules residuales (opcional)
cd frontend && npm prune
```

---

## Rollback disponible

```bash
git reset --hard pre-v5.4-cleanup        # vuelve a v5.3.3 consolidado
cp data/tutelas.db.pre_v54_20260421_221554.bak data/tutelas.db
```

---

## Audit trail intocado

- Tabla `token_usage` con 606 filas históricas (incluye 297 Gemini + 2 Haiku viejo) — preservada como evidencia forense.
- Tabla `audit_log` con 8,924 filas — preservada.
- DB backups físicos `.bak` excluidos de git pero presentes en `data/`.
