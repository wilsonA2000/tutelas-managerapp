# Prompt para retomar — Proyecto Tutelas v9 (Fase 2: extracción de campos)

> Copiar/pegar este bloque al iniciar una nueva sesión de Claude Code.

---

## CONTEXTO DEL PROYECTO

Trabajo en `/home/wilsonarguello/Documentos/GOBERNACION DE SANTANDER/TUTELAS 2026/tutelas-app`.
Es una plataforma para gestionar acciones de tutela de la Secretaría de Educación de Santander.

**v9** es una reescritura desde cero que reemplazó el "mutante v8" (3 pipelines paralelos, 13 sitios LLM, contradicciones). Filosofía: pipeline plano, 1 autoridad por campo, regex determinístico primero, LLM solo donde aporta. Ver `CLAUDE.md` sección v9.

---

## ✅ MODERNIZACIÓN COMPLETA (2026-05-11) — Fases 0-8

Se cerró el programa de modernización (plan en `~/.claude/plans/bueno-ahora-lo-mas-kind-steele.md`). Resumen de lo que cambió y del estado resultante:

- **Toda la extracción es v9.** Los endpoints `/api/extraction/{single,batch,run-all,agent}/...`, la re-extracción tras `POST /api/emails/check` y el monitor de Gmail llaman a `backend.v9.pipeline.extract_case` (que ahora corre `field_extractor_pass` → los 22 `extract_<campo>_for_case`). `persist.py` **solo rellena campos vacíos** — nunca pisa lo ya extraído ni lo editado a mano → "Extraer/Re-extraer/batch" son seguros. **El motor v8 ya no se invoca.**
- **`/api/dashboard/kpis`** ya no da 500 (join `Document↔Case` calificado en `case_service._get_quality_metrics`).
- **Asistente jurídico (botón flotante):** apunta a `POST /api/chat/` (Tier-1 determinístico, instantáneo; Tier-2 LLM local gateado por `LLM_LOCAL_PRIMARY=true` Y no `V9_DISABLE_LLM`). `chat.py` tiene intents nuevos sobre el cuadro (`cuadro_columnas`, `cuadro_completitud`, `_overview` enriquecido) y corregido el desfase v8/v9 en `count_by_abogado/dependencia/sentido_fallo/temas_top/...` → contesta con números reales. `/api/cognitive/*` y `/api/dashboard/chat` retirados; `routers/cognitive.py` borrado.
- **Endpoint v8.1 "validar" retirado** (`/api/cases/{id}/validate`, `/api/cleanup/validate-all`) + su botón en la ficha.
- **Utilidades de documentos** (`extract_document_text`, `classify_doc_type`, `verify_document_belongs`, `verify_all_documents`, `reextract_document`, `compute_file_hash`, `detect_duplicate_documents`, `_verify_bayesian`, `_verify_legacy`) viven ahora en **`backend/extraction/doc_ops.py`** (módulo limpio). El código vivo importa de ahí.
- **Borrado:** `backend/_legacy/{extraction/{pipeline,unified,unified_cognitive}.py, router_cognitive.py}`, `backend/cognition/{cognitive_complementary_ai,focused_field_extractors,document_authority,cognitive_persist,live_consolidator,entropy,procedural_timeline,case_classifier,flag_normalizer}.py`, `backend/cognition/agent/*`, `backend/extraction/remote_client.py`, `scripts/_legacy/*`, y sus tests (movidos a `tests/_legacy/`, que `tests/conftest.py` ignora). Scripts one-off que dependían de eso → `scripts/archive/`.
- **Sigue VIVO en `backend/cognition/`:** `legal_schema.py` (lo usa v9), `bayesian_assignment.py` + `canonical_identifiers.py` (los usa `doc_ops._verify_bayesian`), `confidence.py`, `folder_renamer.py`, y el "fill cognitivo determinista" (`cognitive_fill` → `zone_classifier`/`entity_extractor`/`decision_extractor`/`narrative_builder`/`cie10_to_derecho`/`semantic_matcher`/`timeline_builder`/`ner_spacy`) — lo usan `services/active_learning_scheduler.py` (cron) y `ner_spacy._get_nlp` (main.py / routers/extraction.py). **Pendiente futuro:** si se retira ese scheduler, esa sub-rama queda muerta.
- **Frontend:** "Procesamiento" y "Herramientas IA" marcadas "(v8 · legacy)" en el menú; `AgentChat.tsx` (huérfano) → `frontend/src/_legacy/`; `npm run build` arreglado.
- **Red de seguridad:** `scripts/run_safety_net.sh` (= `v9_test_standalone.py` 61/61 + `scripts/smoke_backend.py` 92 endpoints + `scripts/smoke_frontend.mjs` Playwright — éste necesita `cd frontend && npx playwright install chromium`). Correr tras cada cambio.
- **Servidores:** backend `V9_DISABLE_LLM=true ./venv/bin/python3 -m uvicorn backend.main:app --host 0.0.0.0 --port 8000`; frontend `./node_modules/.bin/vite --host 0.0.0.0` en `frontend/`; llama-server :8765 (Qwen3-4B). Rama de respaldo: `backup/pre-modernizacion`.
- **Pendiente menor:** linter de imports muertos (`ruff`/`pyflakes` no instalados); migrar `sync_service`/doctype-nuevos a `v9.doc_librarian` en vez de `classify_doc_type` (filename); el cuadro Excel de 39 columnas (`/api/reports/excel` ya existe; falta `scripts/build_cuadro_excel.py` si se quiere CLI).

---

## ESTADO ACTUAL (al cierre de la sesión anterior — Fase 2 de extracción)

### FASE 1 — INGESTA: ✅ COMPLETADA
- DB limpia reconstruida desde Gmail (1440 emails, orden cronológico más-antiguo→reciente)
- BASE_DIR = `/home/wilsonarguello/Documentos/GOBERNACION DE SANTANDER/V9_PRODUCCION`
- **398 cases, 4487 documents**, 3.6 GB en disco
- **1:1 emails ↔ .md** (fix de msg_id en md_filename)
- **0 errores SQL** (fix `_ensure_unique_folder_name`)
- Cascada de matching v9.1 (10 niveles): thread RFC5322 → rad21 → rad23-en-texto → FOREST+sender → cédula → rad_corto → personero → nombre_fuzzy → shell → orphan
- Sistema de familia: docs del mismo email viajan juntos; incidentes en sub-carpeta `incidente_<rad>-<sufijo>`
- 60 docs SOSPECHOSOS (FOREIGN reales, 98% precisión); 30 con `suggested_target_case_id` (cruce de referencias)
- `verificacion_score` (0-1) calculado para los 4487 docs

