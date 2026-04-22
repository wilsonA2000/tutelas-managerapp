# AUDIT V50 — Diagnóstico agregado

> Generado: 2026-04-20 | DB: 385 casos / 4,434 docs / 1,493 emails
> Backup pre-auditoría: `data/tutelas_preaudit_v50_20260420_193555.db` (SHA256 verificado)

## Matriz de prevalencia (refinada tras Fase 1.2)

| Bug | Descripción | Casos afectados | % base 385 | Notas |
|-----|-------------|-----------------|-----------|-------|
| **B1** | Regex RAD_LABEL captura FOREST como radicado corto | **85 folders disonantes** | **22.1%** | Query B abajo; rad_corto(folder) ≠ rad_corto(rad23) |
| **B2** | extract_radicado no prioriza rad23 | ≥85 (subconjunto B1) | 22% | Misma población que B1 |
| **B3** | Prompt inyecta folder literal en obs | ≥15 confirmados | 3.9% | Query A refinada (excluye FOREST literales) |
| **B4** | Post-validator no filtra radicados ajenos | ≥15 confirmados | 3.9% | Mismo que B3 (correlacionado) |
| **B5** | No renombra folder `[PENDIENTE REVISION]` | 6 folders | 1.6% | id 465, 500, 501, 502, 541, 560 |
| **B6** | Accionante en forwarded nivel ≥3 no detectado | ≥1 confirmado (id=560) | >0.3% | Requiere re-parsing de emails para cuantificar |
| **B7** | Matching solo por year:seq (no por juzgado) | ≥21 mismatches email-caso en 14d | 7.1% de emails 14d | Query D abajo |
| **B8** | Folders forest-like sistémico | **85 reales** (filtro seq≥10000 sobreestimaba con 54 pero subestimaba B1) | 22% | Corrección metodológica |
| **B9** | /audit destructivo sin backup auto | — | — | Bug de UX/workflow |
| **B10** | UI terminología confusa | — | — | Bug de UX |
| **B11** | 269 docs SOSPECHOSO sin workflow | **81 casos** | 21% | Query C abajo |
| **B12** | COMPLETO sin rad23 válido | 18 casos | 4.7% | Query identificada en Fase 1 |
| **B13** (nuevo) | Matcher no reconsolida duplicados post-rad23 | ≥1 confirmado (541 vs 531) | >0.3% | Buscar por query Fase 2 |

### Hallazgo crítico: B1 afecta 22% de casos, no ~6-8% como estimé inicialmente

La query refinada `WHERE rad_corto(folder_name) ≠ rad_corto(radicado_23_digitos)` detecta **85 casos** con folder disonante del rad23 oficial — **la mayoría con folder formado desde el FOREST**. El filtro original del plan (seq ≥ 10000) capturaba solo 54 y además tenía falsos positivos (304, 306, 389 de la muestra son radicados judiciales legítimos con consecutivo alto, no FOREST).

**Criterio correcto:** un folder es "bugged" si `rad_corto(folder)` difiere de `rad_corto(rad23)` **Y** `rad_corto(folder) == rad_corto(forest)` (es decir, el folder viene del FOREST, no de un rad judicial).

---

## Query A — Observaciones/asunto/pretensiones contaminadas (15 casos)

Filtro: menciones `20YY-NNNNN` en campos narrativos que ≠ rad_corto(rad23) y ≠ rad_corto(folder), **excluyendo** patrones `FOREST \d{7+}`, `radicado número \d{7+}`, `número de radicado \d{7+}`.

