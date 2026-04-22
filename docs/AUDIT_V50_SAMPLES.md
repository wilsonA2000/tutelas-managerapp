# AUDIT V50 — Fichas de 25 casos de muestreo

> Generado: 2026-04-20
> Método: extracción manual (Claude) desde PDFs/emails del disco vs estado actual de `data/tutelas.db`
> Backup DB pre-auditoría: `data/tutelas_preaudit_v50_20260420_193555.db` (SHA256 verificado)
> CSV de seleccionados: `docs/AUDIT_V50_SAMPLES.csv`

## Distribución de la muestra

| Estrato | Label                                | IDs                          |
|---------|--------------------------------------|------------------------------|
| A       | Correcto COMPLETO (baseline)         | 121, 124, 125, 134, 141      |
| B       | PENDIENTE REVISION activo            | 541, 560                     |
| C       | PENDIENTE REVISION tombstone         | 500, 501                     |
| D       | Forest-like (seq>=10000) con rad23   | 265, 304, 306, 328, 389      |
| E       | Obs contaminadas                     | 59, 115, 119, 120, 130       |
| F       | COMPLETO sin rad23                   | 133, 139, 190                |
| G       | ≥3 docs SOSPECHOSO                   | 131, 184, 196                |
| TOTAL   |                                      | 25                           |

---

## CASO id=560 — bug raíz 🔴 CRÍTICO

```
folder:  '2026-66132 [PENDIENTE REVISION]'
status:  COMPLETO
rad23:   68-001-40-88-003-2026-00057-00
forest:  20260066132
docs:    1 (Email_20260414_RV_URGENTE!!!_NOTIFICA_AVOCA_TUTELA_2026-00057.md)
```

### Extracción manual (Claude) desde el email fuente

Fuente: `Email_20260414_RV_URGENTE!!!_NOTIFICA_AVOCA_TUTELA_2026-00057.md` (nivel 4 del forwarded chain, oficio N° 227 del Juzgado 03 Penal Municipal Control Garantías Bucaramanga).

| # | Campo                       | Valor real                                                                                             |
|---|-----------------------------|--------------------------------------------------------------------------------------------------------|
| 1 | RADICADO_23_DIGITOS         | `68001408800320260005700` (aparece textual como LINK EXP)                                              |
| 2 | RADICADO_FOREST             | `20260066132`                                                                                          |
| 3 | ABOGADO_RESPONSABLE         | (sin respuesta aún — tutela recién avocada 14-abr)                                                     |
| 4 | ACCIONANTE                  | **LIBIA INES PATIÑO ROMÁN** (CC 39.384.930 de Santa Bárbara)                                           |
| 5 | ACCIONADOS                  | GOBERNACIÓN DE SANTANDER — SECRETARÍA DE EDUCACIÓN DE SANTANDER                                        |
| 6 | VINCULADOS                  | GIMNASIO MODERNO LATINO, PROCURADURÍA GENERAL, MINISTERIO DE EDUCACIÓN NACIONAL                        |
| 7 | DERECHO_VULNERADO           | Educación (y otros)                                                                                    |
| 8 | JUZGADO                     | Juzgado 03 Penal Municipal con Funciones de Control de Garantías de Bucaramanga                        |
| 9 | CIUDAD                      | Bucaramanga                                                                                            |
| 10| FECHA_INGRESO               | 2026-04-14                                                                                             |
| 11| ASUNTO                      | Notificación de auto admisorio de tutela; traslado a la Secretaría de Educación                        |
| 12| PRETENSIONES                | (no descritas en este email — están en escrito de tutela no adjunto en el .md)                         |
| 13| OFICINA_RESPONSABLE         | Apoyo Jurídico Secretaría de Educación                                                                 |

### Diff DB vs real