### LLM: Qwen3-4B activo
- `llama-server` corriendo: `data/lora-models/Qwen3-4B-Q4_K_M.gguf`, puerto 8765, alias `qwen3-4b-iuris`, ctx 16384, sin LoRA
- ~6.3 GB RAM, ~7s/campo de extracción semántica, calidad EXCELENTE en pruebas
- Comando para relanzarlo si cae: ver `CLAUDE.md`

### Backend
- Levantado en :8000 (`python3 -m uvicorn backend.main:app --host 0.0.0.0 --port 8000`)
- Login: `wilson / tutelas2026`
- Frontend opcional: `./node_modules/.bin/vite --host 0.0.0.0` en `frontend/`

## CAMPOS DEL CUADRO EXCEL (39 columnas) — ESTADO

| # | Campo | Estado | Cobertura |
|---|---|---|---|
| 1 | tipo_actuacion | ✅ | 100% (default TUTELA/INCIDENTE en regex_pass) |
| 2 | RADICADO_23_DIGITOS | ✅ DB | 93% (sliding window CUP + cascada) |
| 3 | RADICADO_FOREST | ✅ DB | 83% (mensaje canónico tutelas@santander + header DOCX) |
| 3b | forest_impugnacion | ✅ DB | 33 cases |
| 4 | ACCIONANTE | ✅ DB | 83% + 162 notas obs (personero→institución, agente oficioso→nota) |
| 5 | ACCIONADOS | ✅ DB | 94% (default GOB+SEC, normaliza typos) |
| 6 | VINCULADOS | ✅ DB | 10% (techo natural — solo autos con vinculación explícita) |
| 7 | DERECHO_VULNERADO | ✅ DB | 96% (82% regex anclas "derechos fundamentales a X" + tags; 14% LLM fallback Qwen3-4B; 3% SIN_DETERMINAR doc-poor) |
| 8 | JUZGADO (1ra) + juzgado_2nd | ✅ DB | 95% juzgado 1ra (remitente Rama Judicial cendoj/notificacionesrj + header/sello); juzgado_2nd 54 extraído + 23 derivado (mapa judicial canónico) |
| 9 | CIUDAD | ✅ DB | 91% (≈363) — = municipio del juzgado de 1ra (derivado del nombre del juzgado, conserva tildes; fallback auto/demanda). Validado contra el corpus: coincide con "Señor Juez de X" 9/9 y "Juzgado de X" del auto 27/28 |
| 10 | FECHA_INGRESO | ✅ DB | 71% (285) = fecha del auto admisorio (texto del auto 175 + recap en sentencia/notificación 82 + email auto-admite 28); 112 SIN (sin auto archivado ni recap). Cota de cordura: año del rad23 ±1 |
| 11 | ASUNTO | ✅ DB | vocabulario controlado SED (`legal_schema.SED_TEMA_MAPPING`): keyword **96%** (380/397; TRASLADO domina ~262) + LLM fallback; ~17 SIN_DETERMINAR = expedientes que solo conservan docs de 2da instancia (mismos sospechosos doc-poor) |
| 12 | PRETENSIONES | ✅ DB | transcripción literal de lo solicitado en el escrito de tutela (sección PRETENSIONES/SOLICITO de la demanda; recap en sentencia/auto si no): **~62% por regex** (245/397) — techo real ~245-255; el resto NO tiene las pretensiones en forma extractable (~14 doc-poor; ~138 demandas truncadas a 30k chars / RESPUESTAS con narrativa SED / sentencias que parafrasean / incidentes). LLM-localizador disponible (`--field pretensiones --apply`) pero lento en este equipo y aún imperfecto → no recomendado para batch grande, ok para el día a día |
| 13 | OFICINA_RESPONSABLE | ✅ DB | 389/397 (98%) = Dirección L1 SED derivada del `asunto` (`legal_schema.SED_TEMA_MAPPING` → L1: TALENTO_DOCENTE 341, ESTRATEGICA 28, APOYO_DIRECTO 12, ADMIN_FINANCIERA 6, PERMANENCIA 2). NO se usa el footer (siempre apunta a Apoyo Jurídico, no a la oficina sustantiva) |
| 13b | ABOGADO_RESPONSABLE | ✅ DB | 194/397 (los cases con DOCX de respuesta) = footer "Proyectó: NOMBRE" → resuelto contra el roster del Grupo Jurídico (15 abogados + correos, `grupo_juridico_abogados.json`) + el catálogo `abogados_canonicos.json` (17); sin match → nombre limpio crudo. Top: M.C. Villamizar Schiller 90 (jefe), Bohórquez 17, Cruz Lizcano 17, Barroso 15, Colmenares 13 |
| 14 | SENTIDO_FALLO_1ra + FECHA_FALLO_1ra | ✅ DB | sentido **247/397 (62%)**: CONCEDE 188 / IMPROCEDENTE 35 / CARENCIA_OBJETO 30 / NIEGA 15 / HECHO_SUPERADO 2 (CONCEDE_PARCIAL no aparece). Fuentes: SENTENCIA_1RA propia (detecta y descarta las 2da-mal-clasificadas; usa el ÚLTIMO RESUELVE para evitar matchear texto considerativo), DESCONOCIDO con RESUELVE clara, recap "el a-quo CONCEDIÓ/NEGÓ" en SENTENCIA_2DA / AUTO_CONCEDE_IMPUGNACION / IMPUGNACION (D2591/91 art. 32 obliga fallo 1ra si hay impugnación). Fecha 215/397 (54%) con cota cronológica `fallo ≥ ingreso` (0 violaciones). Mediana delta ingreso→fallo = 13 días = plazo legal D2591/91 art. 29. Los 150 SIN restantes: 6 doc-poor reales, ~27 con evidencia procesal pero recap no clasifica, ~94 con docs pero no extractables (correos mal clasificados, PDFs truncados a 30k) |
| 15 | IMPUGNACIÓN cluster (4 campos) | ✅ DB | `impugnacion` SI/NO: **116/397 SI** (80 con doc de 2da + 36 con evidencia SOLO en el SUBJECT/cuerpo de los emails .md — "FALLO DE SEGUNDA INSTANCIA", "AUTO CONCEDE IMPUGNACIÓN", "IMPUGNACIÓN FALLO 2026-XXX"; el `_RE_IMPUG_FLAG` exige verbo de acción, no la mera mención boilerplate "procede el recurso de impugnación"). `quien_impugno`: 43/116 — ACCIONANTE 24 / ACCIONADO 14 / AMBOS 5 (regex sobre docs de 2da + SUBJECT del email "IMPUGNACIÓN DEL ACCIONANTE/ACCIONADO" + cuerpo "impugnación interpuesta por…"). `sentido_fallo_2nd`: 18/116 (de las ~31 SENTENCIA_2DA archivadas) — CONFIRMA 10 / NULIDAD 3 / REVOCA 3 / MODIFICA 2. `fecha_fallo_2nd`: 28/116, cota `fallo_2nd ≥ fallo_1st`. NOTA: los ~98 SI sin `sentido_fallo_2nd` están con la impugnación EN CURSO (D2591/91 art.32: 20 días) o sin la sentencia 2da archivada |
| 16 | INCIDENTES DE DESACATO 1/2/3 (12 campos) | ✅ DB | `incidente` SI/NO: 71 SI (señal: doc INCIDENTE_DESACATO/AUTO_INCIDENTE o subject/cuerpo del email "incidente de desacato"/"apertura"/"requerimiento incidente"/"terminación incidente"; flag NO al resto). nº incidentes/case: 60×1, 7×2, 4×3 (cuenta fechas únicas de escritos, colapsa fechas ≤21 días = etapas del mismo incidente). `fecha_apertura_incidente`: 63/71 (cota ≥ fecha_fallo_1st). `responsable_desacato`: 31/71 (regex "contra/a [NOMBRE]"/"REQUERIR a [NOMBRE]"/"sancionar a [NOMBRE]"; default "Secretario de Educación" si hay sanción). `decision_incidente` ∈ {SANCIONA/NO_SANCIONA/NIEGA_APERTURA/CIERRA/EN_TRAMITE}: EN_TRAMITE 62 / CIERRA 4 / SANCIONA 4 / NIEGA_APERTURA 1 (de AUTO_INCIDENTE RESUELVE o subject del email "AUTO SANCIONA/ARCHIVA/TERMINACION/REQUIERE PREVIO") |
| 17 | ESTADO (ACTIVO/INACTIVO) + FECHA_RESPUESTA | ✅ DB | `estado` DERIVADO (decisión del usuario): INACTIVO si hay fallo 1ra Y (sin impugnación o 2da ya falló) Y (sin incidente o todos decididos — no EN_TRAMITE); ACTIVO en cualquier otro caso → ACTIVO 236 / INACTIVO 161. `fecha_respuesta` = dateline del DOCX de respuesta de la SED (la más temprana si hay varias), cota año rad±1 y ≥ fecha_ingreso (0 violaciones); fallback `date_received` del email "RESPUESTA … TUTELA …" → 204/397 (195 del DOCX + 9 del email), 193 SIN (sin RESPUESTA archivada) |
| 18 | CATEGORIA_TEMATICA + OBSERVACIONES | ✅ DB | `categoria_tematica` DERIVADO del `asunto` (grupo L2 de la SED, vía `legal_schema.categoria_tematica_de_asunto` / `CATEGORIA_TEMATICA_VOCAB` — 13 valores) → 389/397 (= los mismos 8 SIN_DETERMINAR que `asunto`). Distribución: CARRERA_DOCENTE 293, ADMINISTRACION_PLANTA 37, COBERTURA_EDUCATIVA 23, APOYO_JURIDICO 12, PRESTACIONES_SOCIALES 10, DERECHOS_FUNDAMENTALES 5, FINANCIERA 4, NOMINA 2, PERMANENCIA_ESCOLAR 2, HISTORIAS_LABORALES 1. `observaciones` = texto libre (lo edita la coordinadora); v9 lo SIEMBRA append-only e idempotente con la nota de agente oficioso/personería (campo 4) + 2 banderas detectadas sobre el escrito de tutela: "Se solicitó medida provisional" (36) y "Sujeto de especial protección: menor/discapacidad/adulto mayor/gestante" (82) → 216/397 con observaciones |

