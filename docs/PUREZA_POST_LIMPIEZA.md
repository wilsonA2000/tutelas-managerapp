# Comparativa de pureza DB — ANTES vs DESPUÉS

- **ANTES**: tutelas.db.pre_cleanup_v534_20260421_181958.bak
- **DESPUÉS**: tutelas.db

## Métricas agregadas

| Métrica | ANTES | DESPUÉS | Δ |
|---|---|---|---|
| **Purity score** | 68.71/100 | **74.74/100** | +6.03 🟢 |
| Total casos | 394 | 378 | -16 |
| Duplicidades docs (multi-caso) | 318 | 301 | -17 🟢 |
| Duplicidades casos | 13 | 4 | -9 🟢 |
| Carpetas mal nombradas | 90 | 54 | -36 🟢 |
| Casos vacíos | 72 | 53 | -19 🟢 |
| Inconsistencias rad23/folder | 46 | 29 | -17 🟢 |
| Emails sin caso | 104 | 102 | -2 🟢 |
| FK orphans documents | 0 | 0 | +0 ⚪ |

## Campos críticos vacíos
| Campo | ANTES | DESPUÉS | Δ |
|---|---|---|---|
| sin_accionante | 20 (5.1%) | 20 (5.3%) | +0.2pp 🔴 |
| sin_asunto | 15 (3.8%) | 15 (4.0%) | +0.2pp 🔴 |
| sin_ciudad | 35 (8.9%) | 35 (9.3%) | +0.4pp 🔴 |
| sin_derecho | 68 (17.3%) | 64 (16.9%) | -0.3pp 🟢 |
| sin_forest | 108 (27.4%) | 102 (27.0%) | -0.4pp 🟢 |
| sin_observaciones | 1 (0.3%) | 1 (0.3%) | +0.0pp 🔴 |
| sin_rad23 | 58 (14.7%) | 58 (15.3%) | +0.6pp 🔴 |

## Estado de verificación de documentos
| Estado | ANTES | DESPUÉS | Δ |
|---|---|---|---|
| `ANEXO_SOPORTE` | 120 | 90 | -30 |
| `DUPLICADO` | 0 | 509 | +509 |
| `NO_PERTENECE` | 498 | 333 | -165 |
| `NULL` | 1 | 1 | +0 |
| `OK` | 3587 | 3235 | -352 |
| `PENDIENTE_OCR` | 11 | 11 | +0 |
| `REUBICADO_AUTO` | 0 | 88 | +88 |
| `REVISAR` | 66 | 64 | -2 |
| `SOSPECHOSO` | 210 | 162 | -48 |