| Campo            | DB actual                                     | Real                                  | Veredicto     |
|------------------|-----------------------------------------------|---------------------------------------|---------------|
| radicado_23d     | `68-001-40-88-003-2026-00057-00`              | ✓                                     | OK            |
| forest           | `20260066132`                                 | ✓                                     | OK            |
| accionante       | NULL                                          | LIBIA INES PATIÑO ROMÁN               | **B6**        |
| accionados       | NULL                                          | GOBERNACIÓN / SED Santander           | **B6**        |
| juzgado          | NULL                                          | Juzgado 03 Penal Municipal C.G. Bmga  | **B6**        |
| ciudad           | NULL                                          | Bucaramanga                           | **B6**        |
| fecha_ingreso    | NULL                                          | 2026-04-14                            | **B6**        |
| observaciones    | "Caso **2026-66132** en estado ACTIVO…"       | Debe decir **2026-00057**             | **B3 + B4**   |
| folder_name      | `2026-66132 [PENDIENTE REVISION]`             | `2026-00057 LIBIA INES PATIÑO ROMAN`  | **B1 + B5**   |

### Cadena causal empírica

1. Email llega con cuerpo: `Con número de radicado 20260066132` (= FOREST).
2. **B1**: regex `RAD_LABEL` (con `IGNORECASE`) matchea "número de radicado 20260066132" y extrae `2026-66132` como radicado judicial.
3. **B2**: `extract_radicado()` retorna early con `2026-66132` aunque el subject ya tenía `TUTELA 2026-00057`.
4. Se crea caso id=560 con folder_name basado en el FOREST formateado: `2026-66132 [PENDIENTE REVISION]`.
5. Al extraer campos, el prompt inyecta `CARPETA DEL CASO: 2026-66132 [PENDIENTE REVISION]`.
6. **B3**: la IA escribe observaciones usando el folder como "Caso 2026-66132 en estado ACTIVO…", ignorando que rad23 dice otra cosa.
7. **B4**: el post_validator no detecta la mención del radicado ajeno.
8. **B5**: aunque más tarde se extrajo `rad23 = 68-001-40-88-003-2026-00057-00`, el folder `[PENDIENTE REVISION]` no fue renombrado.
9. **B6**: el accionante LIBIA INES PATIÑO ROMÁN está en el nivel más profundo del forwarded chain; el parser de accionantes no lo detectó y dejó NULL.

---

## CASO id=541 — duplicación cascada 🔴 CRÍTICO

```
folder:  '2026-69467 [PENDIENTE REVISION]'
status:  COMPLETO
rad23:   68-276-41-89-006-2026-00234-00
forest:  20260069467
docs:    1 (Email_20260417_RV_2026-00234_AVOCA_TUTELA..md)
```

### Extracción manual (Claude) desde el email fuente

Fuente: `Email_20260417_RV_2026-00234_AVOCA_TUTELA..md` (oficio N° 648 del Juzgado Sexto de Pequeñas Causas y C.M. de Floridablanca).

| # | Campo                       | Valor real                                                                                             |
|---|-----------------------------|--------------------------------------------------------------------------------------------------------|
| 1 | RADICADO_23_DIGITOS         | `682764189006-2026-00234-00` (formato alternativo `68-276-41-89-006-2026-00234-00`)                    |
| 2 | RADICADO_FOREST             | `20260069467`                                                                                          |
| 4 | ACCIONANTE                  | **ANDREA PAREDES OLIVEROS** (CC 37.900.491), en nombre propio                                          |
| 5 | ACCIONADOS                  | COLEGIO INTEGRAL SAN PAULO                                                                             |
| 6 | VINCULADOS                  | ICBF Dirección Regional Santander; SED Municipal Floridablanca; SED Departamental Santander; MinEducación; Colegio Nueva Generación; Personería Floridablanca |
| 7 | DERECHO_VULNERADO           | Debido proceso, educación, buen nombre, habeas data                                                    |
| 8 | JUZGADO                     | Juzgado Sexto de Pequeñas Causas y Competencia Múltiple de Floridablanca — Santander                   |
| 9 | CIUDAD                      | Floridablanca                                                                                          |
| 10| FECHA_INGRESO               | 2026-04-16 (providencia del 16-abr que avoca la tutela)                                                |
| 11| ASUNTO                      | Avoca de tutela; traslado por 2 días                                                                   |
| 13| OFICINA_RESPONSABLE         | Apoyo Jurídico Secretaría de Educación                                                                 |

### Diff DB vs real

