# Diagnóstico post v5.0: causas del "descuadre" + plan de mejoras + auditoría agente IA

**Fecha:** 2026-04-20
**Motivación:** usuario reporta que la DB "siempre está descuadrada o desfasada" + solicita auditoría del agente IA y plan para mejorar lo que no mejoró en v5.0

---

## Parte A — ¿Por qué la DB parece descuadrada?

### A.1 Respuesta corta

**La DB NO se corrompe.** `PRAGMA integrity_check` devuelve OK. **0 orphans** (documents/emails sin caso padre). **0 casos con folder_path inexistente en disco**. `SHA256` de los backups coincide.

El "descuadre" que percibes tiene **7 causas técnicas reales**, todas solucionables:

### A.2 Causas identificadas

#### 🔴 Causa 1 — SQLite WAL sin checkpoint por tiempo

```python
# backend/database/database.py:22-24
cursor.execute("PRAGMA journal_mode=WAL")
```

- **WAL activo:** cambios viven en `tutelas.db-wal` hasta que se haga checkpoint
- **autocheckpoint = 1000 páginas** (~4 MB), sin checkpoint por tiempo
- **Consecuencia:** si consultas la DB con otra herramienta (DB Browser, script CLI) mientras la app FastAPI está corriendo, **puedes ver datos anteriores** hasta que el WAL se checkpointee

#### 🔴 Causa 2 — React Query `staleTime: 30_000` global

```typescript
// frontend/src/main.tsx:14
staleTime: 30_000,   // 30 segundos
```

- Aunque el backend modifique un caso, React Query **no refetchea** la query por 30 segundos
- Si abres la UI justo después de un cambio, ves datos viejos hasta el próximo poll
- Algunas páginas tienen `refetchInterval` (Dashboard 10s, CasesList 2s, Cuadro no), pero **muchas no**

#### 🔴 Causa 3 — Scripts CLI bypasan el ORM

```python
# Scripts de R1-R5 usan
conn = sqlite3.connect('data/tutelas.db')
```

- No pasan por SQLAlchemy
- Si la app FastAPI tiene sesiones abiertas (`pool_size=5, pool_recycle=300`), esas sesiones tienen **identity_map en memoria**
- El identity_map cachea objetos ORM — cambios hechos directo a SQLite **no se reflejan** hasta que la sesión se cierre/recicle

#### 🟠 Causa 4 — FKs declaradas pero `foreign_keys=OFF`

```sql
PRAGMA foreign_keys: 0   -- ¡desactivado!
```

- Los modelos SQLAlchemy declaran `ForeignKey(...)` pero con acción `NO ACTION` (sin CASCADE)
- Peor: la pragma está **OFF** (pooled connections no ejecutan el event listener siempre)
- **Consecuencia:** inserts/updates que violarían FK **no fallan** — la DB queda inconsistente silenciosamente

#### 🟠 Causa 5 — `autoflush=False` en sesiones

```python
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
```

- Cambios en objetos ORM no se flushean hasta `commit()` explícito
- Si un endpoint hace `case.accionante = "X"` y luego lanza excepción sin commit, el cambio se pierde
- Las 3906 entradas `AI_EXTRAER` del audit_log sugieren muchas llamadas — ¿todas commiteadas?

#### 🟠 Causa 6 — Inconsistencias reales descubiertas

De mi escaneo post v5.0:

| Inconsistencia | Count | Severidad | Causa probable |
|----------------|-------|-----------|----------------|
| Documents con `case_id` apuntando a caso DUPLICATE_MERGED | **219** | 🔴 Alta | Merges anteriores (no solo v5.0) que no movieron todos los docs |
| Emails con `case_id` apuntando a DUPLICATE_MERGED | 30 | 🟠 Media | Mismo patrón |
| Documents con `file_path` fuera del `folder_path` del caso | **185** | 🔴 Alta | Casos renombrados sin actualizar file_path de docs |
| Casos con 4-5 errores de extracción consecutivos | 2 (503, 137) | 🟡 Baja | Casos problemáticos que bloquean el pipeline |

Estas 219+185 = **404 inconsistencias reales** son lo que ves como "descuadre". NO son corrupción de DB, son datos huérfanos / desalineados por operaciones históricas incompletas.

#### 🟡 Causa 7 — Pool de 5 conexiones sin affinity

```python
create_engine(..., pool_size=5, pool_recycle=300)
```

- Cada request puede usar cualquiera de las 5 conexiones
- SQLite WAL da **snapshot isolation**: una conexión puede ver estado antiguo hasta que haga nuevo `SELECT`
- Para apps pequeñas, `pool_size=1` es más predecible

### A.3 Plan de mitigación

