# Benchmark v4.8 — Provenance + Cleanup (materia prima limpia)

**Fecha:** 2026-04-09 / 2026-04-10
**Sesion:** Paquetes email inmutables + limpieza profunda de DB y disco
**Cambio arquitectonico:** la tabla `documents` ahora vive encadenada al correo de origen (email_id FK inmutable). Los hermanos del mismo paquete viajan juntos al reasignar entre casos — regla absoluta por diseño.

---

## 1. Resumen ejecutivo

- **Raiz del desorden identificada y atacada**: el vinculo email → documents no existia en el schema. Cada doc Gmail era huerfano y tenia que "adivinar" su caso. 192 NO_PERTENECE, fragmentos, duplicados — todo era sintoma del mismo bug arquitectonico.
- **F0 Provenance**: migracion de schema + backfill retroactivo vinculo 798 docs (19.96%) al email de origen. La ingesta Gmail nueva queda blindada: imposible por diseño que un adjunto se separe de su body.md.
- **F1 Diagnosis**: reporte read-only revelo 8 grupos auto-mergeables con mismo radicado_23d + accionante, 12 carpetas con typos, 24 fragmentos, 1,516 docs sin content_hash, 192 NO_PERTENECE.
- **F2 Hash backfill**: 1,516 → **0 docs sin hash** (100% cobertura, 713 grupos duplicados descubiertos por MD5).
- **F3 Merge**: 8 grupos fusionados, **12 casos duplicados consolidados**, **70 documents** re-localizados a sus canonicos (regla "hermanos viajan juntos" activa — movio 20 docs extra por propagacion de paquetes).
- **F4 Emails MD**: 28 emails .md faltantes generados + vinculados via email_id.

**Resultado**: materia prima limpia, lista para re-extraccion con benchmarks reales.

---

## 2. Tabla maestra — Pre-cleanup vs Post-cleanup

| Metrica                          | v4.7 pre-cleanup (9 abr mañana) | **v4.8 post-cleanup (9 abr noche)** | Delta |
|----------------------------------|---------------------------------|-------------------------------------|-------|
| Casos totales                    | 337                             | 337 (325 activos + 12 merged)       | -12 activos |
| Documents totales                | 3,997                           | 4,025                               | +28 (.md nuevos) |
| Emails totales                   | 1,084                           | 1,084                               | — |
| **Docs con `email_id` (provenance)** | 0                           | **826 (20.52%)**                    | **+826** |
| **Docs con `content_hash`**      | 2,481 (62.07%)                  | **4,025 (100%)**                    | **+1,544** |
| Grupos auto-mergeables pendientes| 8                               | **0**                               | ✅ resueltos |
| Casos con radicados duplicados   | 15                              | 7 (los manual review)               | -8 |
| Fragmentos detectados            | 24                              | 19                                  | -5 |
| Docs NO_PERTENECE                | 192                             | 191                                 | -1 |
| Grupos hashes duplicados         | desconocido (pre-hash)          | 713 (post-hash, para F3+)           | +descubierto |

---

## 3. F0 Provenance: vinculo email → documents

### Cobertura por doc_type (post-backfill F0c + F4)

| Doc Type                 | Total | Con email_id | Cobertura |
|--------------------------|-------|--------------|-----------|
| OTRO                     | 1,110 | 359          | 32.3% |
| PDF_OTRO                 | 537   | 49           | 9.1% |
| GMAIL                    | 405   | 0            | 0% (sync de carpetas, no Gmail API) |
| SENTENCIA                | 331   | 88           | 26.6% |
| AUTO_ADMISORIO           | 280   | 63           | 22.5% |
| PDF_AUTO_ADMISORIO       | 269   | 21           | 7.8% |
| RESPUESTA_DOCX           | 262   | 76           | 29.0% |
| EMAIL_MD                 | 283   | 66+28 = 94   | 33.2% |
| INCIDENTE                | 104   | 43           | 41.3% |

**Interpretacion**: los docs `GMAIL` no estan vinculados porque vinieron por sync de carpetas (no por descarga Gmail API), asi que no hay Email records asociados. El resto tiene cobertura parcial por la heuristica del backfill (file_path exacto + case_id+filename). Los docs sin email_id son legacy — documentos locales (DOCX de respuestas, screenshots FOREST, PDFs escaneados manualmente) que nunca vinieron por correo.

### Regla "hermanos viajan juntos" (validada)