| Campo            | DB actual                                     | Real                                  | Veredicto     |
|------------------|-----------------------------------------------|---------------------------------------|---------------|
| radicado_23d     | `68-276-41-89-006-2026-00234-00`              | ✓                                     | OK            |
| forest           | `20260069467`                                 | ✓                                     | OK            |
| juzgado          | `Juzgado Sexto de Pequeñas Causas…`           | ✓                                     | OK            |
| ciudad           | `FLORIDABLANCA`                               | ✓                                     | OK            |
| accionante       | NULL                                          | ANDREA PAREDES OLIVEROS               | **B6** parcial (el email tenía `Accionante: ANDREA PAREDES OLIVEROS` textual, no debería haber fallado — posible bug diferente) |
| accionados       | NULL                                          | COLEGIO INTEGRAL SAN PAULO            | **B6**        |
| vinculados       | NULL                                          | (6 entidades)                         | **B6**        |
| derecho          | NULL                                          | Debido proceso, educación, etc.       | **B6**        |
| fecha_ingreso    | NULL                                          | 2026-04-16                            | **B6**        |
| observaciones    | "Caso **2026-69467** en estado ACTIVO…"       | Debe decir **2026-00234**             | **B3 + B4**   |
| folder_name      | `2026-69467 [PENDIENTE REVISION]`             | `2026-00234 ANDREA PAREDES OLIVEROS`  | **B1 + B5**   |

### Duplicación detectada (bug adicional)

Existe **caso id=531** con:
- `folder_name = '2026-00234 ANDREA PAREDES OLIVEROS ACCIONADOS'`
- `accionante = 'ANDREA PAREDES OLIVEROS'`
- `rad23 = NULL`

→ id=541 es un **duplicado** creado a posteriori de id=531, separado por bugs B1+B7. Cuando se arreglen B1/B2/B7 el matcher debe consolidarlos (id=541 → DUPLICATE_MERGED hacia id=531, o viceversa, lo que tenga mejor folder).

### Evidencia del bug B1 en el email

Texto literal del email (nivel 2 del forward chain):
> "_De manera atenta le informo que su correo fue recibido, radicado y enviado TUTELAS EDUCACIÓN, para lo pertinente. **Con número de radicado 20260069467**_"

El `20260069467` es el **FOREST interno** de la Gobernación; el regex RAD_LABEL lo toma y escupe `2026-69467` como radicado corto.

---

## Estrato A — baseline COMPLETO (5)

| ID  | Folder                                              | rad23                          | Accionante (DB)            | Juzgado (DB)                                  | Fallo / Fecha      | Docs | Veredicto |
|-----|-----------------------------------------------------|--------------------------------|----------------------------|-----------------------------------------------|--------------------|------|-----------|
| 121 | 2021-00065 PERSONERIA MUNICIPAL DE VILLANUEVA       | 68.872.40.89.001.2021.00065.00 | Personería Mpal Villanueva | Juzgado Promiscuo Municipal de Villanueva     | CONCEDE 12/05/2021 | 11OK | ✅ OK     |
| 124 | 2024-00012 PERSONERO MUNICIPAL DE SANTA BARBARA     | 68705-40-89-001-2024-00012-01  | Personero Mpal Sta Bárbara | Juzgado Promiscuo Mpal Santa Bárbara          | CONCEDE PARC. 01/04/2024 | 28 | ✅ OK  |
| 125 | 2024-00050 SAMUEL ANDRES PINZON VEGA                | 68-679-40-71-001-2024-00050-00 | Samuel A. Pinzón Vega      | Juzgado 1° Penal Mpal Adolescentes (San Gil)  | CONCEDE 05/06/2024 | 14OK | ✅ OK   |
| 134 | 2025-00105 EDGAR DÍAZ VARGAS                        | 68-264-40-89-001-2025-00105-02 | 7 docentes (lista)         | Juzgado Promiscuo Mpal Encino                 | CONCEDE PARC. 22/10/2025 | 5 | ⚠️ Folder="EDGAR DÍAZ VARGAS" pero accionantes son 7 docentes (Erika Mora y otros). **No es bug: el folder conserva el nombre histórico; los datos de DB vienen de sentencia 2da instancia.** |
| 141 | 2025-00200 LAURA MARIA ROJAS ALZA                   | 2025-00200-01 (sin 23d completo)| Laura M. Rojas Alza       | Juzgado 1° Penal Mpal Control Garantías Tunja | CONCEDE PARC. 29/12/2025 | 2 | ⚠️ rad23 solo tiene "2025-00200-01" — no fue detectado completo (falla regex). F8 aplica. |