## ARCHIVOS CLAVE DE v9

- `backend/v9/regex_pass.py` — extractores regex doc-por-doc (rad23, forest, accionante, etc.)
- `backend/v9/field_extractor.py` — extractores a nivel CASE (Fase 2): `extract_forest_for_case`, `extract_accionante_for_case`, `extract_accionados_for_case`, `extract_vinculados_for_case`, `extract_derecho_vulnerado_for_case` (+ `DERECHO_VOCAB`), `extract_juzgado_for_case` + `extract_juzgado_2nd_for_case` (parser remitente Rama Judicial + derivación con `legal_schema`)
- `backend/cognition/legal_schema.py` — DATASET CANÓNICO: mapa judicial Santander (2 distritos, circuitos, `MUNICIPIO_CIRCUITO`, `CIRCUITO_A_DISTRITO`, Tribunales) + `derivar_juzgado_segunda()` (factor funcional: municipal→circuito, circuito→tribunal). También `SED_TEMA_MAPPING` (asunto→L1/L2/L3+categoria) y `clasificar_sed_tematica()`
- `backend/v9/doc_librarian.py` — bibliotecario: clasifica 16 doctypes, verifica pertenencia, audita expediente
- `backend/v9/pipeline.py` — orquestador del pipeline v9 (5 etapas)
- `backend/v9/types.py` — `ExtractedFields` (38 campos del cuadro)
- `scripts/ingest_from_gmail_v9.py` — ingesta desde Gmail con cascada de matching
- `scripts/v9_extract_fields.py` — aplica los field_extractors a todos los cases (`--field forest|accionante|accionados|derecho|juzgado|ciudad|fecha|asunto|pretensiones|asignacion|fallo|impugnacion|incidentes|estado|all --apply`; `--no-llm` desactiva el fallback LLM en derecho/asunto/pretensiones)
- `backend/data/grupo_juridico_abogados.json` — roster del Grupo Jurídico SecEdu (15 abogados + correos), del `GRUPO JURIDICO ABOGADOS SEC EDUCACION.xlsx`
- `backend/data/areas_encargadas.json` — correos de las áreas/dependencias SecEdu → código L1, de la hoja "Contactos por Área" del `Lista_Abogados__areas encargadas_Correos.xlsx`
- `scripts/v9_post_ingest_analysis.py` — calcula verificacion_score + cruce de referencias
- `scripts/v9_test_standalone.py` — test sin DB (61/61 ✓ — checks de derecho_vulnerado, juzgado, ciudad, fecha_ingreso, asunto, pretensiones, oficina, abogado, sentido_fallo_1ra, categoria_tematica, observaciones)
- `docs/V9_FASE2_EXTRACCION_PLAN.md` — plan de los campos semánticos pendientes

