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

## Scripts ACTIVOS (no archivados, en `scripts/`)
- `active_learning.py` — Scheduler activo
- `diagnosis.py` — Diagnóstico recurrente
- `reconcile_by_accionante.py` — Reconciliación periódica
- `reocr_pending.py` — Re-OCR de docs PENDIENTE_OCR
- `reverify_sospechosos.py` — Re-verificación de docs SOSPECHOSO