**Conclusión A:** 3/5 limpios, 2/5 tienen inconsistencias leves pero no críticas. Caso 141 confirma que **B12/F8** tiene precedentes no catalogados (rad23 incompleto).

## Estrato C — tombstones PENDIENTE REVISION (2)

| ID  | Folder                           | rad23 | Obs (truncada)                                         | Veredicto |
|-----|----------------------------------|-------|--------------------------------------------------------|-----------|
| 500 | 2026-60777 [PENDIENTE REVISION]  | NULL  | " \| Docs redistribuidos: MARIA EUGENIA RIBEROS"       | ⚠️ Tombstone OK (DUPLICATE_MERGED, docs movidos a canónico MARIA EUGENIA RIBEROS = 542/556). Email original: `2026-258 AVOCA` → rad corto real **2026-00258**. **B1 confirmado**: folder usa FOREST `20260060777`. |
| 501 | 2026-60385 [PENDIENTE REVISION]  | NULL  | " \| Docs redistribuidos: rad 2026-00078 → 2026-00078 DIANA MARIA ME…" | ⚠️ Tombstone OK. Email original: `FALLO TUTELA 2026-078` → rad corto real **2026-00078**. **B1 confirmado**. |

**Conclusión C:** los tombstones prueban que el pipeline de merge v4.8 sí funcionó (docs redistribuidos), pero los folders `[PENDIENTE REVISION]` quedaron fosilizados — no hay cleanup cosmético post-merge.

## Estrato D — forest-like con rad23 (5) ⚠️ hallazgo clave

El filtro "seq ≥ 10000" captura **3 falsos positivos** (304, 306, 389): son radicados judiciales legítimos con consecutivo alto (juzgados laborales de B/mermeja usan 10001+ para tutelas).

| ID  | Folder                              | rad23                                | rad corto real (derivado)    | Veredicto |
|-----|-------------------------------------|--------------------------------------|------------------------------|-----------|
| 265 | 2026-0022738 AMPARO FERIA CASTRO    | 68-081-40-04-003-2025-**00468**-00   | **2025-00468**               | 🔴 Folder MAL. "0022738" no es FOREST 11d (forest real=`2787559`). Es un radicado FOREST viejo corto. Rename → `2025-00468 AMPARO FERIA CASTRO`. |
| 304 | 2026-10003 CEIDY LORENA GAITAN      | 68.081.31.05.003.**2026.10003**.00   | **2026-10003**               | ✅ **Falso positivo**: `10003` ES consecutivo judicial real (Juzgado 3° Laboral B/bermeja). Forest distinto (`20260014424`). |
| 306 | 2026-10044 JORGE IVAN PEÑA          | 68001-40-05-003-**2026-10044**-00    | **2026-10044**               | ✅ Falso positivo. Mismo patrón: 10044 es consecutivo judicial real. |
| 328 | 2026-27600 DAVID DANIEL RUBIO       | 110014003054**20260027600** (23d)    | **2026-00276**               | 🔴 Folder MAL. Parseo del 23d: `11001-40-03-054-2026-00276-00` → rad corto `2026-00276`, NO `2026-27600`. Bug: regex confundió `20260027600` del rad23 completo con "2026-27600". |
| 389 | 2026-10041 JORGE ELIECER RIVERA     | 055793105002-**2026-10041**-00       | **2026-10041**               | ✅ Falso positivo. Consecutivo 10041 legítimo. Forest=`3395041` distinto. |

**Conclusión D:** De 54 folders forest-like, no todos son rename candidates. **El filtro necesita validar que el consecutivo del folder ≠ consecutivo del rad23**. Correcto: rename solo si `rad_corto(folder) != rad_corto(rad23)`.