## METODOLOGÍA FASE 2 (campo por campo)

Para cada campo del cuadro, en orden:
1. El usuario dice: ¿en qué doc(s) aparece? ¿qué patrones/pistas hay?
2. Construir corpus de muestra (30-100 docs de ese tipo) y medir match-rate de regex candidatos
3. Lo que regex no cubre → prompt LLM focal (Qwen3-4B local)
4. Implementar en `regex_pass.py` (campo estructural) o `field_extractor.py` (campo a nivel case)
5. Validar sobre los 397 cases → iterar hasta cobertura razonable
6. `python3 scripts/v9_extract_fields.py --field <campo> --apply`
7. Siguiente campo

NO tocar la ingesta (fase cerrada). NO meter VLM/OCR (decidido: no aporta al objetivo, ver `docs/V9_FASE2_EXTRACCION_PLAN.md`).

## CAMPO 7 — DERECHO_VULNERADO ✅ (cerrado esta sesión)

Decisiones (confirmadas por el usuario):
- **Vocabulario controlado (11 tags + OTRO):** EDUCACION, SALUD, PETICION, DEBIDO_PROCESO, VIDA, SEGURIDAD_SOCIAL, MINIMO_VITAL, TRABAJO, IGUALDAD, INTIMIDAD, HABEAS_DATA, OTRO. El orden de la tupla = prioridad de concatenación. `OTRO` sólo lo emite el LLM (derecho real fuera de la lista).
- **Multi-derecho:** se **concatenan todos** "A - B - C" en orden del vocabulario (como `accionados`).
- **Default:** `SIN_DETERMINAR` cuando ni regex ni LLM logran nada.
- **LLM fallback:** sí — Qwen3-4B local (`_llm_classify_derecho`), 1 llamada por caso sólo si el regex no encontró. Respeta `V9_DISABLE_LLM=true`. Lento bajo carga (~7s/caso libre, hasta ~1-2min/caso con el backend corriendo).

Implementación: `backend/v9/field_extractor.py` → `extract_derecho_vulnerado_for_case(db, case, use_llm=True)`. Ancla sobre "derechos fundamentales/constitucionales a la X, Y y Z" (escanea sólo los primeros 8000 chars del doc, descarta regiones que arrancan con boilerplate jurisprudencial, trunca la enumeración en marcadores tipo "los cuales considera vulnerados...", borra "Secretaría de Educación" para no confundir la accionada con el derecho). Prioridad de doctype: AUTO_ADMISORIO > DEMANDA_TUTELA > SENTENCIA_1RA > SENTENCIA_2DA > otros — el primero con señal gana (el auto enuncia el reclamo limpio; la demanda lista todo; la sentencia trae jurisprudencia).

Aplicado a DB: `python3 scripts/v9_extract_fields.py --field derecho --apply` (regex 82% + LLM rellena el resto). Resultado: 96% con derecho, 14 SIN_DETERMINAR (doc-poor), 8 OTRO.

## CAMPO 8 — JUZGADO ✅ (cerrado esta sesión)

Dos slots: `juzgado` (1ra instancia) y `juzgado_2nd` (2da, solo si hubo impugnación). Implementación en `field_extractor.py`:
- **Fuente canónica = remitente/destinatario de los emails de la Rama Judicial.** Las cuentas de `cendoj.ramajudicial.gov.co` / `notificacionesrj.gov.co` se llaman literal `Juzgado 04 Civil Municipal - Santander - Girón <j04cmpalgiron@cendoj...>` → de ahí salen número, especialidad, NIVEL (Municipal/Circuito) y municipio. `_RE_RJ_SENDER` + `_juzgado_from_rj_sender()` → forma normalizada `JUZGADO NN ESPECIALIDAD NIVEL DE MUNICIPIO (SANTANDER)` (y `TRIBUNAL SUPERIOR DEL DISTRITO JUDICIAL DE X - SALA Y` para la secretaría de una Sala).
- Fallback: header/sello de AUTO_ADMISORIO / SENTENCIA_1RA / NOTIFICACION / OFICIO (`_clean_juzgado()` recorta basura post-nombre y al final del municipio Santander).
- Nivel MUNICIPAL gana sobre CIRCUITO/TRIBUNAL para `juzgado` 1ra (por reparto, las tutelas contra la SED departamental van a Juez Municipal del lugar de los hechos).
- `juzgado_2nd`: solo si hay doc de 2da instancia (o `impugnacion=='SI'` cuando ese campo exista). Toma un candidato nivel CIRCUITO/TRIBUNAL distinto al de 1ra; si no se extrae explícito → **deriva con `legal_schema.derivar_juzgado_segunda()`** (municipal→Juez del Circuito del municipio; circuito→Tribunal Superior/Administrativo) y marca el valor con sufijo `(DERIVADO)`.

Aplicado a DB: `python3 scripts/v9_extract_fields.py --field juzgado --apply`. Resultado: juzgado 1ra 95% (378/397), 19 SIN (doc-poor); juzgado_2nd 77 (54 extraído + 23 derivado de los 81 cases con doc de 2da).

## CAMPO 9 — CIUDAD ✅ (cerrado esta sesión)

**Regla (confirmada por el usuario): `ciudad` = municipio del Juzgado que conoce la tutela en 1ra instancia ≈ lugar de los hechos** (competencia "a prevención", Decreto 2591/1991: la tutela se tramita en el lugar de la presunta vulneración). **Análisis del corpus** (80 cases con demanda+auto+juzgado): el municipio del juzgado coincide con el "Señor Juez de X" del encabezado de la demanda **9/9** y con "Juzgado de X" del header del auto admisorio **27/28** (el desacuerdo restante fue un error de extracción del juzgado, no ambigüedad real). Caveat: en el área metropolitana de Bucaramanga (Floridablanca/Girón/Piedecuesta) algunas tutelas se reparten a un juzgado de Bucaramanga aunque la I.E./docente esté en el suburbio (mismo circuito judicial) → `ciudad` = BUCARAMANGA en esos casos.

Implementación: `field_extractor.extract_ciudad_for_case` → toma el municipio embebido en `case.juzgado` (regex `_RE_CIUDAD_TAIL_JUZGADO`, **conserva tildes**: `GIRÓN`, `MÁLAGA`, `SAN VICENTE DE CHUCURÍ`); para juzgados de fuera de Santander toma el municipio tal cual del nombre (`TUNJA`). Fallbacks: "Juzgado ... de X" en el header del auto; "Señor Juez de X" en la demanda. Aplicado a DB: `python3 scripts/v9_extract_fields.py --field ciudad --apply` → 363/397 (91%), 34 SIN (cases doc-poor sin juzgado).

