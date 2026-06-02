# Scripts archivados — ya ejecutados, no recurrentes

Conservados como audit trail histórico. **No re-ejecutar** sin entender el contexto.

## Cleanup P1-P7 (sesión 2026-04-21)
Cadena ejecutada UNA vez para limpieza masiva v5.3.3. Resultado: 16 casos
duplicados fusionados, 509 docs marcados DUPLICADO, purity 68.71 → 74.74.

- `cleanup_p1_merge_duplicates.py` — Fusión de duplicados por radicado
- `cleanup_p2_mark_hash_duplicates.py` — Marcar docs con mismo hash
- `cleanup_p3_rename_folders.py` — Normalizar nombres carpetas
- `cleanup_p4_relocate_docs.py` — Reubicar docs huérfanos
- `cleanup_p5_rematch_emails.py` — Re-asignar emails sin caso
- `cleanup_p6_archive_empty.py` — Archivar casos vacíos
- `cleanup_p7_rad_folder_report.py` — Reporte final radicado↔carpeta

## Setup one-shot
- `setup_privacy.py` — Inicialización capa PII v5.3 (genera Fernet key + crea tablas).
  Ejecutado en deploy v5.3.

## Benchmarks históricos (snapshot puntual)
- `benchmark_v47.py` — Comparativa v4.7 (Gemini ya eliminado en v5.4)
- `benchmark_v52_vs_v53.py` — Validación PII layer v5.3
- `benchmark_versions_compared.py` — Series de versiones
- `benchmark_cognition.py` — Cognición v5.3.1
- `compare_purity.py` — Purity score post P1-P7
- `catalog_variants.py` — Análisis variantes carpetas
- `db_purity_audit.py` — Auditoría DB purity v5.3.3

## Diagnóstico semántico asunto/derecho (sesión 2026-06-02)
One-shots usados para diagnosticar/validar el fix de `asunto`/`derecho_vulnerado`
LLM-first (commits cdd1cc2/531efec). Ya cumplieron su función:
- `sem_classify_derecho.py` — clasificador standalone temprano (peor que el pipeline real;
  no usaba json_schema). Destapó que el error dominante era el ASUNTO, no el derecho.
- `sem_validate_llm_first.py` — harness que llama a los `_llm_classify_*` reales del
  pipeline para comparar contra la DB antes de cambiar código.

## Scripts ACTIVOS (no archivados, en `scripts/`)
- `active_learning.py` — Scheduler activo
- `diagnosis.py` — Diagnóstico recurrente
- `reconcile_by_accionante.py` — Reconciliación periódica
- `reocr_pending.py` — Re-OCR de docs PENDIENTE_OCR
- `reverify_sospechosos.py` — Re-verificación de docs SOSPECHOSO
- `sem_before_after.py` — Preview antes/después de asunto/derecho con las funciones reales (reutilizable)
- `sem_apply_93.py` — Aplica el preview con filtro de confianza (asunto sí, derecho alta-conf)
- `reclassify_demanda_falsa.py` — Reclasifica DEMANDA_TUTELA falsas (autos/informes), idempotente