| ID  | rad23 → rad corto | Menciones ajenas                    | Folder                                              |
|-----|-------------------|-------------------------------------|-----------------------------------------------------|
| 130 | 2025-00055        | 2026-00055                          | 2025-00055-01 JOSE LUIS PRADA BECERRA               |
| 206 | 2026-00032        | 2026-00008                          | 2026-00032 INGRID TATIANA NIÑO MUÑOZ                |
| 217 | 2026-00041        | 2026-00039                          | 2026-00041 DIANA GANCINO GALVAN                     |
| 224 | 2026-00066        | 2026-00067                          | 2026-00066 y 2026-00067 BISNEY QUINTERO             |
| 241 | 2026-00105        | 2024-00641                          | 2026-00105 YINA PAOLA RUEDA RIOS                    |
| 267 | 2026-00028        | 2025-02026                          | 2026-0025 JUAN GUILLERMO SALAZAR                    |
| 281 | 2026-00043        | 2025-00110                          | 2026-0043 KARINA ARAUJO                             |
| 307 | 2026-00429        | 2026-00100                          | 2026-429 DILSA ACEVEDO PARADA                       |
| 364 | 2026-00022        | 2023-00002, 2025-00002              | 2026-00022 MILTON BLADIMIR CAMACHO NIÑO             |
| 410 | 2026-01417        | 2024-00203                          | 2026-01417 Edgar Alonso Sánchez Cuadros             |
| 465 | (NULL)            | 2026-00014                          | 2026-00000 [PENDIENTE IDENTIFICACION]               |
| 482 | 2026-00071        | 2026-00078                          | 2026-00071 Luz Adriana Solórzano García             |
| 508 | 2024-00070        | 2026-00024                          | 2026-61664 Alix Piratoa Reyes                       |
| 512 | 2025-00097        | 2025-00089, 2025-00092, 2025-00093  | 2025-00097 SANDRA MILENA BAUTISTA GONZÁLEZ          |
| 513 | 2025-00089        | 2025-00092, 2025-00093, 2025-00094  | 2025-00089 PABLO GOMEZ ACOSTA - JUAN FER            |

**Análisis:**
- **512, 513** mencionan tutelas acumuladas (legítimas) — no son contaminación, son referencias cruzadas válidas. F4 debe tolerar este patrón cuando la obs use keywords "acumulad|relacionad|conex".
- **224** folder mismo menciona "2026-00066 y 2026-00067" — tutelas acumuladas documentadas explícitamente.
- **130, 206, 217, 241, 267, 281, 307, 364, 410, 482, 508** → contaminación real (B3+B4).
- **Contaminación neta: 11 casos** (~3% de 385).

---

## Query B — Folders con rad corto disonante del rad23 (85 casos)

Criterio: `rad_corto(folder) != rad_corto(rad23)` y ambos existen.

### Top 30 (por secuencia del folder descendente — los más recientes):