## CAMPO 10 — FECHA_INGRESO ✅ (cerrado esta sesión)

**Regla (confirmada por el usuario): `fecha_ingreso` = fecha del AUTO que admite/avoca la tutela** (formato `DD/MM/AAAA`). Nota procesal aparte (no es este campo): la entidad se entiende notificada al día SIGUIENTE de la llegada del correo del juzgado, y el término empieza a correr desde ahí — eventual campo derivado `fecha_notificacion`/`fecha_inicio_termino`.

Implementación: `field_extractor.extract_fecha_ingreso_for_case`. Fuentes en orden: (1) fecha en el texto del propio auto admisorio (dateline "Ciudad, DD de MMMM de AAAA" arriba o junto a la firma; "auto de fecha X"; parser `_parse_es_dates` maneja numérico, "DD de mes de AAAA", "(NN) días del mes de … dos mil …"). (2) recap en otros docs ("mediante auto del DD de MMMM de AAAA se admitió la tutela" en sentencias/notificaciones/respuestas — `_RE_AUTO_ADMIS_RECAP`). (3) fecha del primer email cuyo subject indica que lleva/notifica el auto. **Cota de cordura: el año de la fecha debe estar dentro de ±1 del año del rad23** (chars 12-15) → descarta fechas de jurisprudencia citada / otros radicados.

Aplicado a DB: `python3 scripts/v9_extract_fields.py --field fecha --apply` → 285/397 (71%): 175 del auto + 82 recap + 28 email; 112 SIN (cases sin el auto archivado ni recap — limitación de datos, no de extracción). Distribución de años: 2026=262, 2025=19, 2024=4 (carryover).

## CAMPOS 11-12 — ASUNTO + PRETENSIONES ✅ (cerrados esta sesión)

Decisiones del usuario: `asunto` → **vocabulario controlado** (el verbo del reclamo se normaliza al sustantivo: "trasladar" → `TRASLADO`); `pretensiones` → **transcripción literal** de lo solicitado en el escrito de tutela.

- **ASUNTO** (`field_extractor.extract_asunto_for_case`): usa el taxonomía SED existente `legal_schema.SED_TEMA_MAPPING` / `clasificar_sed_tematica()` (categoría `[3]` de la tupla — TRASLADO / NOMBRAMIENTO / PENSION / MATRICULA / INCIDENTE_DESACATO / INCLUSION_DISCAPACIDAD / TRANSPORTE_ESCOLAR / SALUD_DOCENTE / DERECHO_PETICION / DEBIDO_PROCESO / …). Keyword matching primero (**96%**, TRASLADO domina ~262/397) sobre el texto del case (asuntos de emails + TODOS los docs con texto, incl. los de 2da instancia y DESCONOCIDO — sus ANTECEDENTES recapitulan el reclamo); LLM (Qwen3-4B) como fallback; default `SIN_DETERMINAR`. **Los ~17 SIN_DETERMINAR son expedientes que solo conservan los docs de 2da instancia** (sentencia/auto de impugnación) sin demanda/auto/sentencia de 1ra — mismos sospechosos doc-poor de `SIN_ACCIONANTE`, no es fallo de extracción.
- **PRETENSIONES** (`field_extractor.extract_pretensiones_for_case`): regex de sección VERBATIM (como el legacy `narrative_builder.build_pretensiones`). Busca el encabezado `PRETENSIONES`/`PETICIÓN`/`SÚPLICAS`/`SOLICITUDES`/`SOLICITO`/`HECHOS Y PRETENSIONES`/`OBJETO DE LA ACCIÓN`/`SOLICITUD DE AMPARO`/`EN CONSECUENCIA`/`RUEGO A SU DESPACHO` (línea propia), o el arranque inline (`respetuosamente solicito a su despacho:` / `con fundamento en los hechos solicito:` / `por lo anterior solicito:` / `los hechos y pretensiones que fundamentan ... son:`), o (en auto/sentencia) el recap `solicitando que se ordene/tutele/ampare ...`; transcribe hasta el siguiente encabezado (`PRUEBAS`/`ANEXOS`/`FUNDAMENTOS DE DERECHO`/`HECHOS`/`ACTUACIÓN PROCESAL`/etc.) o ~4000 chars, conservando el punto final. Orden de fuentes: DEMANDA_TUTELA → ANEXO_DEMANDA → SENTENCIA_1RA/2DA → AUTO_ADMISORIO/2DA → AUTO_CONCEDE_IMPUGNACION → IMPUGNACION → INCIDENTE_DESACATO → NOTIFICACION(_FALLO) → RESPUESTA → DESCONOCIDO (los no-demanda se escanean con `strip_defense=True` para no capturar la contestación SED "que se declaren improcedentes las pretensiones"; `OFICIO_CUMPLIMIENTO` se excluye a propósito). **~62% por regex (245/397)** — éste es prácticamente el techo: de los 152 SIN, ~14 son doc-poor sin texto y ~138 tienen un doc grande pero NO contienen las pretensiones del accionante en forma extractable (demandas truncadas a 30 000 chars por el cap de `extracted_text` — las de 16 págs de las personerías cortan antes; RESPUESTAS de la SED con su narrativa; sentencias que sólo *parafrasean* el reclamo; incidentes de desacato). Para esos cases no hay de dónde transcribir sin re-ingestar los PDFs sin el cap.
  - **Si no hay regex → LLM como LOCALIZADOR** (`_llm_locate_pretensiones`, decisión del usuario: "las pretensiones se transcriben tal cual, no hace falta cognición/parafraseo"): el LLM **no genera** la transcripción — sólo devuelve las primeras ~8-12 palabras de la primera pretensión (`max_tokens=48`), se localiza ese ancla en el texto **original** con `_flexible_substr_pos` (tolerante a mayúsculas/espacios) y se extrae la sección VERBATIM desde ahí. El prompt enfatiza "del ACCIONANTE, no las órdenes del juez (VINCULAR/REQUERIR/AVOCAR) ni la contestación de la SED", y se le pasa el texto de la DEMANDA si existe. Limitación: en este equipo (11 GB RAM, ctx 16384) cada llamada cuesta ~60-90 s (prefill de ~2 000 tokens en CPU) → **no correr el batch grande así**; sirve para el flujo diario de ~4 cases. Para batch, primero relanzar `llama-server` con `--ctx-size 4096 --parallel 1` (ocupa ~4 GB, libera RAM, mata el swap-thrashing).

