# V9 Fase 2 — Plan de extracción de campos semánticos

> Notas para la fase posterior a la ingesta. Cuando llegue el momento, retomar este doc.

## Campos REGEX (ya cubiertos en `backend/v9/regex_pass.py`)

Cobertura sólida con regex CUP + cascada:
- `radicado_23_digitos`
- `radicado_forest`
- `accionante` (parcial — fallback a `_derive_accionante_from_folder`)
- `juzgado`, `ciudad`
- `fecha_ingreso`, `fecha_fallo_1st`, `fecha_apertura_incidente`
- `tipo_actuacion` (TUTELA / INCIDENTE)
- `impugnacion` (SI / NO heurística)
- `incidente`, `incidente_2`, `incidente_3` (cronológico)
- `abogado_responsable` (footer DOCX)
- jerarquía SED `direccion / grupo / equipo` (derivada de catálogo)

## Campos SEMÁNTICOS (próxima fase — requieren regex + Qwen3-4B local como fallback)

Cuando trabajemos cada uno: el usuario aporta patrones/pistas de dónde encontrar la info.

| Campo | Donde aparece típicamente | Estrategia v9.2 |
|---|---|---|
| `accionados` | ✅ HECHO. Auto admisorio header "ACCIONADO:" / "en contra de" / default GOB+SEC | `field_extractor.extract_accionados_for_case` |
| `vinculados` | ✅ HECHO. Auto admisorio "se vincula a..." | `field_extractor.extract_vinculados_for_case` |
| `derecho_vulnerado` | ✅ HECHO. Auto admisorio / demanda / sentencia: "derechos fundamentales a la X, Y y Z" | Ancla + tags → vocab controlado (`DERECHO_VOCAB`) + LLM fallback. `field_extractor.extract_derecho_vulnerado_for_case` |
| `juzgado` (1ra) | ✅ HECHO. Remitente Rama Judicial (cendoj/notificacionesrj) + header/sello del auto/sentencia | `field_extractor.extract_juzgado_for_case` → forma normalizada `JUZGADO NN ... DE MUNICIPIO (SANTANDER)` |
| `juzgado_2nd` | ✅ HECHO. Doc/email de 2da instancia → si no, DERIVADO del mapa judicial canónico | `field_extractor.extract_juzgado_2nd_for_case` + `legal_schema.derivar_juzgado_segunda` |
| `ciudad` | ✅ HECHO. = municipio del juzgado de 1ra (≈ lugar de los hechos). Derivado del nombre del juzgado ya extraído (conserva tildes); fallback auto/demanda | `field_extractor.extract_ciudad_for_case` |
| `fecha_ingreso` | ✅ HECHO. = fecha del auto admisorio (texto del auto + recap en sentencia/notif + email auto-admite; cota año rad23 ±1) | `field_extractor.extract_fecha_ingreso_for_case` |
| `asunto` | ✅ HECHO. = vocab controlado SED (`legal_schema.SED_TEMA_MAPPING` / `clasificar_sed_tematica`); keyword ~89% + LLM fallback | `field_extractor.extract_asunto_for_case` |
| `pretensiones` | ✅ HECHO. Transcripción literal de la sección PRETENSIONES/SOLICITO de la demanda — **~62% por regex (245/397, techo real)**; el resto NO tiene las pretensiones en forma extractable (demandas truncadas a 30k / RESPUESTAS narrativa SED / sentencias que parafrasean). LLM como **localizador** (no transcriptor) para el flujo diario | `field_extractor.extract_pretensiones_for_case` + `_llm_locate_pretensiones` |
| `observaciones` | Texto libre — manual o derivado de respuesta | Manual / LLM resumir |
| `sentido_fallo_1st` | Sentencia zona RESUELVE | Regex (CONCEDE / NIEGA / IMPROCEDENTE / HECHO SUPERADO) + LLM cuando regex falla |
| `sentido_fallo_2nd` | Sentencia 2da zona RESUELVE | Regex (CONFIRMA / REVOCA / MODIFICA) + LLM |
| `decision_incidente`, `_2`, `_3` | Auto del incidente "RESUELVE" | Regex (SANCIONA / NO SANCIONA / NIEGA APERTURA / CIERRA) + LLM |
| `responsable_desacato` | Texto del incidente | LLM extractivo (nombre del funcionario) |
| `quien_impugno` | Doc de impugnación | Regex (ACCIONANTE/ACCIONADO/AMBOS) + LLM |
| `forest_impugnacion` | ✅ HECHO. Email/respuesta de impugnación | `field_extractor.extract_forest_for_case` (segundo retorno) |
| `categoria_tematica` | Inferida del derecho_vulnerado + accionante + asunto (`legal_schema.SED_TEMA_MAPPING`) | Clasificador semántico |
| `oficina_responsable` | ✅ HECHO. = Dirección L1 SED derivada del `asunto` (`SED_TEMA_MAPPING` → L1) | `field_extractor.extract_oficina_responsable_for_case` — 389/397 |
| `abogado_responsable` | ✅ HECHO. footer "Proyectó:" del DOCX de respuesta → roster Grupo Jurídico (`grupo_juridico_abogados.json`, 15+correos) + catálogo (17) | `field_extractor.extract_abogado_responsable_for_case` — 194/397 (los con respuesta) |