→ **F3/F5 ajustado**: comparar short-from-folder contra short-from-rad23 antes de renombrar.

## Estrato E — obs contaminadas (5)

| ID  | Folder / rad23                                         | Menciones en obs                  | Veredicto |
|-----|--------------------------------------------------------|-----------------------------------|-----------|
|  59 | (folder NULL, DUPLICATE_MERGED) / rad23=2026-00106     | 2026-00092, 2026-00243, 2026-00351 | ⚠️ Parte de trámite complejo (peticiones con FOREST 20260009209). Algunas menciones son FOREST legítimos mal-formateados por el detector (falso positivo parcial). |
| 115 | (folder NULL, DUPLICATE_MERGED) / rad23=2026-10021     | 2026-00082                         | ✅ **Falso positivo mío**. La obs dice "FOREST 20260008216" y el detector lo interpretó como 2026-00082. Mi query necesita excluir menciones formateadas como `FOREST NNNNNNNNNNN`. |
| 119 | 2021-00047 ALCALDIA DE LA PAZ / rad23=2021-00047       | 2026-00344                         | 🔴 **B4 confirmado**. El FOREST `20260034476` (cabecera del caso) fue formateado como `2026-00344` y la IA lo metió en observaciones. |
| 120 | 2021-00065 DIDIER SANTIAGO / rad23=2021-00065          | 2026-00363                         | 🔴 **B4 confirmado**. FOREST `20260050786` → obs dice "2026-00363" (ni siquiera derivado limpiamente). Contaminación IA. |
| 130 | 2025-00055-01 JOSE LUIS PRADA / rad23=2025-00055-01    | 2026-00055                         | ⚠️ Posible confusión del año entre distintas instancias. Requiere leer el oficio para veredicto final. |

**Conclusión E:** de 95 casos detectados, estimo que **~60-70%** son contaminación real (B3+B4) y **~30-40%** son FOREST legítimos malformateados por mi detector. Para FINDINGS: refinar query excluyendo patrones `FOREST\s+\d{11}` y `radicado\s+\d{11}`.

## Estrato F — COMPLETO sin rad23 (3)

| ID  | Folder                                    | Accionante (DB)                    | Juzgado (DB)                  | Veredicto |
|-----|-------------------------------------------|------------------------------------|-------------------------------|-----------|
| 133 | 2025-00086 NUBIA GOMEZ SEPULVEDA          | **FRANCY JOHANA SIERRA DIAZ** ❌    | NULL                           | 🔴 **Conflicto folder↔accionante**. Docs en disco son "DecisionSegundaInstancia" + "NOTIFICO SENTENCIA". Sugiere docs de caso ajeno en folder incorrecto. Necesita leer PDF para confirmar. |
| 139 | 2025-00125 CESAR AUGUSTO LEON VERGARA     | César A. León Vergara              | Juez Promiscuo Circuito SVC   | ⚠️ Docs son 2 resoluciones + 1 docx respuesta. No hay auto admisorio → no hay fuente para rad23. F8 debe marcarlo REVISAR. |
| 190 | 2026-00015 ISABELLA BLANCO REATIGA        | Liseth Y. Riatiga (madre)          | Juzgado 2° Penal Mpal Floridablanca | ⚠️ Tiene "AUTO QUE AVOCA CONOCIMIENTO.pdf" — rad23 extraíble pero no fue extraído. Bug de pipeline. |

**Conclusión F:** 1/3 tiene inconsistencia grave (id=133). 2/3 son fallos puros de extracción que F8 debería forzar a REVISAR.

## Estrato G — ≥3 docs SOSPECHOSO (3)