| ID  | seq folder | rad corto real (rad23) | rad corto folder | FOREST match?         | Folder                                          |
|-----|------------|------------------------|------------------|-----------------------|-------------------------------------------------|
| 529 | 71556      | 2026-00060             | 2026-71556       | ✓ (`20260071556`)     | ELVER ALBEIRO ALVARADO SANTOS                   |
| 533 | 71240      | 2026-00024             | 2026-71240       | ✓                     | Alix Piratoa Reyes                              |
| 537 | 70528      | 2026-00048             | 2026-70528       | ✓                     | JESSIKA VIVIANA CAMARGO ARDILA                  |
| 542 | 69947      | 2026-00258             | 2026-69947       | ✓                     | MARIA EUGENIA RIBEROS VÁSQUEZ                   |
| 543 | 69697      | 2026-00047             | 2026-69697       | ✓                     | LEIBY ADRIANA GARCIA ROMERO                     |
| 544 | 69572      | 2026-00062             | 2026-69572       | ✓                     | FABIO LEANDRO CARREÑO NIÑO                      |
| **541** | 69467  | **2026-00234**         | 2026-69467       | ✓                     | **[PENDIENTE REVISION]** (caso B1 raíz)         |
| 546 | 69420      | 2026-00055             | 2026-69420       | ✓                     | LEÓNIDAS MARTÍNEZ MARTÍNEZ                      |
| 540 | 69406      | 2025-00020             | 2026-69406       | ✓                     | YESSENIA FERNANDA SANDOVAL BECERRA              |
| 547 | 69398      | 2026-00032             | 2026-69398       | ✓                     | PERSONERIA MUNICIPAL DE GAMBITA                 |
| 549 | 68836      | 2026-00096             | 2026-68836       | ✓                     | Cindy Katherine Vesga Montoya                   |
| 550 | 68810      | 2026-00018             | 2026-68810       | ✓                     | DENNIS ROCÍO MENESES CASTRO                     |
| 553 | 67616      | 2026-00061             | 2026-67616       | ✓                     | CIRO ALFONSO CAICEDO CAICEDO                    |
| 555 | 67547      | 2026-00066             | 2026-67547       | ✓                     | RUTH QUIJANO GARCÉS                             |
| 556 | 67423      | 2026-00258             | 2026-67423       | ✓                     | MARIA EUGENIA RIBEROS VÁSQUEZ (dup de 542)      |
| **560** | 66132  | **2026-00057**         | 2026-66132       | ✓                     | **[PENDIENTE REVISION]** (caso B1 raíz)         |
| 561 | 65547      | 2026-10003             | 2026-65547       | ✓                     | CEIDY LORENA GAITÁN BENAVIDES                   |
| 563 | 64775      | 2025-00058             | 2026-64775       | ✓                     | DIANA SERRANO AMADO                             |
| 528 | 64514      | 2026-00129             | 2026-64514       | ✓                     | AYDE PEREZ MURILLO                              |
| 517 | 63875      | 2026-00174             | 2026-63875       | ✓                     | Jorge Luis Sandoval Carvajal                    |
| 519 | 63646      | 2026-00060             | 2026-63646       | ✓                     | ELVER ALBEIRO ALVARADO SANTOS (dup de 529)      |
| 525 | 62372      | 2026-00042             | 2026-62372       | ✓                     | YINETH RUBIELA SANTOS C (dup de 492)            |
| 505 | 61862      | 2026-00052             | 2026-61862       | ✓                     | JENNY PAOLA TARAZONA ARIAS                      |
| 508 | 61664      | 2024-00070             | 2026-61664       | ✓                     | Alix Piratoa Reyes (dup de 533)                 |
| 503 | 60408      | 2026-00021             | 2026-60408       | ✓                     | WILMAN DARÍO ANTOLÍNEZ PEÑA                     |
| 497 | 59830      | 2026-00055             | 2026-59830       | ✗ (FOREST NULL)       | Sara Edilia Mogollón Bustamante                 |
| 495 | 59623      | 2026-00240             | 2026-59623       | ✗ (mismatch)          | YADIRA MONTOA CRISTANCHO                        |
| 494 | 59243      | 2026-00239             | 2026-59243       | ✓                     | NICOLL DANIELA SALCEDO GONZÁLEZ                 |
| 492 | 58982      | 2026-00042             | 2026-58982       | ✗ (mismatch)          | YINETH RUBIELA SANTOS                           |
| 491 | 58927      | 2026-00076             | 2026-58927       | ✓                     | MARIA CAMILA SALCEDO GONZALEZ                   |

**+55 más** con mismo patrón.

**Hallazgo adicional — B13 cuantificado parcialmente:** varios pares son duplicados del mismo expediente (ej. 542↔556 MARIA EUGENIA RIBEROS; 529↔519 ELVER ALBEIRO ALVARADO; 533↔508 Alix Piratoa Reyes; 492↔525 YINETH RUBIELA SANTOS). **Duplicación sistémica** — al menos 4 pares visibles solo en el top 30. Proyección conservadora: **15-25 pares duplicados** en los 85 casos de B1.

---

## Query C — Docs SOSPECHOSO por caso (81 casos, 269 docs totales)