## Vocabulario controlado

- ✅ `derecho_vulnerado`: EDUCACION / SALUD / PETICION / DEBIDO_PROCESO / VIDA / SEGURIDAD_SOCIAL / MINIMO_VITAL / TRABAJO / IGUALDAD / INTIMIDAD / HABEAS_DATA / OTRO (+ default SIN_DETERMINAR). Multi-derecho → concatenar "A - B - C". Ver `DERECHO_VOCAB`.

El usuario debe aportar la lista cerrada para:
- `categoria_tematica`: ¿lista de la SED?
- `sentido_fallo_1st`: CONCEDE / CONCEDE_PARCIAL / NIEGA / IMPROCEDENTE / HECHO_SUPERADO / CARENCIA_OBJETO
- `sentido_fallo_2nd`: CONFIRMA / CONFIRMA_PARCIAL / REVOCA / MODIFICA / INHIBIR
- `decision_incidente`: SANCIONA / NO_SANCIONA / NIEGA_APERTURA / CIERRA / EN_TRAMITE
- `quien_impugno`: ACCIONANTE / ACCIONADO / AMBOS

## Fase 3 — Agente conversacional (después de extracción)

**Stack propuesto**:
- Retrieval: TF-IDF existente (`backend/ml/embeddings/tfidf_index.py`)
- LLM: Qwen3-4B local (ya en `data/lora-models/`)
- Patrón: RAG simple — buscar Document por filtro SQL, pasar `extracted_text` al LLM con prompt focal

**Casos de uso típicos del operador**:
- "¿Qué dijo el fallo de primera instancia de la tutela de Gambita?"
  → SQL: SENTENCIA_1RA del case con folder LIKE '%GAMBITA%' → resumir con LLM
- "¿Cuántas tutelas tiene Marcela Mondragón?"
  → SQL puro, no necesita LLM
- "¿Qué órdenes dio el juez en el caso #142?"
  → SQL al case + extracted_text de SENTENCIA_1RA → LLM extractivo

## Cuándo evaluar VLM (mPLUG-DocOwl / GLM-OCR)

Solo si emerge alguna de estas necesidades reales:
- Preguntas sobre info **en imagen** (sellos rotados, firmas, gráficos)
- >20% del corpus pasa a ser PDFs escaneados sin OCR
- Necesidad de extraer **tablas complejas** del cuerpo del fallo

Mientras tanto: NO meter VLM. Es ruta al mutante v8.

## Referencias para evaluar más adelante

- mPLUG-DocOwl 1.5 (x-plug/mplug-docowl)
- GLM-OCR (zai-org/GLM-OCR)
- Survey paper: comparación métodos document LLMs (datasets DocVQA, TableBank, etc.)