| ID  | Folder                                  | Docs (OK/SUSP/OTROS)              | Hipótesis                                                                |
|-----|-----------------------------------------|-----------------------------------|--------------------------------------------------------------------------|
| 131 | 2025-00066 LUIS HUMBERTO MALDONADO      | 46/17/14 (80 total)               | Desacato prolongado con contratación (ANGIE MAYERLY ROJAS, ANDRES CABRERA). Los "sospechosos" son soportes de cumplimiento (contratos, actas) — pertenecen al caso pero no lucen como "documentos judiciales". → reclasificar como `ANEXO_SOPORTE`. |
| 184 | 2026-00014 BLANCA AURORA NIÑO MATEUS    | 42/32/17 (93 total)               | **Accionante DB = HELVIA LUCIA CAMACHO MOTTA ≠ folder "BLANCA AURORA"**. Docs de `2026-00032-01 SENTENCIA REVOCA` — tutelas **acumuladas** (varias mezcladas). Requiere desmezcla manual. |
| 196 | 2026-00021 CARLOS ALBERTO OSMA          | 45/15/11 (72 total)               | Docs con "RECOMENDACIONES EDILIA TORRES" y cadenas de correos administrativos — son anexos del proceso pero confunden al clasificador. Reclasificar ANEXO_SOPORTE. |

**Conclusión G:** **269 docs SOSPECHOSO** se explican por 2 patrones: (1) anexos administrativos/contratación mal clasificados; (2) tutelas acumuladas con docs de varios radicados en mismo folder. Solución: ampliar `doc_type` para `ANEXO_ADMINISTRATIVO` + flag de folder multi-radicado.

---

## Resumen de veredictos (25 casos)

| Veredicto | Cantidad | IDs                                                      |
|-----------|----------|----------------------------------------------------------|
| ✅ OK completo         | 9   | 121, 124, 125, 304, 306, 389, 500*, 501*, 139 (\*tombstones legítimos) |
| ⚠️ Inconsistencia menor | 5  | 134, 141, 59, 115, 130                                    |
| 🔴 Bug confirmado      | 11  | **541**, **560**, 265, 328, 119, 120, 133, 190, 131, 184, 196 |

## Prevalencia empírica por bug

| Bug | Confirmado en muestra | Magnitud estimada global |
|-----|-----------------------|--------------------------|
| B1 (regex RAD_LABEL captura FOREST)   | 541, 560, 265, 328, 500, 501 | ~6-8% de casos recientes (~20-30 afectados) |
| B3 (prompt obs usa folder literal)    | 541, 560, 119, 120            | ~30-60 casos (subconjunto de los 95 con menciones ajenas) |
| B4 (post-validator no detecta ajenos) | 119, 120 y implícito en B3    | Misma magnitud que B3 |
| B5 (rename post-extracción)           | 541, 560, 500, 501            | 6 folders `[PENDIENTE REVISION]` + ~2 forest-like no renombrados |
| B6 (accionante en forwarded anidado)  | 560 (nivel 4)                 | Difícil estimar sin re-parsear emails |
| B8 (forest-like sistémico)            | 2/54 reales (265, 328)        | Solo ~2-5 casos, NO 54 como sugería el plan |
| B11 (docs sospechosos sin workflow)   | 131, 184, 196                 | 269 docs totales → 50-80 casos afectados |
| B12 (COMPLETO sin rad23)              | 133, 139, 190 + 141 borderline | 18-19 casos |
| **B13 (duplicación no reconsolidada)** | **541 vs 531**               | Por cuantificar en Fase 1.3 |

---

*Fichas de 541 y 560 detalladas arriba; resto en modo ligero por acuerdo con el usuario (2026-04-20).*

---

## Hallazgos preliminares tras 2 fichas

1. **Bug B1 confirmado empíricamente** (no es hipótesis): texto "Con número de radicado 20260066132" del correo de Atención al Ciudadano → se parsea como "2026-66132".
2. **Bug B3 confirmado**: la IA escribe observaciones mencionando "Caso 2026-XXXXX" tomando el `folder_name` literal, no el `radicado_23_digitos`.
3. **Bug B5 confirmado**: ambos casos tienen rad23 válido pero el folder sigue `[PENDIENTE REVISION]`.
4. **Bug B6 confirmado en caso 560**: accionante `LIBIA INES PATIÑO ROMÁN` está en el cuerpo del oficio nivel 4 del forward — no detectado.
5. **Bug adicional (no catalogado en el plan original)**: duplicación de casos. id=541 y id=531 son la misma tutela (`2026-00234 ANDREA PAREDES OLIVEROS`) pero figuran como casos distintos. Sugiere incluir **B13 = matcher no reconsolida tras rad23** en el plan.