| Acción | Impacto | Esfuerzo | Prioridad |
|--------|---------|----------|-----------|
| Activar `PRAGMA foreign_keys=ON` en cada connect | Evita FKs rotas silenciosas | 1 línea | **P0** |
| Checkpoint WAL periódico (cada 5 min) | WAL no crece, data fresca en disco | 10 líneas | P0 |
| Reducir `staleTime` React Query a 5s | UI se refresca más rápido post-mutación | 1 línea | P0 |
| Mover 219+30 docs/emails a canónicos | Corrige descuadre real | 1 script | **P0** |
| Sincronizar `file_path` de 185 docs con `folder_path` del caso | Corrige paths | 1 script | P0 |
| Agregar endpoint `/api/cleanup/reconcile` que haga los 3 puntos anteriores en 1 operación | Usuario puede correr cuando sospeche descuadre | 1 endpoint | P1 |
| `pool_size=1` (app single-user local) | Snapshot determinístico | 1 línea | P1 |
| Agregar invalidateQueries tras cada mutación (revisar 20+ mutations) | UI actualiza al instante | 30-45 min | P1 |
| Agregar a CI el test "0 docs en DUPLICATE_MERGED" | Alerta si regresa | 1 test | P2 |

---

## Parte B — Plan de mejoras para lo que NO mejoró en v5.0

### B.1 PENDIENTE_OCR (83 documentos escaneados)

**Diagnóstico:** PDFs que `pdftext` no puede leer porque son scans de imágenes. `document_normalizer.py` tiene un tier de PaddleOCR pero solo se activa opt-in.

**Plan:**

| Paso | Acción | Detalle |
|------|--------|---------|
| B1.1 | Script batch `scripts/reocr_pending.py` | Filtra `WHERE verificacion='PENDIENTE_OCR'`, aplica `normalize_pdf_lightweight()` a cada uno, actualiza `extracted_text` y cambia `verificacion='OK'` si produce >50 chars |
| B1.2 | Agregar a Cleanup Panel | Botón "Re-OCR pendientes" con progress bar |
| B1.3 | En pipeline de ingesta | Marcar `PENDIENTE_OCR` → auto-retry con OCR al siguiente `check_inbox` |
| B1.4 | Dashboard Salud | KPI nuevo: "Docs PENDIENTE_OCR" con botón directo de re-procesar |

**Costo:** $0 (OCR local, no API). Tiempo estimado: ~30s por PDF escaneado. 83 docs → ~40 min total.

### B.2 `abogado_responsable` (61.1% — solo 176 de 288 casos)

**Diagnóstico:** el campo solo se puebla desde `[TIPO: DOCX_RESPUESTA]` (respuesta de la Gobernación firmada). Muchos casos:
- Son **recientes** (no se ha respondido aún) → falso negativo aceptable
- Son de otros departamentos o PPL donde la Gobernación solo es vinculada → no responde
- Tienen DOCX sin footer (`Proyectó:`, `Elaboró:`) por formato distinto

**Plan:**

| Paso | Acción | Detalle |
|------|--------|---------|
| B2.1 | Regex adicional en `ABOGADO_FOOTER` | Tolerar variantes: `Elaboro:`, `Aprobó:`, firma digital `.p7z` |
| B2.2 | Extraer de emails enviados | Si `subject LIKE 'RESPUESTA ACCIÓN DE TUTELA%'` y sender es abogado, capturar |
| B2.3 | Tolerar `abogado_responsable='PENDIENTE'` | En casos sin respuesta, marcarlo explícitamente. Criterio: si `sentido_fallo_1st IS NULL AND fecha_ingreso < 3 días` → PENDIENTE no es error |
| B2.4 | Métrica derivada | "Cobertura de abogado en casos con respuesta" (filtrar solo los que ya tienen DOCX de respuesta). Ahí debería ser 95%+ |

**Beneficio esperado:** no sube el número bruto, pero la métrica se vuelve **honesta**. Un caso admitido hace 2 días sin abogado asignado NO es un error.

### B.3 `radicado_forest` (81.6%)

**Diagnóstico:** FOREST solo viene de emails de `tutelas@santander.gov.co`. Casos que:
- Fueron creados por sync de carpetas sin email → sin FOREST
- Son impugnaciones de años anteriores (2021-2025) sin FOREST nuevo

**Plan:**

| Paso | Acción |
|------|--------|
| B3.1 | Buscar FOREST en DOCX nombres | Patrón `3\d{6}|20260\d{6}` en filename, validar >0.7 similarity con FOREST blacklist invertido |
| B3.2 | Tolerar `radicado_forest='NO_APLICA'` | Casos antiguos (pre-2026) pueden no tener |
| B3.3 | Métrica derivada | "Cobertura FOREST en casos con email de tutelas@" |

