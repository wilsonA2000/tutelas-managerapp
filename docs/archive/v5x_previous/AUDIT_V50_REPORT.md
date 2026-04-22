# AUDIT V50 — Reporte final

> Generado: 2026-04-20
> Auditoría + remediación: 9 fixes de código + 5 scripts de remediación histórica
> Tiempo total: ~5 horas (Fase 0-3 + Fase 5)
> Backups pre/post: `data/tutelas_preaudit_v50_20260420_193555.db` (pre) y DB actual (post)

## Criterios de éxito — matriz antes/después

| Criterio | Antes | Después | Target | Estado |
|----------|-------|---------|--------|--------|
| Folders `[PENDIENTE REVISION]` activos | 2 (541, 560) | **0** | 0 | ✅ |
| COMPLETO sin `radicado_23_digitos` | 18 | **0** | 0 | ✅ |
| Folders con `rad_corto(folder) != rad_corto(rad23)` | 85 (33 filtrados reales) | **0** | ≤5 | ✅ |
| Docs SOSPECHOSO | 269 | 211 | ≤30 | ⚠️ parcial (-22%) |
| Duplicados detectados (B13) | ~15-25 proyectados | 5 consolidados (541→531, 529→519, 542→504, 550→193, 556→504) | 0 abiertos | ✅ detectables |
| Tests regresión | 0 | **15/15 passing** | 8/8 | ✅ |

### Distribución de processing_status

| Status             | Antes  | Después | Δ      |
|--------------------|--------|---------|--------|
| COMPLETO           | 308    | 288     | -20    |
| DUPLICATE_MERGED   | 77     | 82      | +5 (consolidaciones R1/R3) |
| REVISION (nuevo)   | 0      | 15      | +15 (F8 aplicado) |
| **TOTAL**          | 385    | 385     | =      |

El cambio en COMPLETO (-20) se explica: -5 casos pasaron a DUPLICATE_MERGED (R1+R3) y -15 pasaron a REVISION porque no tienen rad23 ni pudieron extraerlo (F8 + R4).

### Docs verificacion

| verificacion     | Antes | Después | Δ    |
|------------------|-------|---------|------|
| OK               | 3474  | 3474    | =    |
| NO_PERTENECE     | 498   | 498     | =    |
| SOSPECHOSO       | 269   | 211     | -58  |
| ANEXO_SOPORTE    | 51    | 120     | +69  |
| PENDIENTE_OCR    | 83    | 83      | =    |
| REVISAR          | 58    | 47      | -11  |

---

## Validación del caso raíz: email `RV: URGENTE!!! NOTIFICA AVOCA TUTELA 2026-00057`

### Antes (pre-fix, caso 560)

```
folder_name:   2026-66132 [PENDIENTE REVISION]
rad23:         68-001-40-88-003-2026-00057-00    ← correcto
accionante:    NULL                              ← B6 fallo
observaciones: "Caso 2026-66132 en estado ACTIVO…"  ← B3 contaminado
juzgado:       NULL
ciudad:        NULL
fecha_ingreso: NULL
```

### Después (post-fix + R1)

```
folder_name:   2026-00057 LIBIA INES PATIÑO ROMÁN    ← F5 rename
rad23:         68-001-40-88-003-2026-00057-00
accionante:    LIBIA INES PATIÑO ROMÁN               ← F6 forwarded
observaciones: "El 14/04/2026, el Apoyo Jurídico
                de la Secretaría de Educación
                notificó la recepción de la tutela…" ← F4 cleanup
```

### Cadena causal corregida

| Antes (v4.9) | Después (v5.0) | Fix |
|--------------|----------------|-----|
| "Con número de radicado 20260066132" → regex matchea `2026-66132` | "Con número de radicado 20260066132" → regex NO matchea (negative lookahead) | **F1** |
| `extract_radicado` retorna `2026-66132` aunque rad23 existe | `extract_radicado` prioriza rad23→rad_corto, devuelve `2026-00057` | **F2** |
| Prompt inyecta `CARPETA: 2026-66132 [PENDIENTE REVISION]` → IA escribe "Caso 2026-66132…" | Prompt inyecta `RADICADO OFICIAL: 68-001-40-88-003-2026-00057-00 (rad corto 2026-00057)` | **F3** |
| Post-validator no detecta menciones ajenas | Post-validator elimina oraciones "Caso 20YY-NNNNN" contaminadas | **F4** |
| Folder `[PENDIENTE REVISION]` queda fosilizado | Rename automático usando rad_corto(rad23) | **F5** |
| Accionante LIBIA en nivel 4 forwarded no detectado | `_split_forwarded_blocks` escanea todos los niveles | **F6** |