## CAMPO 13 — OFICINA_RESPONSABLE + ABOGADO_RESPONSABLE ✅ (cerrado esta sesión)

- **OFICINA_RESPONSABLE** (`field_extractor.extract_oficina_responsable_for_case`): = la Dirección L1 de la SED dueña del ASUNTO de fondo (la que debe ACTUAR). Prioridad: (1) **EMAIL DE ASIGNACIÓN** — si en los .md de los emails del case aparece (en Para/Cc/De) un correo de un área de la SED, ese es el área a la que Apoyo Jurídico asignó el caso (`backend/data/areas_encargadas.json`, generado de la hoja "Contactos por Área" del `Lista_Abogados__areas encargadas_Correos.xlsx` que aportó el usuario — 20 correos → L1, p.ej. `juridicatheducacion@santander.gov.co`/`admplanta@`/`ln.amarin@` → TALENTO HUMANO; `juridicotransporte@`/`pae@` → PERMANENCIA; `financierased@`/`ln.jaguilar@` → ADMIN_FINANCIERA; `ln.lygomez@`/`ca.dmejia@` → ESTRATEGICA); (2) derivada del `asunto` ya extraído (`legal_schema.SED_TEMA_MAPPING` → L1 vía `_ASUNTO_TO_L1`) — heurística por keyword, fallback. NO se usa el footer del DOCX de respuesta (siempre apunta a Apoyo Jurídico, no a la oficina sustantiva). Aplicado: 389/397 (98%) — 79 por email de asignación + 310 derivado del asunto. Distribución: DIRECCION_TALENTO_DOCENTE 305, DIRECCION_ESTRATEGICA 52, DIRECCION_ADMIN_FINANCIERA 17, APOYO_DIRECTO 12, DIRECCION_PERMANENCIA 3.
- **ABOGADO_RESPONSABLE** (`field_extractor.extract_abogado_responsable_for_case`): = quien firma el DOCX de respuesta ("Proyectó: NOMBRE", via `regex_pass._extract_abogado_footer`). Si varias respuestas → el más frecuente (empate → la más reciente). Se limpia (`_clean_abogado_name` quita "-JEFE APOYO JURÍDICO" / "EXT 1422" / "CONTRATISTA SED" / etc.; rechaza si quedan palabras no-nombre) y se resuelve contra: (1) **roster del Grupo Jurídico** aportado por el usuario — 15 abogados + correos, `backend/data/grupo_juridico_abogados.json` (creado del `GRUPO JURIDICO ABOGADOS SEC EDUCACION.xlsx`) — por correo si aparece en el doc, o por nombre exacto/substring/fuzzy; (2) catálogo `abogados_canonicos.json` (17, con aliases) vía `catalog_resolve.resolve_abogado`. Sin match → nombre limpio crudo. Aplicado: 194/397 (los cases con DOCX de respuesta). Top: M.C. Villamizar Schiller 90 (jefe Apoyo Jurídico, no está en el roster de 15 contratistas), Bohórquez 17, Cruz Lizcano 17, Barroso 15, Colmenares 13. Aplicado: `python3 scripts/v9_extract_fields.py --field asignacion --apply`.

## CAMPO 14 — SENTIDO_FALLO_1ra + FECHA_FALLO_1ra ✅ (cerrado esta sesión)

- **SENTIDO_FALLO_1ra** (`field_extractor.extract_sentido_fallo_1ra_for_case` + `_classify_sentido_fallo`): clasifica la zona RESUELVE al vocab cerrado `SENTIDO_FALLO_VOCAB = (CONCEDE, CONCEDE_PARCIAL, NIEGA, IMPROCEDENTE, HECHO_SUPERADO, CARENCIA_OBJETO)`. Orden de patrones: CARENCIA_OBJETO → HECHO_SUPERADO → IMPROCEDENTE → CONCEDE_PARCIAL → **NIEGA → CONCEDE** (al final). NIEGA tiene que ser sobre el AMPARO. CONCEDE incluye verbos dispositivos del SED context (TRASLADAR, REINTEGRAR, NOMBRAR, DEJAR SIN EFECTO, REVOCAR-acto-administrativo). **Fuentes** (en orden): (1) SENTENCIA_1RA propia — detecta y **descarta las 2da-mal-clasificadas** por el librarian (`_doc_es_realmente_2da`: marcadores "segunda instancia", "Tribunal Superior", o verbo dispositivo CONFIRMAR/REVOCAR/MODIFICAR/INHIBIR) y usa **el ÚLTIMO match de RESUELVE** (no el primero, que cae en texto considerativo); (2) DESCONOCIDO con zona RESUELVE clara (sentencias mal clasificadas); (3) **recap del 1ra** dentro de SENTENCIA_2DA / AUTO_CONCEDE_IMPUGNACION / IMPUGNACION / AUTO_2DA / NOTIFICACION_FALLO — patrón "mediante sentencia / el a-quo CONCEDIÓ/NEGÓ/DECLARÓ…" (procesalmente, art. 32 Decreto 2591/1991 obliga a que haya habido fallo 1ra si hay impugnación). Aplicado: **247/397 (62%)**. Distribución: CONCEDE 188 (76%), IMPROCEDENTE 35, CARENCIA_OBJETO 30, NIEGA 15, HECHO_SUPERADO 2, CONCEDE_PARCIAL 0 (no apareció en este corpus). Los 150 SIN restantes: ~6 doc-poor reales, ~27 con evidencia procesal pero el recap no clasifica, ~117 con docs pero no extractables (correos cubierta mal clasificados como sentencia, o PDFs truncados al cap 30k chars).
- **FECHA_FALLO_1ra** (`field_extractor.extract_fecha_fallo_1ra_for_case`): dateline de la SENTENCIA_1RA (parser `_parse_es_dates`). Dos cotas: (a) año = `rad23_year` ± 1; (b) cronológica: `fecha_fallo ≥ fecha_ingreso` (si está disponible) — si el primer candidato viola, se prueba el siguiente; si todos violan, se devuelve None (evita capturar fechas citadas o del auto recapeado dentro del cuerpo). Aplicado: 215/397 (54%), **0 violaciones cronológicas**. Mediana delta ingreso→fallo = **13 días** (= el plazo legal de tutela), p90 60 días.

Aplicado a DB: `python3 scripts/v9_extract_fields.py --field fallo --apply`.

## CAMPO 18 — CATEGORIA_TEMATICA + OBSERVACIONES ✅ (cerrado esta sesión)