### Top 15 casos con mayor acumulación:

| ID  | SUSP | NO_PERTENECE | REVISAR | Total docs | Folder                                              |
|-----|------|--------------|---------|-----------|-----------------------------------------------------|
| 184 | 32   | 9            | 3       | 91        | 2026-00014 BLANCA AURORA NIÑO MATEUS                |
| 131 | 17   | 0            | 0       | 77        | 2025-00066 LUIS HUMBERTO MALDONADO MÁRQUEZ          |
| 196 | 15   | 11           | 0       | 71        | 2026-00021 CARLOS ALBERTO OSMA CHAPARO              |
| 189 | 14   | 19           | 5       | 75        | 2026-00015 ALFONSO ALVAREZ REYES                    |
| 191 | 10   | 5            | 0       | 23        | 2026-00015 NI 6539 VICTOR MANUEL CABALLERO SIERRA   |
| 206 | 7    | 8            | 0       | 75        | 2026-00032 INGRID TATIANA NIÑO MUÑOZ                |
| 224 | 7    | 1            | 1       | 28        | 2026-00066 y 2026-00067 BISNEY / INGRID SEPULV…     |
| 298 | 7    | 0            | 0       | 33        | 2026-009 JELISSA VIVIANA GALVIS MOGOLLON            |
| 143 | 6    | 10           | 0       | 34        | 2025-00253 ANA MILENA CACUA PABON                   |
| 210 | 6    | 3            | 1       | 44        | 2026-00034 ANGELICA MAYERLY VELASCO MENDEZ          |
| 230 | 6    | 0            | 0       | 16        | 2026-00076 Heyllem Judith Villamizar Fuentes        |
| 286 | 6    | 10           | 0       | 66        | 2026-0053 NATALIA ROA SERRANO                       |
| 409 | 6    | 0            | 0       | 15        | 2026-00059 IVONN JOHANNA SANCHEZ VILLAMIZAR         |
| 173 | 5    | 2            | 0       | 100       | 2026-000026 JUAN CAMILO ORTIZ ORTIZ                 |
| 179 | 5    | 7            | 0       | 35        | 2026-00012 KAROL LUCIANA MENDEZ RINCON              |

**Patrones dominantes observados en la muestra G (131, 184, 196):**

1. **Contratación de cumplimiento**: docs con nombres como "CESION DE CONTRATO A X", "ACTA DE INICIO Y", "ANDRES EDUARDO CABRERA GONGORA 1118301332" — son soportes administrativos del cumplimiento de la orden de tutela, pertenecen al caso pero no lucen como docs judiciales al clasificador. → reclasificar como **ANEXO_ADMINISTRATIVO** (nuevo doc_type).

2. **Tutelas acumuladas**: un solo folder contiene docs de múltiples radicados (ej. 184 mezcla `2026-00014` con `2026-00032-01`). Requiere flag `multi_radicado=True` en cases + desmezcla manual asistida.

3. **Correspondencia administrativa**: cadenas de correos entre dependencias ("RECOMENDACIONES EDILIA TORRES", "Respuesta Rector"). → ANEXO_ADMINISTRATIVO.

**Recomendación**: no borrar los 269 docs — reclasificarlos. Esperado post-fix: **SOSPECHOSO → ≤30** (solo los genuinamente ambiguos).

---

## Query D — Emails últimos 14 días: mismatches subject → caso (21 de 297)

Criterio: extraer `20YY-NNNNN` del subject; comparar con `rad_corto(rad23)` del caso asignado.

### 21 mismatches detectados:

| email_id | subj_rad (detectado) | case_rad (DB) | case_id | Subject (truncado)                                        | Veredicto |
|----------|----------------------|---------------|---------|----------------------------------------------------------|-----------|
| 1342     | 2026-08300           | 2026-00083    | 308     | NOTIFICACIÓN AVOCA…Radicado: 680014009…                  | ⚠️ regex captura `08300` del rad23 largo `68001400902320260008300` — debería ser `2026-00083`. **Falso positivo de mi query**. |
| 1359     | 2026-07600           | 2026-00076    | 491     | RE: NOTIFICACION FALLO TUTELA 68001430300220260007600    | ⚠️ Mismo patrón: 07600 viene del rad23 largo. **Falso positivo**. |
| 1380     | 2026-00115           | 2026-00011    | 244     | contestación tutela 2026-000115                          | 🔴 Subject dice **tutela 2026-000115**, caso es 2026-00011. Matching erróneo (B7). |
| 1394     | 2026-00115           | 2026-00011    | 244     | PARA NOTIFICAR AUTO ADMISORIO DE TUTELA 686794089001 202 | 🔴 Mismo caso que 1380: debería ir a caso 2026-00115. |
| 1417     | 2026-00069           | 2026-00011    | 244     | NOTIFICACION AUTO ADMITE Y VINCULA - ACCION DE TUTELA RA | 🔴 Subject 2026-00069, matcheado a 2026-00011 — B7 confirmado. |
| 1387     | 2026-00025           | 2026-00028    | 267     | RV: Auto Admisorio Acción de tutela – Radicado No. 2026… | ⚠️ 2026-0025 vs 2026-00028 (caso 267 tiene folder "2026-0025") — el matcher eligió por folder, no por rad23. |
| 1402     | 2026-05500           | 2026-00055    | 373     | NOTIFICA AUTO CONCEDE IMPUGNACION…680014009024202        | ⚠️ 05500 es del rad23. **Falso positivo** mío. |
| 1414     | 2026-07600           | 2026-00076    | 491     | NOTIFICACION FALLO TUTELA 68001430300220260007600        | ⚠️ mismo patrón 1359. |
| 1424     | 2026-00083           | 2026-00086    | 385     | INFORME CUMPLIMIENTO FALLO 2026-0083                     | 🔴 Subject dice 2026-0083 (= 2026-00083), caso 385 tiene rad 2026-00086. **Documento en caso equivocado**. |
| 1432     | 2026-06600           | 2026-00066    | 555     | NOTIFICACIÓN FALLO TUTELA 68001400902420260006600        | ⚠️ 06600 del rad23. **Falso positivo**. |
| 1437     | 2023-26700           | 2023-00267    | 413     | 68001333300820230026700 Respuesta…                       | ⚠️ 26700 del rad23. **Falso positivo**. |
| 1448     | 2026-07400           | 2026-00074    | 228     | Se le ha compartido información de proceso judicial - 68 | ⚠️ 07400 del rad23. **Falso positivo**. |
| 1466     | 2026-01201           | 2026-00012    | 182     | NOTIFICACIÓN SENTENCIA SEGUNDA INSTANCIA RDO. 6816740890 | ⚠️ 01201 es sufijo del rad23 `…2026-00012-01`. **Falso positivo**. |
| 1468     | 2026-00044           | 2026-00066    | 224     | RESPUESTA REQUERIMIENTO 2026-0044 /2026-0066             | ⚠️ Subject menciona 2 radicados (acumuladas). **Tolerable**. |
| 1480     | 2026-07400           | 2026-00074    | 228     | Notifica Auto Avoca Accion Tutela 6868931890012026000740 | ⚠️ 07400 del rad23. **Falso positivo**. |
| 1489     | 2026-00045           | 2026-00042    | 492     | RESPUESTA ACCIÓN DE TUTELA 2026-0045                     | 🔴 Subject 2026-0045, caso con rad 2026-00042 — **mismatch real**. Caso 492 es YINETH RUBIELA SANTOS (rad 00042), subject parece ser de otro expediente. |
| 1120     | 2026-00045           | 2026-00042    | 492     | OFICIO 215 NOTIFICA AUTO ADMITE…                         | 🔴 Mismo patrón 1489 — posible email mal vinculado. |
| 1135     | 2026-00159           | 2025-00159    | 390     | RV: NOTIFICACIÓN SENTENCIA TUTELA 2026-159               | ⚠️ Subject 2026-159, caso 2025-00159 — **año distinto**. Posible duplicado inter-año o typo. |
| 385      | 2026-00083           | 2026-00086    | 385     | Notificación fallo de tutela 681904089001-2026-00083-00  | 🔴 Doble mismatch (mismo que 1424). |
| 408      | 2026-03200           | 2026-00032    | 208     | Radicado de tutela. 680013333014-2026-0003200…           | ⚠️ 03200 = parte del rad23 largo. Podría ser falso positivo. |
| 409      | 2026-05500           | 2026-00055    | 373     | NOTIFICA FALLO TUTELA 68001400902420260005500            | ⚠️ 05500 del rad23. **Falso positivo**. |