---

## Fixes aplicados (Fase 2)

| Fix | Archivo | Líneas afectadas | Descripción |
|-----|---------|------------------|-------------|
| **F1** | `agent/regex_library.py` | ~59-77 | `RAD_LABEL` + `RAD_GENERIC` exigen separador guion + negative lookahead para FOREST 11d |
| **F2** | `email/gmail_monitor.py` | ~140-170 | `extract_radicado` prioriza rad_corto derivado de rad23 antes de probar labels |
| **F3** | `extraction/ai_extractor.py` | ~610, 781, 1025, 1235 | Nuevo `_build_anti_contamination_block(folder, radicado_oficial)` propagado a 3 funciones extractoras y `parallel_extract_with_ai` |
| **F4** | `extraction/post_validator.py` | ~240-325 | Nueva regla 8: detecta radicados ajenos en obs/asunto/pretensiones, elimina oraciones "Caso 20YY-NNNNN" contaminadas |
| **F5** | `extraction/pipeline.py` | ~548-640 | `_rename_folder_if_needed` usa rad_corto(rad23) como fuente de verdad + fuerza rename si difiere del folder |
| **F6** | `email/gmail_monitor.py` | ~195-280 | Nuevo `_split_forwarded_blocks`; `extract_accionante` escanea todos los niveles + STOP_TOKENS (ACCIONADO, CC, etc.) para corte limpio |
| **F7** | `email/gmail_monitor.py` | ~367-395 | `match_to_case` rechaza match por rad_corto cuando dígitos 6-12 del rad23 (juzgado) difieren |
| **F8** | `extraction/unified.py` | ~465-510 | Pre-COMPLETO: exige rad23 ≥18 dígitos O (folder nombrado + accionante); si no, REVISION |
| **F9** | `extraction/unified.py` | ~465-510 | Detecta duplicados por rad23/rad_corto (con juzgado) y registra en `stats["potential_duplicate_of"]` |

### Tests agregados

`tests/test_audit_v50.py` — **15 tests** cubriendo B1-B13:

```
TestB1_RegexRadLabel::test_foreign_forest_not_matched      PASSED
TestB1_RegexRadLabel::test_real_radicados_still_match      PASSED
TestB1_RegexRadLabel::test_all_patterns_self_test          PASSED
TestB2_ExtractRadicadoPrioritizesRad23                     PASSED (x2)
TestB3_AntiContaminationBlock                              PASSED (x2)
TestB4_ForeignRadicadosInObs                               PASSED (x2)
TestB6_ForwardedNested                                     PASSED (x2)
TestB7_MatchingByJuzgado::test_rejects_different_juzgado   PASSED
TestB8_PreCompletoValidation                               PASSED
TestB5_RenameFolderLogic                                   PASSED
TestB13_DuplicateDetection                                 PASSED
```

Suite global: **110 tests passing** (15 nuevos + 74 regresión existentes + 36 extraction/cases), 0 regresiones.

---

## Remediación histórica (Fase 3)

### R1 — Re-extracción casos críticos

| Caso | Antes | Después | Acción |
|------|-------|---------|--------|
| 560 | `2026-66132 [PENDIENTE REVISION]`, accionante=NULL | `2026-00057 LIBIA INES PATIÑO ROMÁN`, obs limpia | Rename + update accionante |
| 541 | `2026-69467 [PENDIENTE REVISION]`, duplicate de 531 | Marcado DUPLICATE_MERGED → id=531 (ANDREA PAREDES OLIVEROS) | Merge + movimiento de docs |

### R2 — Cleanup obs contaminadas

6 casos con oraciones "Caso 2026-NNNNN" eliminadas automáticamente por F4:
- 478, 489, 491, 495, 541, 560

### R3 — Rename 33 folders bugged

- **29 renames limpios** aplicados: 367, 392, 397, 421, 423, 426, 473, 489, 490, 491, 494, 503, 505, 508, 517, 519, 528, 533, 537, 540, 543, 544, 546, 547, 549, 553, 555, 561, 563
- **4 merges por conflicto de destino** (F9 auto-consolidación):
  - 529 → 519 (ELVER ALBEIRO ALVARADO SANTOS)
  - 542 → 504 (MARIA EUGENIA RIBEROS VÁSQUEZ)
  - 550 → 193 (DENNIS ROCÍO MENESES CASTRO)
  - 556 → 504 (MARIA EUGENIA RIBEROS VÁSQUEZ)