### B.4 Docs SOSPECHOSO residual 211 (meta ≤30)

**Diagnóstico:** mi R5 reclasificó 69 por keyword (admin docs). Los 211 restantes son:
- Docs con texto ambiguo (ej. mencionan otro radicado pero pertenecen al caso)
- Docs de tutelas acumuladas (legítimamente mencionan 2 radicados)
- PDFs con OCR parcial o corrupto

**Plan (3 fases):**

| Fase | Acción | Cobertura esperada |
|------|--------|-------------------|
| B4.1 | `scripts/classify_sospechosos.py` | Re-ejecutar `verify_document_belongs` con datos actualizados de casos (post v5.0). Muchos casos ahora tienen rad23 que antes no → reconocimiento mejora. Esperado: 211 → ~120 |
| B4.2 | Nuevo doc_type `ANEXO_ADMIN_EXTERNO` | Docs de otras entidades que vienen en el expediente (respuesta del colegio, del ICBF, etc.). Keyword match ampliado. Esperado: 120 → ~60 |
| B4.3 | IA para los ambiguos | Batch de 60 docs × DeepSeek barato (~$0.001 c/u = $0.06 total). Clasifica `PERTENECE/NO_PERTENECE/ANEXO`. Esperado: 60 → ≤30 |

**Costo total B4:** ~$0.06 USD (casi nada).

### B.5 Costo/tiempo por caso ($0.0025 / 41s)

**Diagnóstico:** ya está cerca del piso razonable. Posibles mejoras:

| Opción | Detalle | Ahorro esperado |
|--------|---------|-----------------|
| Cache de extracciones | Si `docs_fingerprint` no cambia, saltar re-extracción | +20% velocidad en re-corridas |
| Prompt dinámico | Solo pedir campos faltantes (no los 28) si ya están poblados | -30% tokens |
| Regex-only para casos sin docs nuevos | Saltar IA si regex cubre >15/17 campos | -60% llamadas IA |

**Impacto real:** sobre 300 casos nuevos al año (estimado), los ahorros son de cents. No vale la pena priorizarlo.

---

## Parte C — Auditoría del Agente IA + herramientas

### C.1 Estado actual (v4.9 + adaptaciones menores v5.0)

**Arquitectura:**
- `backend/agent/runner.py` (477 líneas) — loop de agente con planner → ejecución tools
- `backend/agent/orchestrator.py` (473 líneas) — orquesta agentic extraction
- `backend/agent/tools/registry.py` — sistema de registro
- `backend/agent/tools/legal_tools.py` (443 líneas) — **16 herramientas registradas**

### C.2 Inventario de herramientas

| # | Tool | Categoría | Estado v5.0 |
|---|------|-----------|-------------|
| 1 | `buscar_caso` | search | ✅ funcional |
| 2 | `buscar_conocimiento` | search | ✅ funcional |
| 3 | `buscar_email` | search | ✅ funcional |
| 4 | `verificar_plazo` | analysis | ✅ funcional |
| 5 | `predecir_resultado` | analysis | ⚠️ usa `juzgado`+`derecho`+`ciudad` — con v5.0 los campos están más limpios, predicción mejora automáticamente |
| 6 | `analizar_abogado` | analysis | ✅ funcional |
| 7 | `obtener_contexto` | retrieval | ✅ funcional |
| 8 | `ver_razonamiento` | debugging | ✅ funcional |
| 9 | `listar_alertas` | management | ✅ funcional |
| 10 | `escanear_alertas` | management | ✅ funcional |
| 11 | `estadisticas_generales` | reporting | ⚠️ **no refleja KPIs v5.0** (no cuenta REVISION, no muestra duplicados F9) |
| 12 | `consultar_cuadro` | search | ✅ funcional |
| 13 | `casos_por_municipio` | search | ✅ funcional |
| 14 | `extraer_caso` | extraction | ✅ funcional |
| 15 | `consumo_tokens` | reporting | ✅ funcional |
| 16 | `contar_por_categoria` | reporting | ✅ funcional |

### C.3 Herramientas FALTANTES (a crear en v5.1)

Post-auditoría, el agente debería poder responder preguntas como:
- "¿Qué casos tienen folder mal formado?"
- "¿Hay duplicados pendientes de consolidar?"
- "¿Cómo está la salud general de datos?"

