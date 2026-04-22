# Baseline v5.4 Cleanup — Estado PRE-limpieza

> Fecha captura: 2026-04-21 22:15
> Commit de referencia: `1d33dd0` (tag: `pre-v5.4-cleanup`)
> DB backup físico: `data/tutelas.db.pre_v54_20260421_221554.bak` (124M)

---

## Métricas de código

| Métrica | PRE (baseline) | Meta POST | Delta meta |
|---------|----------------|-----------|------------|
| **Backend LOC (Python)** | 26,378 | -15% | ~22,400 |
| **Frontend LOC (src)** | 8,796 | -15% | ~7,500 |
| **Frontend páginas** | 13 | auditar todas, -2 a -4 deprecated | 9-11 |
| **Frontend componentes** | 8 | auditar | ≥6 |
| **Backend routers** | 13 | consolidar | 10-12 |
| **Endpoints backend** | 110 | -20% o marcados DEPRECATED | ~88 |
| **Dependencias requirements.txt** | 36 | -30% (post drop providers) | ~25 |
| **Dependencias package.json** | 18 prod + 12 dev = 30 | -15% | ~25 |
| **Tests archivos** | 36 | consolidar (sin test_backend.py roto) | 34 |
| **Tests collected** | 108 (con errores collect) | 100% passing | 108+ |
| **Scripts operacionales** | 20 | archivar one-shot ejecutados | 8-12 |
| **Docs markdown** | 21 | archivar v3.x-v4.x | 10-14 |
| **DB size** | 124M | post-VACUUM | -5% |
| **Frontend bundle JS** | 1,230.75 kB (gzip 373.31 kB) | -10% | ~1,100 kB |
| **Frontend bundle CSS** | 101.23 kB (gzip 16.71 kB) | -5% | ~95 kB |
| **Frontend módulos** | 3,101 | -5% | ~2,950 |

---

## Dependencias IA — token_usage real (audit trail)

```
Provider      Model                                      Llamadas
────────────────────────────────────────────────────────────────
deepseek      deepseek-chat                                 307   ← ACTIVO (primary)
google        gemini-2.5-flash                              297   ← DEPRECADO v4.7 (histórico)
anthropic     claude-3-haiku-20240307                         2   ← MODELO OBSOLETO, migrar a Haiku 4.5
────────────────────────────────────────────────────────────────
                                                    TOTAL   606
```

**Hallazgos clave**:
- **0 llamadas**: Cerebras, Groq, HuggingFace, OpenAI → ELIMINAR sin impacto
- **Gemini**: 297 llamadas históricas pre-v4.7 → eliminar cliente, **preservar registros** en `token_usage`
- **Anthropic**: modelo registrado es `claude-3-haiku-20240307` (viejo, 2 llamadas). Plan dice usar `claude-haiku-4-5` (Haiku 4.5). Verificar smart_router y ai_extractor apuntan al modelo correcto.

---

## Providers en código (vs token_usage)

### `backend/agent/smart_router.py` (menciones)
```
anthropic     6
cerebras      5   ← ELIMINAR
deepseek     12
groq          3   ← ELIMINAR
huggingface   5   ← ELIMINAR
```

### `backend/extraction/ai_extractor.py` (PROVIDERS dict)
```
google (gemini-2.5-flash, gemini-2.5-pro)   ← ELIMINAR cliente, preservar BD histórica
deepseek (chat, reasoner, DeepSeek-R1)      ← MANTENER
cerebras                                     ← ELIMINAR
groq                                         ← ELIMINAR
anthropic                                    ← MANTENER (verificar modelo Haiku 4.5)
openai                                       ← ELIMINAR
```

**Inconsistencia detectada**: `huggingface` aparece en smart_router pero NO en `PROVIDERS` dict de ai_extractor. Revisar cableado real.

---

## Base de datos — tablas y conteos

```
Tabla                            Filas
──────────────────────────────────────
alembic_version                      1
alerts                             249   ← revisar si hay UI consumiendo
audit_log                        8,924   ← crecerá con v5.4; evaluar política de retención
cases                              378
compliance_tracking                188   ← revisar uso
corrections                         14   ← pocas filas, posible feature inactiva
documents                        4,493
emails                           1,493
extractions                      5,626
knowledge_entries                4,287
knowledge_fts + fts_*           ~16,000  ← índices FTS SQLite (no tocar)
pii_mappings                         0   ← v5.3 activado, aún sin uso real
privacy_stats                        0   ← idem
reasoning_logs                     140   ← revisar uso
sqlite_sequence                      0
token_usage                        606
users                                1
──────────────────────────────────────
```

**Candidatas a auditar en Fase 6 (DB)**:
- `alerts`, `compliance_tracking`, `corrections`, `reasoning_logs` → verificar si hay lecturas/escrituras activas en código
- `pii_mappings` y `privacy_stats` vacías → esperar primer uso real PII para decidir

---

## Distribución docs por versión

```
V3:  1    ← ARCHIVAR
V47: 1    ← ARCHIVAR
V48: 1    ← ARCHIVAR
V50: 5    ← ARCHIVAR (consolidado en AUDIT_V50_REPORT y CLAUDE_HISTORY)
V51: 1    ← ARCHIVAR
V52: 1 (y v52: 1)
V53: 1
V531: 1
V532: 1
V533: 1
V54: 1 (este documento + ROADMAP)
```

Estrategia: mover v3.x-v4.x a `docs/archive/`, mantener v5.x activos. CLAUDE_HISTORY_v3_to_v52.md es el consolidado.

---

## Tests — estado actual

- **108 collected** en 61s
- **Error crítico**: `tests/test_backend.py:346` ejecuta `sys.exit(1)` rompiendo el runner de pytest
- **test_e2e.py** presumiblemente tiene mismo issue (confirmar en Fase 1)
- Tests nuevos agregados v5.3.x: privacy (9 files) + cognition (2 files) + audit (3 files)

---

## Riesgos identificados

1. **Gemini con 297 llamadas**: eliminar cliente SIN borrar histórico token_usage (audit trail útil para forensics).
2. **Modelo anthropic en BD es `claude-3-haiku-20240307`**: verificar que código actual usa `claude-haiku-4-5`. Si no, hay deriva silenciosa.
3. **Provider huggingface fantasma**: código en smart_router sin contraparte en ai_extractor → puede indicar código muerto obvio, verificar primero si se invoca.
4. **108 tests collected pero test_backend.py rompe runner**: cobertura real puede ser menor. Fase 1 debe estabilizar suite antes de tocar otras fases.

---

## Rollback disponible

```bash
# Rollback a v5.3.3 consolidado
git reset --hard pre-v5.4-cleanup

# Restaurar DB si se corrompe
cp data/tutelas.db.pre_v54_20260421_221554.bak data/tutelas.db
```

---

## Preguntas para Wilson (antes de Fase 1)

1. `alerts`, `compliance_tracking`, `corrections`, `reasoning_logs` — ¿features activas o legacy? Si no sabes, las audito como parte de Fase 5 (endpoints + schemas).
2. Gemini 297 llamadas — ¿preservar registros token_usage para siempre o purgar pasado X fecha? Sugiero: preservar, solo eliminar cliente.
3. Modelo Anthropic activo en smart_router — ¿confirmas que es Haiku 4.5 (`claude-haiku-4-5-20251001`)? Si hay deriva, la corregimos en Fase 2.
4. ¿Quieres que construya el frontend (`npm run build`) ahora para tener baseline de bundle size, o lo diferimos a post-Fase 3?