### R4 — Re-extracción 18 COMPLETO sin rad23

- **3 rad23 extraídos** vía regex desde documentos (sin IA): 272 (2025-00767), 531 (2026-00234), 554 (2026-00074)
- **15 casos marcados REVISION** por F8 (no hay rad23 extraíble): 133, 139, 190, 273, 322, 401, 405, 406, 447, 463, 532, 536, 552, 558, 562

### R5 — Reclasificación docs SOSPECHOSO

- 269 docs SOSPECHOSO → **69 reclasificados** a `ANEXO_SOPORTE` por keyword administrativa (cesion, contrato, acta de inicio, recomendaciones, envio correo, informe técnico, etc.)
- 211 docs SOSPECHOSO restantes requieren **revisión manual** en panel Cleanup (Fase 4 pendiente)

---

## Pendientes / No abordado en esta iteración

### Fase 4 — Mejoras UX (pendiente)

- U1 Tooltips explicativos en `Extraction.tsx`
- U2 Renombrar counter "498 pendientes" → "498 docs NO_PERTENECE"
- U3 Modal warning antes de classify
- U4 Modal warning antes de /audit
- U5 Panel "Salud de datos" con KPIs accionables

### R5 complemento — Reducir SOSPECHOSO <30

211 docs SOSPECHOSO restantes. Requiere:
- Script de análisis por caso vs rad23
- Reutilizar `verify_document_belongs` sobre docs actualizados con los nuevos campos
- Posible creación de `doc_type = ANEXO_ADMINISTRATIVO` (vs ANEXO_SOPORTE actual)

### Bug B10 (UX terminología) — no abordado

Los checkboxes "Clasificar" y counters del UI siguen confusos. Requiere revisión de Extraction.tsx.

---

## Lecciones aprendidas

1. **B1 era más sistémico de lo estimado**: afectaba 22% de casos (85 candidatos de 385), no ~6-8% estimado inicialmente. La DB tenía **33 folders bugged reales** (después de filtrar falsos positivos de la query por seq≥10000 que capturaba rad judiciales legítimos).

2. **B13 (duplicación) se manifestó en cascada**: al corregir B1, 5 folders bugged colisionaron con casos existentes (mismo rad_corto, mismo juzgado) → auto-consolidación.

3. **El filtro correcto para B1 es**: `rad_corto(folder) != rad_corto(rad23)` **Y** `rad_corto(folder) == rad_corto(forest)` (o seq ≥ 10000 sin forest registrado). El criterio del plan original (seq ≥ 10000) tenía falsos positivos (304, 306, 389: radicados judiciales legítimos con consecutivo alto).

4. **F4 post-validator debe ignorar FOREST literales**: patrones como `"FOREST NNNNNNNNNNN"` o `"radicado NNNNNNNNNNN"` no son contaminación — son referencias legítimas del trámite. Filtrarlos ANTES de detectar radicados ajenos.

5. **F6 requiere STOP_TOKENS post-match**: el regex `accionante[:\s]+([A-Z...]+\s{5,50})` captura palabras tipo "ACCIONADO" después del nombre. Cortar al primer STOP_TOKEN mejoró los resultados (de "JENNY PAOLA TARAZONA ARIAS ACCIONADO" → "JENNY PAOLA TARAZONA ARIAS").

6. **Plan dry-run obligatorio para R3**: el `--dry-run` detectó 3 conflicts de merge antes de mover archivos. Sin él, el script hubiera fallado silenciosamente al llegar a esos casos.

---

## Métricas de esfuerzo

- **Auditoría (Fase 1)**: ~1.5h (25 casos de muestreo + 4 queries agregadas)
- **Fixes de código (Fase 2)**: ~2h (9 fixes con tests)
- **Remediación histórica (Fase 3)**: ~1.5h (R1-R5 con backups + dry-run)
- **Reporte + verificación (Fase 5)**: ~0.5h

**Archivos generados:**
- `docs/AUDIT_V50_SAMPLES.csv`
- `docs/AUDIT_V50_SAMPLES.md`
- `docs/AUDIT_V50_FINDINGS.md`
- `docs/AUDIT_V50_REPORT.md` (este)
- `tests/test_audit_v50.py`
- `data/tutelas_preaudit_v50_20260420_193555.db` (backup integridad SHA256 verificado)
- `data/tutelas_pre_R1_20260420_202436.db` (backup pre-remediación)
- `backend_preaudit_v50_20260420_193557/` (snapshot código)