**Análisis de la query D:**
- 11/21 son **falsos positivos** de mi regex (captura parte del rad23 largo en lugar del rad corto del subject). Debería mi query excluir strings de 20+ dígitos contiguos.
- **10/21 son mismatches reales** (B7 confirmado): 1380, 1394, 1417, 1387, 1424, 1468, 1489, 1120, 1135, 385.
- Prevalencia estimada: **~3-5% de emails son mal vinculados** a caso ajeno.

---

## Matriz final de remediación priorizada

| Prio | Bug/Fix | Casos afectados | Impacto usuario | Esfuerzo |
|------|---------|-----------------|-----------------|----------|
| **P0** | F1 + F2 (regex RAD_LABEL + priorizar rad23) | 85 casos (B1+B2) | **ALTO** — folders malos en 22% de casos | 1-2h |
| **P0** | F3 + F4 (prompt + post-validator radicados ajenos) | 11 casos contaminados | **ALTO** — obs mentirosas | 1h |
| **P0** | F5 (rename auto post-extracción) | 6 folders PENDIENTE + 85 forest-like | **ALTO** — afecta navegación | 1h |
| **P1** | F9 (nuevo) B13 reconsolidación | ~15-25 pares duplicados | **ALTO** — duplicación sistémica | 1.5h |
| **P1** | F6 (forwarded anidados) | ≥1 confirmado, probable docenas | MEDIO | 1h |
| **P1** | F7 (matching por juzgado) | 10+ emails/14d, prevalencia ~3% | MEDIO | 1h |
| **P2** | F8 (pre-COMPLETO) | 18 casos | MEDIO | 30min |
| **P2** | Reclasificación ANEXO_ADMINISTRATIVO | 81 casos / 269 docs | MEDIO | 2h |
| **P3** | UX U1-U5 | — | BAJO-MEDIO | 1h |

**Tiempo total estimado Fase 2+3+4:** 8-11 horas (vs 5-7h del plan original, por ajuste B1 y adición B13).

---

## Criterios de éxito actualizados (post-Fase 1)

Al final de Fase 5, debe cumplirse:

- `SELECT COUNT(*) FROM cases WHERE folder_name LIKE '%PENDIENTE%'` → **0** (todos renombrados)
- **NEW**: Query B (folder rad ≠ rad23) → **≤5** (solo tutelas acumuladas legítimas)
- Query A (obs contaminadas) → **≤3** (solo acumuladas legítimas)
- `COMPLETO sin rad23` → **0** (F8 los pasa a REVISION)
- **NEW**: Pares duplicados B13 → **0** (F9 los reconsolida)
- Docs SOSPECHOSO → **≤30** (post-reclasificación)
- `/api/extraction/audit total_problemas` → **<20**
- Email mismatches subject→case 14d → **≤1%**
- Replay email 2026-00057 → matchea caso canónico 2026-00057 LIBIA INES PATIÑO ROMÁN
- 8 tests regresión B1-B8 + 1 test B13 → verde