En F3 merge, cuando se movieron los 70 documents al canonico, 20 de ellos eran **hermanos arrastrados por la regla de provenance** (no estaban en el dry_run count porque pertenecian a paquetes que se propagaron). Esto confirma que la infraestructura v4.8 F0 funciona: si el sistema decide mover el PDF X del email #452 al caso B, los otros 4 adjuntos del mismo correo van con el, automaticamente. Cero intervencion manual.

---

## 4. F3 Merge: grupos fusionados

| # | Canonico (id / folder / docs) | Merge desde | Docs movidos | Emails reasignados |
|---|-------------------------------|-------------|---------------|---------------------|
| 1 | 240 / Jose Rafael Peñaloza (9) | 55 (vacio) | 0 | 2 |
| 2 | 305 / Ronald Diaz Daza (5)     | 115 (vacio) | 0 | 0 |
| 3 | 143 / Ana Milena Cacua Pabon (36) | 399, 402 (3) | 3 | 2 |
| 4 | **206 / Ingrid Tatiana (46→70)**  | 471 (24)    | **24** | 0 |
| 5 | **260 / Nayibe Castaño (31→45)**  | 395, 396, 422 (14) | **14** | 4 |
| 6 | 284 / Rubiela Calderon (16)    | 400 (6)     | 6 | 1 |
| 7 | 351 / Oscar Mauricio Rojas (19) | 475, 476 (2) | 2 | 0 |
| 8 | 456 / Tania Vanessa Cardenas (3) | 452 (1)    | 1 | 0 |
| **TOTAL** | — | 12 casos | **70** (50 directos + 20 por hermanos) | **9** |

Los 12 casos duplicados quedan marcados `DUPLICATE_MERGED` con 0 docs — sirven como tombstones para rollback. No contaminan el count de casos activos ni el Cuadro.

---

## 5. Estado final (post-cleanup)

```
=== DB ===
Casos totales:          337
  COMPLETO:             321 (activos)
  REVISION:               4 (legacy)
  DUPLICATE_MERGED:     12 (tombstones por F3)
Documents totales:     4,025
  Con email_id:          826 (20.52%)
  Con content_hash:    4,025 (100%)
Emails:                1,084

=== Integridad ===
FKs rotos:                0
Docs huerfanos:           0
Casos con 0 docs:        19 (de los cuales 12 son DUPLICATE_MERGED legitimos)

=== Backups creados esta sesion ===
- pre_cleanup: 61.94 MB
- pre_f2_hash_backfill: 62.32 MB
- pre_f4_emails_md: 62.56 MB
- pre_f3_merge: 62.56 MB
```

---

## 6. Tests

| Suite | Resultado |
|---|---|
| `tests/test_provenance.py` (v4.8 F0 nuevos) | 10/10 ✅ |
| `tests/test_extraction.py` | 16/16 ✅ |
| `tests/test_parallel_extraction.py` (v4.7) | 15/15 ✅ |
| `tests/test_emails.py` | 11/11 ✅ |
| **TOTAL** | **52/52 verde** (0 regresiones tras F3) |

---

## 7. Comandos de operacion

```bash
# F1: diagnosticar (no toca nada)
python scripts/diagnosis.py --save data/diag_hoy.md
curl http://localhost:8000/api/cleanup/diagnosis.md

# F2: hash backfill (safe)
curl -X POST http://localhost:8000/api/cleanup/hash-backfill -d '{"dry_run":false}' -H "Content-Type: application/json"

# F4: emails md backfill (safe)
curl -X POST http://localhost:8000/api/cleanup/emails-md-backfill -d '{"dry_run":false}' -H "Content-Type: application/json"

# F3: merge dry_run (opt-in)
curl -X POST http://localhost:8000/api/cleanup/merge-identity -d '{"dry_run":true}' -H "Content-Type: application/json" | jq

# F3: merge REAL (despues de revisar dry_run)
curl -X POST http://localhost:8000/api/cleanup/merge-identity -d '{"dry_run":false}' -H "Content-Type: application/json"

# Ver paquete de un email
curl http://localhost:8000/api/emails/1/package | jq

# Ver timeline de correos de un caso
curl http://localhost:8000/api/cases/364/email-packages | jq

# Preview de move con hermanos
curl http://localhost:8000/api/extraction/docs/1383/move-preview | jq
```

---

## 8. Iteracion extendida (F3b + F5 + legacy backfill)