Decisiones (tomadas en modo auto, redirigibles):
- **`categoria_tematica` = agrupación temática del caso = grupo L2 de la SED** (CARRERA_DOCENTE / ADMINISTRACION_PLANTA / PRESTACIONES_SOCIALES / HISTORIAS_LABORALES / DESARROLLO_DOCENTE / NOMINA / FINANCIERA / COBERTURA_EDUCATIVA / CALIDAD_EDUCATIVA / PERMANENCIA_ESCOLAR / APOYO_JURIDICO / INSPECCION_VIGILANCIA / DERECHOS_FUNDAMENTALES — 13 valores). **DERIVADO del `asunto`** ya extraído (1 autoridad por campo, sin LLM, sin leer docs nuevos): `legal_schema.categoria_tematica_de_asunto()` toma el L2 de la entrada de `SED_TEMA_MAPPING` cuya `categoria` == el asunto; para las 3 entradas con L2=None (TRANSPORTE_ESCOLAR/ALIMENTACION_PAE → `PERMANENCIA_ESCOLAR`; TUTELA_GENERICA → `DERECHOS_FUNDAMENTALES`) se usa una etiqueta equivalente (`_CATEGORIA_TEMATICA_FALLBACK`). Si el asunto es OTRO/SIN_DETERMINAR → `categoria_tematica = SIN_DETERMINAR`. Es la capa intermedia entre `asunto` (acción concreta: TRASLADO) y `oficina_responsable` (Dirección L1) — no redundante con ninguno. Aplicado: 389/397 (= los 8 SIN_DETERMINAR son exactamente los del `asunto`; cota verificada).
- **`observaciones` = texto libre** que edita la coordinadora; v9 lo SIEMBRA **append-only e idempotente** (anexa una línea solo si su prefijo no está ya en el campo, como hace el campo 4): (1) la nota de **agente oficioso / representante legal / personería** (la pone el campo 4 ACCIONANTE — ya estaba), (2) "**Se solicitó medida provisional**" si el escrito de parte (DEMANDA_TUTELA/ANEXO_DEMANDA/IMPUGNACION/INCIDENTE_DESACATO, primeros 12k chars) menciona "medida provisional/cautelar" (36/397), (3) "**Sujeto de especial protección: <menor de edad | persona con discapacidad | adulto mayor / tercera edad | mujer gestante / en embarazo>**" con regex conservadoras (solo frases fuertes: "menor de edad", "interés superior del menor", "N.N.A.", "hijo menor"; "persona con discapacidad", "síndrome de Down", "TEA/autismo"; "adulto mayor", "tercera edad"; "gestante", "fuero/licencia de maternidad") — 82/397, sobre todo en tutelas de TRASLADO donde el docente alega afectación a la unidad familiar / hijos menores. NO se sacan banderas de los subjects de los emails ("URGENTE", "perjuicio irremediable" son boilerplate de toda tutela → ruido). Total: 216/397 con observaciones.

Implementación: `legal_schema.categoria_tematica_de_asunto()` + `CATEGORIA_TEMATICA_VOCAB`; `field_extractor.extract_categoria_tematica_for_case()` + `extract_observaciones_for_case()` (devuelve lista de banderas; el runner las anexa). Aplicado a DB: `python3 scripts/v9_extract_fields.py --field categoria --apply`. Checks añadidos a `v9_test_standalone.py` (ahora **61/61** — antes 50/50).

## PRÓXIMO PASO CONCRETO

**Campos 1-18 ya hechos y aplicados a la DB.** Pendientes de cierre/limpieza:
- ⚠️ **`asunto` — NO re-aplicar con el `_asunto_case_text` actual (deja la DB como está).** Investigado esta sesión: el problema NO es solo "auto de traslado" (el traslado *procesal* al accionado, que sí domina por ser "traslado" la 1ª entrada de `SED_TEMA_MAPPING`). Al neutralizar esa acepción aparece una capa más profunda: `clasificar_sed_tematica` hace **substring-match** (`if kw in txt`), y varios keywords son demasiado laxos — "**provision**" ⊂ "**provisional**" (cualquier "medida provisional" → NOMBRAMIENTO), "**encargo**" es genérico ("le encargo", "el encargo"), "**pago/giro**" ⊂ muchas palabras, etc. Re-aplicar con cualquier parche al "traslado" produce ~56 diffs con un montón de `TRASLADO→NOMBRAMIENTO` falsos. **Fix de verdad (sesión aparte, con el usuario):** pasar `clasificar_sed_tematica` a match por **límites de palabra** (`\b…\b` / token) en vez de substring, y limpiar los keywords laxos de `SED_TEMA_MAPPING`; recién entonces re-validar y re-aplicar `asunto` (y, derivado, `categoria_tematica`). La DB actual de `asunto`/`categoria_tematica` (validada ~96%) se mantiene.
- re-correr el pase LLM de `pretensiones` de noche (relanzar `llama-server` con `--ctx-size 4096 --parallel 1` primero): `python3 scripts/v9_extract_fields.py --field pretensiones --apply`.
- mejoras .md-como-fuente pendientes: `fecha_ingreso` (migrar de `Email.subject` a leer el .md), `abogado_responsable` (buscar el correo del abogado asignado en el To/Cc del .md de `apoyojuridico@`).
- armar el cuadro Excel final (39 columnas) a partir de la DB.

---
**(histórico de campos previos abajo)**

**Campo 15: IMPUGNACIÓN + QUIEN_IMPUGNO + SENTIDO_FALLO_2nd + FECHA_FALLO_2nd** (`forest_impugnacion` y `juzgado_2nd` ya hechos en campo 8). `impugnacion` SI/NO (flag — hay regex parcial en `regex_pass._extract_impugnacion_flag`: SI si hay doc IMPUGNACION o frase "recurso de impugnación"). `quien_impugno` ACCIONANTE/ACCIONADO/AMBOS (LLM o regex sobre la firma del doc IMPUGNACION). `sentido_fallo_2nd` CONFIRMA/CONFIRMA_PARCIAL/REVOCA/MODIFICA/INHIBIR (zona RESUELVE de SENTENCIA_2DA). `fecha_fallo_2nd` dateline de la SENTENCIA_2DA (con cota cronológica fallo_2nd ≥ fallo_1st).

## FUENTE COMPLEMENTARIA: SUBJECT + CUERPO DE LOS EMAILS .md

