# Comparativa de pureza DB — ANTES vs DESPUÉS

- **ANTES**: tutelas_backup_20260324.db
- **DESPUÉS**: tutelas.db

## Métricas agregadas

| Métrica | ANTES | DESPUÉS | Δ |
|---|---|---|---|
| **Purity score** | 72.30/100 | **68.71/100** | -3.59 🔴 |
| Total casos | 383 | 394 | +11 |
| Duplicidades docs (multi-caso) | 0 | 318 | +318 🔴 |
| Duplicidades casos | 0 | 13 | +13 🔴 |
| Carpetas mal nombradas | 239 | 90 | -149 🟢 |
| Casos vacíos | 122 | 72 | -50 🟢 |
| Inconsistencias rad23/folder | 0 | 46 | +46 🔴 |
| Emails sin caso | 10 | 104 | +94 🔴 |
| FK orphans documents | 0 | 0 | +0 ⚪ |

## Campos críticos vacíos
| Campo | ANTES | DESPUÉS | Δ |
|---|---|---|---|
| sin_accionante | 192 (50.1%) | 20 (5.1%) | -45.1pp 🟢 |
| sin_asunto | 264 (68.9%) | 15 (3.8%) | -65.1pp 🟢 |
| sin_ciudad | 264 (68.9%) | 35 (8.9%) | -60.0pp 🟢 |
| sin_derecho | 265 (69.2%) | 68 (17.3%) | -51.9pp 🟢 |
| sin_forest | 298 (77.8%) | 108 (27.4%) | -50.4pp 🟢 |
| sin_observaciones | 264 (68.9%) | 1 (0.3%) | -68.7pp 🟢 |
| sin_rad23 | 214 (55.9%) | 58 (14.7%) | -41.2pp 🟢 |

## Estado de verificación de documentos
| Estado | ANTES | DESPUÉS | Δ |
|---|---|---|---|
| (columna `verificacion` no existía en snapshot antiguo) | — | — | — |
| `ANEXO_SOPORTE` | 0 | 120 | +120 |
| `NO_PERTENECE` | 0 | 498 | +498 |
| `NULL` | 0 | 1 | +1 |
| `OK` | 0 | 3587 | +3587 |
| `PENDIENTE_OCR` | 0 | 11 | +11 |
| `REVISAR` | 0 | 66 | +66 |
| `SOSPECHOSO` | 0 | 210 | +210 |