Tras el commit inicial v4.8 F2-F4, continuamos con 3 acciones adicionales:

### 8.1 Backfill EMAIL_MD legacy (+106 docs vinculados)

`backend/database/migrations/v48_backfill_email_md_legacy.py` — 2 estrategias:
- D) hash hex en filename → match con emails.message_id (0 matches, message_ids en formato Outlook)
- E) `Email_YYYYMMDD_<subject>.md` → match por case_id + fecha (+/- 3 dias) + first_words_key

Resultado: **106/217 EMAIL_MD legacy vinculados** (48.8%). Los 111 restantes son formatos muy antiguos.

### 8.2 F3b Reasignacion individual de NO_PERTENECE (+70 docs movidos)

`backend/services/cleanup_actions.py::batch_move_no_pertenece` — solo confidence ALTA:
- Extrae radicado 23d del texto, busca caso con mismo sufijo
- Reusa `move_document_or_package` (regla hermanos aplica)

Resultado: **63 docs movidos directos + 7 hermanos arrastrados = 70 total**. NO_PERTENECE bajo de 192 → 141 (-51, algunos hermanos ya estaban en destino correcto). Duracion: 2.4s. 0 errores.

### 8.3 F5 Re-extraccion de 8 canonicos fusionados

Re-corrimos `unified_extract` sobre los 8 canonicos post-merge para capturar campos que podrian estar en los docs movidos desde los fragmentos.

**Resultado sorprendente**: +0 campos totales. Los canonicos ya estaban completos (18-19/19 campos) desde el momento del merge, porque `unified_extract` respeta campos ya poblados y el sistema heredó la info en la fusion.

**Efecto colateral positivo**: el caso 206 Ingrid pasó de 70 → 58 docs. El pipeline detecto 12 docs duplicados/NO_PERTENECE dentro del caso y los marco automaticamente. **Esto sugiere que F5 es util como limpieza de consistencia interna, no como mejora de cobertura.**

## 9. Estado final definitivo (post-iteracion extendida)

| Metrica | v4.7 inicio | v4.8 post-F4 | **v4.8 final** |
|---|---|---|---|
| Docs con file_hash | 62% | 100% | **100%** |
| Docs con email_id (provenance) | 0% | 20.52% | **23.16%** |
| Docs NO_PERTENECE | 192 | 191 | **141** (-51) |
| Grupos auto-mergeables | 8 | 0 | **0** |
| Casos DUPLICATE_MERGED | 0 | 12 | **12** |
| Casos COMPLETO activos | 337 | 321 | **321** |

## 10. Lessons learned

1. **El merge ya aplica los campos del fusionado al canonico** — no hay que re-extraer despues de F3, la info ya esta en el canonico via SQL UPDATE.
2. **La regla "hermanos viajan juntos" funciona en produccion** — en F3 se arrastraron 20 docs por propagacion de paquetes, y en F3b otros 7.
3. **PENDIENTE_OCR (293 docs)** es un problema separado del cleanup — son PDFs escaneados que necesitan OCR para dar su radicado. Pendiente para futuras iteraciones con PaddleOCR.
4. **Los 111 EMAIL_MD legacy sin vincular** son de un formato pre-v3 (nombres como `Email_EXTRACCION_<hash>_...`) — la estrategia del hash no matcheo porque los message_ids actuales no usan hex. Podria tackearse con heuristica diferente en futuro.

## 11. Proximas mejoras posibles (ya fuera de scope v4.8)

1. **PENDIENTE_OCR**: re-correr PaddleOCR sobre los 293 docs escaneados
2. **Typos de carpeta** (`20222-`, `2026 -0055`, etc): renombrar en disco + actualizar folder_path. 12 folders afectadas.
3. **UI CleanupPanel**: componente frontend que expone F1-F5 al usuario con confirmaciones visuales. Hoy solo backend + CLI.
4. **Los 141 NO_PERTENECE restantes**: requiere revision manual o una heuristica mas agresiva (confidence MEDIA con validacion adicional).
5. **111 EMAIL_MD legacy pre-v3** sin vincular: requeririan re-descargar los emails desde Gmail para obtener message_id fresh, probablemente no vale la pena.

---

**Generado:** 2026-04-09 (provenance F0) + 2026-04-10 (F1-F4)
**Proximo update:** tras re-extraccion de canonicos y medicion de campos/caso post-cleanup