El monitor descarga el cuerpo de los emails del juzgado/SED como `.md` (doctype
EMAIL_JUDICIAL / EMAIL_INTERNO). El **subject** lo arma el juzgado/SED con info de oro
("NOTIFICACIÓN AUTO CONCEDE IMPUGNACIÓN — PRESENTADA POR LA ACCIONADA — RAD X",
"SOLICITUD DE DESIGNACIÓN DE DOCENTE", "APERTURA INCIDENTE DE DESACATO contra [NOMBRE]").
Principio: el regex sobre los docs autoritativos (demanda/auto/sentencia) va PRIMERO; el
contenido del email es **complemento/fallback**, nunca pisa una extracción confiable.
Dónde se usa o conviene usar:
- ✅ `radicado_forest` / `forest_impugnacion` — `_extract_forest` lee los .md.
- ✅ `juzgado` / `juzgado_2nd` — el remitente Rama Judicial ("Juzgado X - Santander - Y") sale del .md.
- ✅ `oficina_responsable` — correos de área (`juridicatheducacion@`, `pae@`, …) en Para/Cc del .md.
- ✅ `impugnacion` / `quien_impugno` — SUBJECT + cuerpo del .md (campo 15).
- ⚠️ `fecha_ingreso` — usa `Email.subject`; conviene también el head del .md (más completo).
- ✅ `asunto` — `_asunto_case_text` ahora incluye el head (2500 chars) del .md de los emails además de `Email.subject` (regex sube a 389/397; pendiente re-aplicar con `--field asunto --apply`).
- ⚠️ `abogado_responsable` — el .md de `apoyojuridico@...` que asigna el caso CC al abogado; conviene buscar el correo del abogado en el .md, no solo el footer del DOCX. **Pendiente.**

**Nota técnica (qué se lee del .md):** los `.md` son pequeños (pocos KB) e incluyen el subject + headers + cuerpo + el "hilo" de correos huella reenviados (con su From/To/Cc). Hoy:
- **se lee el .md COMPLETO**: `juzgado`/`juzgado_2nd` (`_rj_sender_candidates`), `oficina_responsable` (`_oficina_from_email_assignment`), `forest`/`forest_impugnacion`.
- **solo el head (~1200-8000 chars)**: `impugnacion`/`quien_impugno` (head 2500 + body 6000), `incidentes` (head 1200 + body 8000), `asunto` (head 2500).
- **solo `Email.subject` (la columna de la DB, NO el .md)**: `fecha_ingreso`. ← pendiente migrar a leer el .md.
Riesgo del hilo de reenvíos: puede citar OTRO radicado → patrones que matchean "radicado 2025-XXX" en texto reenviado pueden contaminar; mitigado anclando al rad del case cuando aplica.
- ⏳ `incidente` 1/2/3 + `fecha_apertura_incidente` + `responsable_desacato` + `decision_incidente` (campo 16) — los SUBJECTS gritan "INCIDENTE DE DESACATO RAD X", "AUTO QUE DECIDE INCIDENTE — SANCIONA"; **fuente primaria** para ese cluster.
- ⏳ `fecha_respuesta` — el `date_received` del email de la SED respondiendo a la tutela ("RESPUESTA AUTO DE TRASLADO TUTELA X").
- ⏳ `fecha_fallo_1st` / `fecha_fallo_2nd` — fallback: `date_received` del email que notifica el fallo (subject "NOTIFICACIÓN SENTENCIA TUTELA …" / "… SEGUNDA INSTANCIA …").
- ⏳ `estado` (ACTIVO/INACTIVO) — "en cumplimiento al fallo" / "SE REMITE … PARA CUMPLIMIENTO" sugiere caso resuelto.
- ❌ `pretensiones` — los subjects RESUMEN el reclamo, no lo transcriben; el usuario exige verbatim → NO usar el subject como pretensión.
- ❌ `derecho_vulnerado` — los subjects rara vez nombran el derecho; bajo valor.

## PENDIENTES MENORES (no bloqueantes)

- Endpoint UI para mostrar las 30 sugerencias de cruce de referencias ("¿mover doc#X a case#Y?")
- 5 patrones colectivos detectados (ej. case#246→case#92 con 5 docs cruzados) — auto-sugerencia en lote
- Vinculados: limpiar mejor el texto extraído ("trámite tutelar a;" etc.)
- Decidir destino de los 64 cases SIN_ACCIONANTE (pobres en docs)

## VOCABULARIOS CONTROLADOS

- ✅ `derecho_vulnerado`: EDUCACION / SALUD / PETICION / DEBIDO_PROCESO / VIDA / SEGURIDAD_SOCIAL / MINIMO_VITAL / TRABAJO / IGUALDAD / INTIMIDAD / HABEAS_DATA / OTRO (+ default SIN_DETERMINAR) — ver `DERECHO_VOCAB` en `field_extractor.py`
- ✅ `categoria_tematica`: grupo L2 SED — CARRERA_DOCENTE / ADMINISTRACION_PLANTA / PRESTACIONES_SOCIALES / HISTORIAS_LABORALES / DESARROLLO_DOCENTE / NOMINA / FINANCIERA / COBERTURA_EDUCATIVA / CALIDAD_EDUCATIVA / PERMANENCIA_ESCOLAR / APOYO_JURIDICO / INSPECCION_VIGILANCIA / DERECHOS_FUNDAMENTALES (+ default SIN_DETERMINAR) — ver `CATEGORIA_TEMATICA_VOCAB` / `categoria_tematica_de_asunto()` en `legal_schema.py`. Derivado del `asunto`.
- ✅ `sentido_fallo_1st`: CONCEDE / CONCEDE_PARCIAL / NIEGA / IMPROCEDENTE / HECHO_SUPERADO / CARENCIA_OBJETO — ver `SENTIDO_FALLO_VOCAB` en `field_extractor.py`
- ⏳ `sentido_fallo_2nd`: CONFIRMA / CONFIRMA_PARCIAL / REVOCA / MODIFICA / INHIBIR
- ⏳ `decision_incidente`: SANCIONA / NO_SANCIONA / NIEGA_APERTURA / CIERRA / EN_TRAMITE
- ⏳ `quien_impugno`: ACCIONANTE / ACCIONADO / AMBOS

---

**Para empezar la próxima sesión, di**: "Continuemos la Fase 2 del proyecto Tutelas v9. Los 18 campos del cuadro ya están extraídos y aplicados a la DB. Falta el cierre: (a) dar contexto al keyword 'traslado' en `_asunto_case_text`/`clasificar_sed_tematica` para poder re-aplicar `asunto` con el .md sin regresiones; (b) re-correr el pase LLM de `pretensiones` de noche con `--ctx-size 4096`; (c) mejoras .md-como-fuente de `fecha_ingreso` y `abogado_responsable`; (d) armar el cuadro Excel final (39 columnas) a partir de la DB. Empieza por: ___."