| # | Tool nueva | Categoría | Reemplaza/Usa |
|---|-----------|-----------|---------------|
| 17 | `diagnosticar_salud` | diagnostic | llama `/api/cleanup/health-v50` |
| 18 | `detectar_duplicados` | cleanup | query rad23 agrupados, expone `potential_duplicate_of` |
| 19 | `reconciliar_db` | cleanup | mueve docs de DUPLICATE_MERGED a canónicos (B4.1 arriba) |
| 20 | `verificar_rad23_integrity` | validation | re-corre validación B1+B13 en un caso o global |
| 21 | `resolver_sospechosos` | cleanup | invoca clasificador B4.1+B4.2 |
| 22 | `re_ocr_pending` | extraction | invoca B1.1 script |
| 23 | `consolidar_duplicados` | cleanup | merge 2 casos tras confirmación humana |

### C.4 Herramientas a ACTUALIZAR

**`estadisticas_generales`** (línea 239):

Actualmente devuelve:
- `total_casos`, `total_documentos`, `total_alertas`, casos por categoría temática...

Falta:
- `casos_por_status` (incluir REVISION que es nuevo)
- `folders_pendiente_revision` (target: 0)
- `completo_sin_rad23` (target: 0)
- `docs_sospechosos_por_caso_top10`
- `pares_duplicados_f9`

**`predecir_resultado`** — ya funciona, pero con v5.0:
- Más casos tienen rad23 completo → mejor agrupación por juzgado
- Menos contaminación en `ciudad` → clusters regionales más precisos
- **Esperado:** aumento de precisión del 5-10% sin tocar código

**`buscar_caso`** — puede beneficiarse de:
- Buscar también en `radicado_23_digitos` con digits-only match
- Priorizar casos con `processing_status = 'COMPLETO'` sobre REVISION/DUPLICATE_MERGED

### C.5 Observaciones arquitectónicas

1. **El agent runner usa Smart Router de v4.7+** — OK, DeepSeek + Haiku fallback. No necesita cambios.

2. **Reasoning logs están activos** — se pueden consultar con `ver_razonamiento`. Útil para debugging.

3. **Tools categorías actuales:** search, analysis, management, reporting, retrieval. Falta categoría **diagnostic/cleanup** para las nuevas.

4. **Tool execution es síncrona** — todas corren en el mismo thread del request. Para batch operations largos (B4.1 re-clasificar 211 docs), habría que mover a background con `threading` o `BackgroundTasks` de FastAPI.

---

## Parte D — Hoja de ruta propuesta v5.1

### Sprint 1 (arreglo inmediato descuadre — 2h)

1. **Fix foreign_keys OFF → ON** — 1 línea en `database.py`
2. **Checkpoint WAL por tiempo** — decorator/timer en FastAPI que haga `PRAGMA wal_checkpoint(PASSIVE)` cada 5 min
3. **Reducir staleTime a 5s** — 1 línea en `main.tsx`
4. **Script `reconcile_db.py`** — mueve 219 docs + 30 emails de DUPLICATE_MERGED, actualiza 185 file_path desalineados
5. **Test regresión** — "0 docs/emails deben apuntar a DUPLICATE_MERGED" + "docs.file_path debe estar dentro de cases.folder_path"

### Sprint 2 (B1-B4 plan de mejoras — 4h)

1. Script re-OCR 83 pendientes
2. Clasificador SOSPECHOSO en 3 fases (B4.1-B4.3)
3. Métricas "honestas" (cobertura condicional) en Dashboard

### Sprint 3 (agente IA v5.1 — 3h)

1. Actualizar `estadisticas_generales` con KPIs v5.0
2. Agregar tools 17-23 (diagnosticar_salud, detectar_duplicados, reconciliar_db, etc.)
3. Probar agente con preguntas de diagnóstico
4. Documentar `AGENTE_JURIDICO_IA.md` v5.1 con nuevas tools

**Total estimado:** 9 horas de trabajo, todo en 1-2 sesiones.

---

## Respuesta directa a tu pregunta

**"¿Por qué la DB se descuadra?"**

No se corrompe (integrity_check OK). Hay 3 razones combinadas:

1. **Scripts directos sqlite3 + FastAPI corriendo** → el ORM ve snapshots viejos hasta reciclar pool
2. **WAL sin checkpoint por tiempo** → datos en `.db-wal` no bajan a `.db` principal
3. **219 docs + 30 emails + 185 file_paths desalineados** de operaciones históricas (merges v4.8+ que no movieron TODO)

**Los 3 son solucionables en ~2h.** No hay corrupción, solo reconciliación pendiente.

**"¿Hay que actualizar tools del agente?"**

Sí, 7 tools nuevas a agregar (diagnosticar_salud, detectar_duplicados, reconciliar_db, etc.) + `estadisticas_generales` a ampliar con KPIs v5.0. Es trabajo de ~3h.
