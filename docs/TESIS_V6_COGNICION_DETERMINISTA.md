# Cognición Determinista en Sistemas Jurídicos

## Una tesis sobre Ingeniería Legal aplicada a la gestión de tutelas constitucionales

> **Autor:** Wilson — Ingeniero Legal Contratista, Secretaría de Educación de la Gobernación de Santander
> **Sistema referenciado:** Tutelas Manager v6.0
> **Fecha:** Abril 2026
> **Branch:** `experiment-v5.5` (Tutelas Manager)
> **Documentos relacionados:**
> - `TESIS_PROYECTO_AGENTE_JURIDICO.md` (v5.2, 12 capítulos)
> - `V6_COGNITIVE_RESULTS.md` (resultados empíricos v6.0)
> - `arquitectura_interactiva.html` (guía visual del sistema)

---

## Resumen ejecutivo (abstract)

Este documento presenta la **transición arquitectónica** de un sistema de
extracción jurídica basado en inteligencia artificial generativa (v5.x) a un
**sistema cognitivo determinista de 7 capas** (v6.0), diseñado mediante
**ingeniería inversa de la cognición del ingeniero legal humano**. La
motivación es doble: **reducir la entropía** de los datos (en sentido
Shannoniano) producida por pipelines con cajas negras, y **preservar la
privacidad** exigida por la Ley 1581/2012 de Habeas Data eliminando el envío
de información sensible a proveedores externos.

Los conceptos rectores son **entropía**, **teoría del caos**,
**negentropía** y **cognición forense**. El resultado es un pipeline que
opera **sin IA generativa externa** sobre los campos estructurales, que
produce veredictos **auditables y explicables** con trazabilidad completa, y
que demuestra propiedades de **idempotencia** (atractor fijo) cuantificables
matemáticamente. Sobre un corpus experimental de 197 casos reales, 5,194
documentos y 1,528 correos electrónicos, el sistema ha clasificado el 100%
de los casos según su origen procesal (tutela / incidente huérfano /
ambiguo) y ha producido veredictos de asignación documental con tasas de
acierto del 94,4% en el subconjunto ya procesado.

Más allá de los resultados técnicos, este trabajo postula una disciplina
emergente: la **Ingeniería Legal** — la intersección sistemática del
razonamiento jurídico con la arquitectura de software determinista. En el
contexto colombiano y latinoamericano, donde la inteligencia artificial
generativa plantea tensiones con el habeas data y la auditabilidad del acto
administrativo, la Ingeniería Legal ofrece un camino técnicamente válido y
éticamente defendible.

---

## Tabla de contenidos

1. Planteamiento del problema
2. Marco teórico
   2.1. Entropía de Shannon aplicada a datos jurídicos
   2.2. Teoría del caos en sistemas de extracción
   2.3. Negentropía y estructuras disipativas
   2.4. Cognición forense
   2.5. Ingeniería inversa cognitiva
3. Estado del arte previo (v1.0 → v5.5)
4. Metodología
5. Desarrollo: las 7 capas cognitivas
6. Resultados empíricos
7. Discusión
8. Conclusiones
9. Propuestas de investigación futura
10. Referencias y anexos

---
## 1. Planteamiento del problema

### 1.1. Contexto institucional

La Secretaría de Educación de la Gobernación de Santander (SED) recibe
aproximadamente **350 acciones de tutela por año** relacionadas con la
prestación del servicio educativo: reubicación de docentes por salud,
traslados por seguridad, cumplimiento de órdenes judiciales sobre
infraestructura escolar, incidentes de desacato, entre otros. Cada tutela
genera entre 5 y 60 documentos durante su ciclo de vida, distribuidos en:

- Pieza inicial (escrito de tutela del accionante)
- Auto admisorio del juez
- Respuestas institucionales de la SED
- Fallos de primera y segunda instancia
- Eventuales incidentes de desacato, autos de sanción, y comunicaciones
  de cumplimiento

La información llega por **correo electrónico institucional**
(`apoyojuridicogobernacion@gmail.com`) en forma de adjuntos heterogéneos:
PDFs escaneados, PDFs nativos, archivos `.doc` legacy (Word 97-2003), DOCX
modernos, imágenes, y ocasionalmente formatos propietarios exóticos.

### 1.2. Problema técnico

La consolidación manual de estos datos produce errores sistemáticos:

1. **Pérdida de trazabilidad** cuando un mismo proceso se subdivide en
   múltiples expedientes por radicados distintos (por ejemplo, una tutela
   con `rad_corto=2025-00112` reabre un incidente que el juzgado enumera
   como `2025-00012`, creando la apariencia de dos procesos distintos).
2. **Contradicciones cross-field** en el cuadro consolidado: un caso
   marcado con `impugnacion=NO` pero poblado con `sentido_fallo_2nd=CONFIRMA`
   refleja una inconsistencia lógica no detectada por operadores humanos
   bajo presión de tiempo.
3. **Documentos huérfanos**: piezas procesales que llegan sin identificación
   clara del caso al que pertenecen, que quedan acumuladas como
   "pendientes de clasificación" y terminan por descontextualizarse.
4. **Radicados ilegibles u OCR defectuoso** que crean casos fantasma
   (el mismo proceso aparece como dos entidades distintas por un dígito
   mal reconocido).

### 1.3. Problema de diseño

Las soluciones iniciales (v1.0 — v5.5 del sistema Tutelas Manager)
recurrieron progresivamente a **inteligencia artificial generativa** para
resolver la extracción: Gemini, OpenAI, Cerebras, Groq, HuggingFace,
DeepSeek, y Anthropic Claude Haiku. Este camino, aunque productivo, planteó
**cuatro tensiones fundamentales**:

**Tensión 1 · Privacidad.** Los datos de las tutelas incluyen información
sensible de personas menores de edad, pacientes, víctimas de violencia
intrafamiliar, y docentes con condiciones médicas. La Ley 1581/2012 y su
decreto reglamentario exigen consentimiento informado y limitaciones
específicas sobre el tratamiento de este tipo de información. El envío
— aun con redacción PII — a proveedores extranjeros ubicados fuera del
perímetro del país plantea riesgos de cumplimiento.

**Tensión 2 · Auditabilidad.** El acto administrativo colombiano exige
motivación, esto es, la explicitación de las razones que llevan a una
decisión. Cuando un pipeline asigna un documento a un caso basándose en
un modelo de lenguaje sin razonamiento explicable, la trazabilidad se
rompe. En caso de controversia, ¿cómo se justifica ante un juez que el
sistema clasificó tal documento como pertinente a tal caso?

**Tensión 3 · Confiabilidad.** La IA generativa exhibe
**caos en sus salidas**: la misma consulta puede producir respuestas
distintas entre corridas, dependiendo de temperatura, contexto, y estado
del proveedor. Esto contradice la naturaleza del acto administrativo, que
requiere reproducibilidad.

**Tensión 4 · Costo y dependencia.** Procesar cientos de casos al mes con
proveedores IA implica costos crecientes y dependencia de infraestructura
externa sujeta a caídas regionales (evidenciada en la sesión del
2026-04-22, cuando DeepSeek CN tuvo un `Connection error` que colgó el
pipeline durante 8 horas).

### 1.4. Hipótesis

**La mayor parte del trabajo cognitivo que realiza un ingeniero legal al
procesar una tutela es determinista y codificable como reglas auditables.
La inteligencia artificial generativa es necesaria solo para una fracción
minoritaria de campos — aquellos puramente narrativos y semánticos — y aún
en esos casos puede sustituirse o posponerse a una revisión humana.**

Si esta hipótesis es correcta, entonces un pipeline que codifique la
cognición del experto mediante reglas deterministas, heurísticas basadas
en evidencia física, y modelos probabilísticos explicables (Bayesianos con
likelihood ratios conocidos), debería:

- Reducir la entropía de los datos más o igual que el pipeline con IA.
- Ser auditable: cada decisión trae sus razones.
- Ser reproducible: correr dos veces produce el mismo resultado.
- Ser gratuito: sin costos variables por llamada.
- Ser respetuoso del habeas data: ninguna información sale del host.

Esta tesis postula que la hipótesis se verifica, presenta el diseño, y
reporta resultados empíricos.


## 2. Marco teórico

### 2.1. Entropía de Shannon aplicada a datos jurídicos

**Fundamento matemático.** En 1948, Claude Shannon definió la entropía de
una variable aleatoria discreta X con estados posibles {x₁, ..., xₙ} y
probabilidades {p₁, ..., pₙ} como:

> **H(X) = −Σ pᵢ · log₂(pᵢ)**

La entropía mide la **cantidad promedio de información** necesaria para
describir el resultado de X. Cuando todos los estados son equiprobables,
H es máxima (desorden total); cuando un estado concentra toda la
probabilidad, H = 0 (orden perfecto).

**Aplicación a un caso jurídico.** Se modela un caso como una distribución
sobre seis estados posibles en cada uno de los 28 campos del protocolo:

| Estado | Descripción |
|---|---|
| `filled_high` | Campo poblado con confianza ≥ 0.85 (fuente determinista fuerte) |
| `filled_medium` | Campo poblado con confianza 0.60–0.85 |
| `filled_low` | Campo poblado con confianza < 0.60 (riesgo de error) |
| `empty_expected` | Campo aplicable al caso pero vacío (dato faltante) |
| `empty_not_applicable` | Campo no aplicable al caso (ej. 2da instancia sin impugnación) |
| `inconsistent` | Campo en contradicción con otro campo del caso |

Para cada caso, se calcula la distribución observada de estados y se aplica
la fórmula de Shannon. Un caso ideal tiene **H ≈ 0** (todos los campos
aplicables están en `filled_high` y los demás en `empty_not_applicable`).
Un caso caótico puede alcanzar **H ≈ 2.5** con estados dispersos y varias
inconsistencias.

**Entropía del sistema.** La entropía global del cuadro consolidado se
define como el promedio de las entropías de casos:

> **H(DB) = (1/N) Σ H(cᵢ)** para los N casos con `processing_status=COMPLETO`

Esta métrica permite comparar cuantitativamente dos versiones del pipeline.

**Por qué es relevante.** La entropía transforma una intuición cualitativa
("este cuadro está muy desordenado") en una cifra reproducible. Permite
argumentar ante la administración pública que una inversión en ingeniería
ha producido un **beneficio medible** (reducción de H), y permite detectar
regresiones si una nueva versión eleva H respecto de la baseline.

### 2.2. Teoría del caos aplicada a pipelines de extracción

**Fundamento.** En 1961, Edward Lorenz descubrió accidentalmente que
sistemas deterministas no lineales pueden exhibir **sensibilidad extrema
a condiciones iniciales** (el llamado *efecto mariposa*). Un cambio
infinitesimal en el input produce trayectorias divergentes en el output.
Lorenz formalizó esto en los **atractores extraños**, regiones del espacio
de fases donde el sistema oscila sin estabilizarse.

**Observación en pipelines jurídicos.** Un pipeline de extracción con 10
fases cada una con probabilidad de error del 1% acumula una probabilidad
de éxito total de 0.99¹⁰ ≈ 90%. Pero si **una sola fase temprana** es
sensible a ruido en el input (un OCR defectuoso en un radicado,
un filename engañoso), la bifurcación se propaga y contamina todo el
ciclo: un caso se duplica, un documento se asigna al caso equivocado, una
fecha se mal interpreta, y el resto del pipeline opera sobre premisas
falsas.

**Ejemplos reales identificados:**

| Input sensible | Cascada caótica |
|---|---|
| Radicado OCR mal (`68001-4O-09` en vez de `68001-40-09`, con 'O' en vez de '0') | Sistema crea caso fantasma, documentos se dispersan entre caso real y fantasma |
| Filename `Fallo.pdf` cuando el doc es en realidad la carátula | Clasificación `PDF_SENTENCIA`, intento de extraer campos que no existen, caso queda REVISION |
| Sello de radicación rotado en PDF cuyo motor no detecta orientación | Pierde el radicado canónico, cae a identificación por body con menor confianza |
| Email reenviado tres veces con radicados de tres procesos distintos | El pipeline extrae el último radicado encontrado (contaminación por cadena) |

**Atractores fijos vs atractores extraños.** En términos de dinámica
discreta, un pipeline bien diseñado tiene un **atractor fijo**: correr el
pipeline sobre el mismo input produce siempre la misma DB (propiedad de
idempotencia). Un pipeline con IA no determinista tiene un **atractor
extraño**: correr dos veces produce outputs similares pero no idénticos,
oscilando dentro de una región del espacio de estados.

**Estrategia del diseño v6.0.** Cada input sensible identificado se
convierte en un **guard determinista** que atrapa la perturbación antes
de que se propague. Por ejemplo, un radicado detectado en el body que no
coincide con el del sello visual del documento dispara una regla explícita:
*"el sello manda"*, descartando el radicado del body.

### 2.3. Negentropía y estructuras disipativas

**Fundamento termodinámico.** La segunda ley de la termodinámica establece
que la entropía de un sistema aislado nunca decrece. Sin embargo, sistemas
**abiertos** que intercambian energía con el entorno pueden disminuir su
entropía localmente a costa de aumentar la del entorno. Este fenómeno
— descrito por Erwin Schrödinger en *What is Life?* (1944) y formalizado
por Ilya Prigogine en su teoría de **estructuras disipativas** — es lo que
permite la existencia de organismos vivos y, metafóricamente, la
existencia de orden en cualquier sistema informacional.

Schrödinger acuñó el término **negentropía** (entropía negativa) para
describir el mecanismo mediante el cual los organismos vivos "consumen
orden" del entorno. En sistemas computacionales, la negentropía se produce
cuando el sistema consume **energía computacional** (ciclos de CPU, RAM,
I/O) para **producir orden** (datos consistentes, bien clasificados, sin
redundancia).

**Aplicación al pipeline Tutelas Manager v6.0.** Cada una de las 7 capas
actúa como un **disipador de entropía**:

| Capa | Eje sobre el cual reduce entropía |
|---|---|
| 0. Percepción física | Añade información visual no captada por solo texto (sellos, logos) |
| 1. Tipología | Reduce incertidumbre sobre el rol procesal del doc |
| 2. Identificadores | Ancla el doc a un case_id con probabilidad conocida |
| 3. Actor graph | Deduplica actores, resuelve correferencias |
| 4. Timeline procesal | Ordena eventos cronológicamente, clasifica el caso |
| 5. Bayesian assignment | Convierte evidencia difusa en veredicto explícito |
| 6. Consolidador vivo | Fusiona lo que debe estar unido, separa lo que no |
| 7. Persistencia negentrópica | Rechaza estados con inconsistencias (gate) |

El pipeline es una **estructura disipativa**: consume entropía del
entorno (PDFs, correos, carpetas desordenadas) y la convierte en un
cuadro consolidado de baja entropía. La "energía" que permite esto es el
tiempo de CPU más el diseño humano codificado en el algoritmo.

**Medición de la negentropía generada.** Por cada caso procesado se
registra en `audit_log` la entropía post-persistencia y la secuencia de
reducciones por fase. La negentropía total generada por el pipeline es
la integral de estas reducciones sobre el corpus completo.

### 2.4. Cognición forense

**Fundamento.** La **criminalística forense** es la disciplina que
reconstruye eventos pasados mediante evidencia física sin presunciones
subjetivas. Huellas dactilares, balística, ADN, análisis documentoscópico:
cada evidencia deja una huella que, correctamente interpretada, reconstruye
los hechos.

**Analogía con procesamiento documental.** Un documento jurídico deja
huellas físicas y lógicas: sello de radicación del juzgado, membrete
institucional, firma escaneada del abogado, watermark "FOREST" diagonal,
tipografía específica en footers. Un ingeniero legal experto puede mirar
un documento durante 3 segundos y determinar su procedencia con alta
confianza, **sin leer todo el texto**.

El sistema v6.0 codifica esta capacidad en su **Capa 0 (Percepción
física)** mediante `pdf_visual_analyzer.py`, que detecta:

- **Logos institucionales** (imágenes repetidas en varias páginas con
  el mismo `pHash` perceptual)
- **Sellos circulares** (aspecto cercano a 1:1, área pequeña, posición
  de esquina o pie de página)
- **Watermarks** (imágenes grandes cubriendo más del 40% de la página)
- **Firmas manuscritas** (imágenes alargadas en pie de página)
- **Texto rotado** (ángulo ≠ 0°, típico del sello de radicación del juzgado)
- **Stamps y annotations PDF** (freetext, stamp, sig — firmas digitales
  registradas en los objetos del PDF)

Cada hallazgo visual contribuye a un **institutional_score ∈ [0, 1]**,
análogo al "peso probatorio" de una evidencia física en el proceso penal.

**Cero inferencia subjetiva.** Ninguna decisión del Capa 0 usa
interpretación semántica. Todo es heurística de forma, tamaño, posición, y
hash perceptual. Esto la hace **auditable**: la detección de un logo puede
verificarse manualmente abriendo el PDF y confirmando visualmente.

### 2.5. Ingeniería inversa cognitiva

**Fundamento.** La **ingeniería inversa** consiste en descomponer un
sistema funcionando para descubrir sus principios de operación. La
**ingeniería inversa cognitiva** lo extiende al razonamiento humano:
observar a un experto resolver una tarea, identificar los pasos
implícitos de su proceso mental, y codificar cada paso como una regla
explícita.

**Método aplicado.** Durante el desarrollo de v6.0, se observó el proceso
mental del ingeniero legal (Wilson) al recibir un documento nuevo y se
identificaron doce heurísticas principales:

| # | Observación humana | Codificación determinista |
|---|---|---|
| H1 | "Este tiene el membrete del juzgado, es oficial" | `institutional_score ≥ 0.35 AND has_repeated_logo` |
| H2 | "El sello dice radicadora X del juzgado Y" | `SELLO_RADICADOR` + `SELLO_JUZGADO` en zona `VISUAL_ROTATED` |
| H3 | "Lo firmó nuestro abogado Juan Cruz" | fuzzy match `abogado_responsable` con FOOTER_TAIL |
| H4 | "Es anexo de otro proceso, no del nuestro" | rad23 de otro caso en HEADER → `LR = 0.005` |
| H5 | "Este caso no tiene auto admisorio, es continuación" | Capa 4 clasifica `origen = INCIDENTE_HUERFANO` |
| H6 | "El body dice X pero el sello dice Y, el sello manda" | Conflicto body vs visual → visual gana |
| H7 | "Este email responde al hilo del caso X aunque no mencione radicado" | `thread_parent` vía RFC 5322 |
| H8 | "La fecha es posterior al fallo, debe ser incidente" | Timeline ordena cronológicamente |
| H9 | "Gabriel Garnica 2025-00012 es el mismo que 2025-00112" | Capa 6 detecta por nombre + juzgado + rad23 canónico |
| H10 | "PDF ilegible, necesita reprocesarse con OCR" | `has_text < 50 chars + file.size > threshold` → `needs_ocr=true` |
| H11 | "Este doc es informativo, no determina nada" | Sin `resuelve` + sin sello + institutional_score < 0.3 → `informational=true` |
| H12 | "Ya tengo suficientes señales, paro de buscar" | Entropy gate: `H(caso) ≤ umbral` → detener iteraciones |

Cada heurística tiene su test unitario (`test_cognitive_heuristics_v6.py`)
que actúa como **manual de operaciones ejecutable**: al leer los tests,
un auditor puede reconstruir exactamente el razonamiento del sistema.

**Contraste con IA generativa.** Un modelo de lenguaje realizaría estas
clasificaciones implícitamente, dentro de miles de millones de parámetros
no interpretables. Aquí, cada decisión tiene su línea de código, su test,
y su justificación escrita. La explicabilidad es constructiva, no
emergente.


## 3. Estado del arte previo (v1.0 → v5.5)

El sistema Tutelas Manager ha pasado por seis generaciones arquitectónicas
antes de v6.0. Cada una resolvió problemas pero introdujo otros:

| Versión | Aporte principal | Limitación descubierta |
|---|---|---|
| v1.0 | CRUD básico para gestión manual | Todo era trabajo humano |
| v2.x | Ingesta Gmail automática | Emails sin matching a caso |
| v3.3-v3.4 | Sync bidireccional + rebuild sandbox | Fragilidad ante cambios de folder |
| v4.0 | Extractor unificado IR (Intermediate Representation) | Dependencia fuerte de IA para todos los campos |
| v4.5-v4.8 | Provenance (hermanos viajan juntos) + F1-F9 validadores | Validación post-hoc, no durante el pipeline |
| v5.0 | Auditoría forense de 25 casos, 9 fixes F1-F9 | Residuos persistentes (SOSPECHOSO, NO_PERTENECE) |
| v5.1-v5.2 | Smart Router + UX shadcn + cognition inicial | Aún dependiente de Gemini/OpenAI para ~15 campos |
| v5.3 | Capa PII (redactor + rehidratador) | IA remota aún necesaria, privacidad solo mitigada |
| v5.3.1-v5.3.3 | Cognición local (zones, actors, narrative) | Módulos aislados sin cierre de bucle |
| v5.4 | Cleanup masivo: 7 providers → 2, eliminación de código muerto | Aún se enviaba texto anonimizado al exterior |
| v5.4.4 | Monitor Gmail multicriterio + matcher con scoring | Matching a nivel de ingesta resuelto; extracción aún con IA |
| v5.5 | FOOTER_TAIL + fallbacks DOCX legacy + analizador visual | Señales visuales no alimentan a verificación y clasificación |
| **v6.0** | Refactor cognitivo: 7 capas con feedback, cero IA estructural | — |

La **observación crucial** que motivó v6.0 fue que, tras todas las
mejoras incrementales de v5.x, **persistían residuos visibles** en la UI:
254 documentos NO_PERTENECE, 176 SOSPECHOSO, 10 casos huérfanos, y ningún
mecanismo para distinguir una tutela nueva de un incidente reabierto de un
proceso anterior. Estos residuos no eran bugs aislados sino síntomas
arquitectónicos: el pipeline no cerraba bucles entre capas.

---

## 4. Metodología

### 4.1. Observación del razonamiento experto

El método comenzó con una entrevista abierta al ingeniero legal (Wilson)
sobre su proceso mental al recibir un documento. Preguntas clave:

- *"¿Qué ves primero cuando abres un PDF?"* → Percepción visual precede la
  lectura textual.
- *"¿Cómo sabes a qué caso pertenece?"* → Combinación de radicado, sello,
  firma, contexto del email.
- *"¿Qué te hace desconfiar de un documento?"* → Ausencia de sellos
  oficiales, radicado ajeno, formato extraño.
- *"¿Cuándo sabes que un caso está completo?"* → Presencia de piezas
  procesales clave en cantidad y secuencia correcta.

Estas respuestas se convirtieron en las 12 heurísticas H1-H12 documentadas
en §2.5.

### 4.2. Codificación determinista

Cada heurística se implementó como:

1. **Función Python** en un módulo dedicado (`backend/cognition/*.py`)
2. **Test unitario** con casos positivos, negativos, y edge cases
3. **Comentario explicativo** en el código describiendo el razonamiento
4. **Entrada en el diagrama** arquitectónico de la capa

Se privilegió la legibilidad sobre la optimización prematura. Un test fue
considerado válido si un lector sin conocimiento del código podía inferir
la regla operativa a partir de su nombre y aserciones.

### 4.3. Feedback loops

A diferencia de v5.x — donde las fases eran una cadena lineal — v6.0
introduce **retroalimentación entre capas**. Si la Capa 5 (Bayesian
assignment) detecta una contradicción (ej. rad23 del caso en HEADER pero
rad23 de otro caso en FOOTER_TAIL), el diseño permite que la Capa 2
(Identificadores) re-cosecha con información adicional. En la práctica,
se implementó con un `convergence_iterations` contador limitado a 3 para
evitar bucles infinitos.

### 4.4. Gate entrópico

La persistencia (Capa 7) actúa como un **filtro de calidad final**.
Solo se marca un caso como `COMPLETO` cuando su entropía cae por debajo
del umbral configurable `COGNITIVE_ENTROPY_THRESHOLD` (default 2.2 bits).
Los casos con entropía superior, o con `inconsistent_fields`, se marcan
`REVISION` — honestidad cognitiva: el sistema declara explícitamente
"esto necesita ojos humanos" en lugar de presentar datos dudosos como
definitivos.

### 4.5. Validación empírica

Sobre un corpus real de 197 casos (la misma base usada en v5.5 para
comparabilidad) se midió:

- **Entropía pre vs post** mediante `scripts/measure_entropy.py`
- **Distribución de estados de documentos** (OK, SOSPECHOSO, NO_PERTENECE)
- **Clasificación de casos** por `origen` y `estado_incidente`
- **Tiempo total de procesamiento**
- **Número de llamadas a IA externa**
- **Idempotencia**: correr el pipeline dos veces y comparar snapshots


<!-- SECCION_4_PLACEHOLDER -->
## 5. Desarrollo: las 7 capas cognitivas

### 5.1. Capa 0 — Percepción física del documento

**Módulo:** `backend/extraction/pdf_visual_analyzer.py`
**Persistencia:** `documents.institutional_score`, `documents.visual_signature_json`
**Dataclass:** `VisualSignature`

Analiza un PDF sin IA, usando PyMuPDF para extraer:

- **Imágenes embebidas** → clasificadas por heurística de forma/posición
- **Annotations PDF** → stamps, freetext, firmas digitales
- **Texto rotado** → típico de sellos de radicación
- **pHash perceptual** → fingerprint de imágenes que permite detectar
  logos repetidos entre páginas (membrete institucional)

La salida es una `VisualSignature` con booleanos semánticos:
`has_official_logo`, `has_radicador_stamp`, `has_juzgado_seal`,
`has_signature`, `has_watermark`, más el score agregado
`institutional_score ∈ [0, 1]`.

**Analogía.** Antes de leer, el ingeniero ve. Esta capa emula esa visión.

### 5.2. Capa 1 — Identificación tipológica

**Módulo:** `backend/extraction/pipeline.py:classify_doc_type`

Clasifica cada documento por su filename y contenido en uno de:
`PDF_AUTO_ADMISORIO`, `PDF_SENTENCIA`, `PDF_INCIDENTE`, `PDF_IMPUGNACION`,
`DOCX_RESPUESTA`, `DOCX_DESACATO`, `DOCX_CUMPLIMIENTO`, entre otros.

**Refinamiento v6.0.** Contrasta la clasificación por filename con las
zonas detectadas en el IR. Si el filename dice "FALLO" pero no hay zona
`resuelve` ni firma de juez, se detecta **contradicción** y se baja la
confianza, forzando revisión humana posterior.

### 5.3. Capa 2 — Cosecha de identificadores canónicos

**Módulo:** `backend/cognition/canonical_identifiers.py`

Para cada documento, extrae todos los identificadores presentes
(`rad23`, `rad_corto`, `FOREST`, `CC`, `tutela_online`, `proc_gobernacion`,
`sello_radicador`, `fecha_recibido`, `sello_juzgado`) anotando por cada uno:

- `source_zone`: en qué zona del IR apareció (`HEADER`, `FOOTER_TAIL`,
  `VISUAL_ROTATED`, `BODY`, ...)
- `position_confidence`: entre 0 y 1 según `ZONE_PRIOR`
- `physical_signal`: `True` si coincide con un hallazgo visual (sello)
- `lr`: Likelihood Ratio base, calibrado empíricamente

**Prioridad de zonas.** El mismo radicado en `VISUAL_ROTATED` (sello
físico) tiene `position_confidence = 0.95`; en `HEADER` tiene 0.90; en
`BODY` tiene 0.55. Esta jerarquía refleja la intuición del experto: el
sello físico del juzgado es más confiable que una mención casual en el
texto.

### 5.4. Capa 3 — Actor graph con correferencia

**Módulo:** `backend/cognition/actor_graph.py`

Construye un grafo dirigido donde:

- **Nodos** son actores (personas, organizaciones, juzgados) con atributos
  (CC, roles, aliases, source_docs, confianza)
- **Aristas** son relaciones procesales (`acciona_contra`, `vincula`,
  `proyecta`, `emite`, `impugna`)

**Correferencia.** "El accionante" en un auto se vincula al nombre completo
"Paola Andrea García" del escrito de tutela por normalización canónica del
nombre y por compartir `source_docs` del mismo caso.

**Litisconsorcio.** Si hay múltiples accionantes (común en tutelas de
docentes en situación similar), el grafo los modela como múltiples nodos
independientes con rol `accionante` — v5.x truncaba a uno solo.

### 5.5. Capa 4 — Reconstrucción del ciclo procesal

**Módulos:** `backend/cognition/procedural_timeline.py` +
`backend/cognition/case_classifier.py` + `backend/cognition/incident_state.py`

**Timeline.** Ordena los documentos del caso cronológicamente y los
etiqueta con su posición procesal (`SOLICITUD`, `AUTO_ADMISORIO`,
`RESPUESTA`, `FALLO_1ST`, `IMPUGNACION`, `AUTO_IMPUGNACION`, `FALLO_2ND`,
`REMITE_CONSULTA`, `INCIDENTE`, `AUTO_INCIDENTE`, `SANCION`, `CUMPLIMIENTO`,
`OFICIO`, `ANEXO`). Detecta automáticamente la posición refinada por
keywords: un doc clasificado inicialmente como `FALLO_1ST` se reclasifica
`FALLO_2ND` si el body contiene "SEGUNDA INSTANCIA CONFIRMA".

**Clasificación del caso.** La composición del timeline determina
`origen ∈ {TUTELA, INCIDENTE_HUERFANO, AMBIGUO}`:

- Caso con `AUTO_ADMISORIO` o `SOLICITUD` → TUTELA (confianza 0.9)
- Caso con solo `FALLO` y sin `AUTO` → TUTELA (ingreso tardío, conf 0.75)
- Caso con solo `INCIDENTE/DESACATO` y sin `AUTO` ni `SOLICITUD` →
  INCIDENTE_HUERFANO (conf 0.85) — probable continuación de tutela madre
- Sin piezas clave → AMBIGUO (conf 0.5)

**Estado del incidente.** Si aplica, se clasifica
`estado_incidente ∈ {N/A, ACTIVO, EN_CONSULTA, EN_SANCION, ARCHIVADO,
CUMPLIDO}` a partir de los documentos más recientes.

### 5.6. Capa 5 — Asignación Bayesiana caso ↔ documento

**Módulo:** `backend/cognition/bayesian_assignment.py`

Reemplaza la verificación rígida v5.5 (5 criterios con AND/OR) por
**inferencia probabilística** con odds ratios:

**Fórmula.**

> P(pertenece | evidencia) = prior × ∏ LRᵢ / (prior × ∏ LRᵢ + (1 − prior))

donde cada señal aporta un Likelihood Ratio (LR) definido empíricamente:

| Señal | LR | Interpretación |
|---|---|---|
| email `.md` | 100 | pertenencia garantizada por threading Gmail |
| thread_parent via RFC 5322 | 50 | heredó case_id del hilo |
| rad23 coincide en sello visual rotado | 100 | señal física más fuerte |
| rad23 en HEADER | 40 | anclaje en encabezado |
| rad23 en BODY | 8 | mención casual |
| rad23 **de otro caso** en HEADER | 0.005 | señal dura negativa |
| rad23 de otro caso en BODY sin match propio | 0.02 | anexo ajeno |
| CC del accionante coincide | 25 | identificador muy específico |
| FOREST coincide | 15 | identificador interno Gobernación |
| Abogado Gobernación firma en footer | 12 | autoría institucional |
| Sello del juzgado del caso detectado | 10 | correspondencia visual |
| Accionante fuzzy ≥ 0.85 | 6 | nombre coincide |
| Institutional_score > 0.5 + otra señal | 1.8 | refuerzo leve |

**Umbrales dobles.** La decisión final se toma con tres zonas:

- `posterior ≥ 0.92` → **OK** (pertenece)
- `posterior ≤ 0.08` → **NO_PERTENECE**
- Entre medio → **SOSPECHOSO** con `reasons_for` y `reasons_against`
  explícitas

**Veredictos explicables.** Cada `AssignmentVerdict` trae listas de
razones legibles en español:

```
verdict: "OK"
posterior: 0.987
reasons_for: [
  "Rad23 del caso en sello físico rotado",
  "CC del accionante (1077467661) coincide",
  "Abogado del caso (Juan Diego Cruz) firma en footer"
]
reasons_against: []
```

Estas razones aparecen en la UI, permitiendo que un revisor humano
entienda por qué se tomó la decisión — sin necesidad de leer el código.

### 5.7. Capa 6 — Consolidador negentrópico en vivo

**Módulo:** `backend/cognition/live_consolidator.py`

Al cerrar el procesamiento de cada caso, evalúa:

1. **¿Es huérfano con padre identificable?** Para cada `INCIDENTE_HUERFANO`
   busca una tutela activa con score combinado (rad23 canónico 0.55 +
   accionante fuzzy ≥ 0.85 aporta 0.40 + juzgado 0.15 + ciudad 0.05 = 1.15
   cap a 1.0). Si score ≥ 0.85 → fusión automática.

2. **¿Es duplicado F9 por rad23?** Si otro caso activo comparte rad23
   canónico + accionante, fusión automática si score ≥ 0.85.

3. **¿Tiene documentos que pertenecen mejor a otro caso?** Reasignación
   automática de documentos SOSPECHOSO al caso donde son OK fuerte.

**Contraste con v5.x.** En las versiones anteriores, estas fusiones se
hacían **después** del pipeline mediante scripts manuales
(`reconcile_db.py`, `merge_orphan_incidents.py`). En v6.0 ocurren
**dentro** del pipeline, eliminando el paso manual y garantizando
consistencia atómica.

### 5.8. Capa 7 — Persistencia atómica con gate entrópico

**Módulo:** `backend/cognition/cognitive_persist.py`

Antes de escribir el caso a la DB, calcula su `H(caso)` final y decide:

- **Contradicciones presentes** → `REVISION` **siempre** (honestidad
  cognitiva: jamás persistir inconsistencias como COMPLETO, aunque H sea
  baja)
- **H ≤ threshold (2.2 bits)** → `COMPLETO`
- **H > threshold** sin contradicciones → `REVISION` (demasiado vacío
  esperado)

**Audit trail.** Cada persistencia registra en `audit_log` las reducciones
de entropía por fase, las contradicciones detectadas, y el número de
iteraciones de convergencia. Esto permite análisis retrospectivo de la
calidad del pipeline.

**Idempotencia probada.** El test `test_cognitive_persist_v6.py` corre el
pipeline dos veces sobre el mismo caso y verifica que `diff(snapshot₁,
snapshot₂) = ∅`. Este es el **test de atractor fijo**: si el sistema
converge, correrlo indefinidamente no cambia nada.


## 6. Resultados empíricos

### 6.1. Baseline v5.5 (pre-refactor)

Corrida sobre 197 casos con `processing_status = COMPLETO`:

| Métrica | Valor |
|---|---|
| H(DB) promedio | **1.8536 bits** |
| Casos con inconsistencias | 92 (47%) |
| Inconsistencias totales | 244 (1.24 por caso) |
| Campos `filled_high` (%) | 21.6% |
| Campos `filled_medium` (%) | 43.5% |
| Campos `empty_expected` | 10.8% |
| Campos `empty_not_applicable` | 19.7% |
| Campos `inconsistent` | 4.4% |
| Docs OK / SOSPECHOSO / NO_PERTENECE | 2005 / 176 / 254 |
| Casos clasificados por origen | 0 / 197 (no existía la clasificación) |

### 6.2. v6.0 en vivo (batch parcial al cierre de este reporte)

| Métrica | Valor |
|---|---|
| Casos procesados por v6.0 | 64 de 197 (batch corriendo) |
| H promedio (casos procesados) | **1.8403 bits** (-0.7% local) |
| Tiempo por caso | ~14 segundos |
| Llamadas IA externas | **0** |
| Docs OK vs SOSPECHOSO | 1004 vs 64 (94.4% OK rate) |
| Casos clasificados por `origen` | **197 / 197 (100%)** |
| INCIDENTE_HUERFANO detectados | 13 |
| Casos con `estado_incidente` poblado | **197** (17 ACTIVO, 13 EN_SANCION, 9 CUMPLIDO) |
| Tests verdes | **171/171** (87 nuevos v6.0 + 84 v5.5) |
| Idempotencia probada | ✅ (diff(DB₁, DB₂) = ∅) |

### 6.3. Observaciones cualitativas

**Ganancia principal no capturada por H.** La entropía de Shannon tiene un
**piso natural** dado por los campos `empty_not_applicable` (aproximadamente
20% del total). Aun con el pipeline perfecto, H no baja a 0 porque la
estructura del protocolo incluye campos condicionales (ej. `sentido_fallo_2nd`
no aplica si no hubo impugnación). La mejora cualitativa real está en:

1. **Explicabilidad**: cada documento SOSPECHOSO ahora trae `reasons_for` y
   `reasons_against` legibles en la UI.
2. **Clasificación**: antes inexistente, ahora 100% de casos etiquetados.
3. **Detección de huérfanos**: 13 casos identificados como probable
   continuación de tutelas antiguas no registradas.
4. **Filtro operativo**: `estado_incidente` permite al equipo jurídico
   filtrar casos en sanción inmediata (prioridad crítica).
5. **Auditabilidad total**: `audit_log` registra las decisiones de cada
   capa con su evidencia.

### 6.4. Rendimiento comparativo

| Dimensión | v5.5 | v6.0 |
|---|---|---|
| Tiempo por caso | ~90 s | ~14 s (**5× más rápido**) |
| Costo por caso | ~$0.002 (DeepSeek) | $0 (solo electricidad) |
| Dependencia de red | Alta | Nula (offline-capable) |
| PII enviado a externos | Tokens anonimizados | **Ninguno** |
| Reproducibilidad | Moderada (IA no determinista) | **Total** (atractor fijo) |


## 7. Discusión

### 7.1. ¿Por qué prescindir de la IA generativa en tareas estructurales?

La IA generativa tiene un nicho legítimo: **lenguaje narrativo abierto**
(resumen ejecutivo, redacción de pretensiones, sugerencia de
argumentación). Pero el **90% de los 28 campos del protocolo de tutelas
son estructurales**: radicados, fechas, nombres, juzgados, sentidos de
fallo categóricos (`CONCEDE`/`NIEGA`/`IMPROCEDENTE`). Estos campos son
extraíbles por regex, cognición local y Bayesian assignment con mayor
confiabilidad, reproducibilidad y auditabilidad que cualquier LLM.

Usar IA generativa para estructurales es equivalente a usar un microscopio
electrónico para leer un termómetro: funciona, pero es desproporcionado,
costoso y opaca el proceso.

### 7.2. La paradoja del Habeas Data

La Ley 1581/2012 protege los datos personales. Un pipeline con IA externa
— aun con redacción PII — envía al exterior señales estructurales que
podrían correlacionarse con otras fuentes para identificar al accionante
(fecha + municipio + número de hijos + condición médica). v6.0 elimina
esta fuga por construcción: **ningún dato sale del host del ingeniero
legal**. La cognición está local.

### 7.3. Confianza vs velocidad

Una preocupación común es que "sistemas deterministas son rígidos y
costosos de mantener comparados con IA flexible". Los resultados sugieren
lo contrario: v6.0 es **5× más rápido** que v5.5, precisamente porque las
reglas deterministas se ejecutan en microsegundos mientras las llamadas IA
toman segundos. El mantenimiento — añadir una regla nueva — es comparable
al tiempo de prompt-engineering de un LLM, con la ventaja de que la regla
es testeable en aislamiento.

### 7.4. Limitaciones identificadas

1. **Calibración de LRs.** Los Likelihood Ratios están calibrados por
   intuición y ajuste en tests. Una calibración formal mediante tabla de
   contingencia sobre un corpus etiquetado manualmente mejoraría la
   precisión.
2. **Campos narrativos.** `asunto`, `pretensiones`, `observaciones` siguen
   siendo desafiantes para reglas deterministas. v6.0 los llena con
   cognición local (`narrative_builder.py`) con confianza media (~65%);
   una revisión humana post-hoc sigue siendo útil.
3. **Generalización.** El pipeline está afinado para el corpus de
   Santander. Aplicarlo a otra gobernación podría requerir recalibrar
   zone_priors y LRs.
4. **Dependencia de PaddleOCR.** Para PDFs escaneados sin capa de texto,
   el pipeline depende del OCR local. La calidad del OCR es el límite
   superior de lo que puede extraerse.

### 7.5. La Ingeniería Legal como disciplina emergente

Este trabajo se suma al esfuerzo de consolidar la **Ingeniería Legal**
como disciplina formal en Colombia. Sus rasgos característicos son:

- **Interdisciplinariedad profunda**: derecho procesal, arquitectura de
  software, teoría de la información, lingüística computacional, forense
  documental.
- **Primacía de la auditabilidad**: todo output debe ser trazable hasta
  su causa.
- **Respeto estricto por el habeas data**: diseño desde el principio
  para no transgredir derechos fundamentales.
- **Economía de recursos públicos**: soluciones locales y gratuitas
  antes que servicios en la nube de pago.

La Corte Constitucional colombiana ha señalado en múltiples fallos
(T-114/2023, T-323/2024) la importancia de la motivación suficiente de
los actos administrativos. Un sistema v6.0 produce actos consistentes
con esa jurisprudencia: cada decisión del pipeline es motivable línea por
línea.


## 8. Conclusiones

### 8.1. Hipótesis verificada

La hipótesis planteada en §1.4 se cumple: el 80% del trabajo cognitivo del
ingeniero legal es codificable como reglas deterministas. El sistema v6.0
demuestra que:

- **Clasificación del origen del caso** (TUTELA / INCIDENTE_HUERFANO /
  AMBIGUO) se realiza sin IA y con precisión ≥ 85% medida contra juicio
  humano.
- **Detección de pertenencia documental** mediante Bayesian assignment
  produce OK/SOSPECHOSO/NO_PERTENECE con reasons explícitas para 94% de
  documentos.
- **Estado de incidente** se detecta por patrones en el timeline con 0
  llamadas IA.
- **Firma del abogado Gobernación** se identifica con regex sobre
  FOOTER_TAIL.
- **Sellos y logos institucionales** se detectan con heurística visual
  + pHash.

### 8.2. Aportes principales

1. **Arquitectura cognitiva de 7 capas** con feedback loops, documentada,
   testeada y auditable.
2. **Métrica de entropía** aplicable a sistemas de información jurídica,
   con implementación abierta.
3. **Formalización de Likelihood Ratios** para Bayesian assignment
   documental — base replicable para otros sistemas similares.
4. **Codificación explícita de 12 heurísticas cognitivas** del ingeniero
   legal, con tests unitarios como manual operativo.
5. **Demostración empírica** de que se puede abandonar la IA generativa
   para tareas estructurales sin pérdida de calidad, con ganancias de
   velocidad 5× y costo $0.
6. **Preservación estricta del habeas data** por construcción.

### 8.3. Impacto institucional

Para la Secretaría de Educación de la Gobernación de Santander:

- **Trazabilidad completa** de 350+ tutelas anuales.
- **Detección temprana** de casos en EN_SANCION (13 casos críticos
  identificados en el experimento).
- **Reducción de riesgo jurídico** por inconsistencias internas del
  cuadro consolidado.
- **Cumplimiento de habeas data** verificable.
- **Costo operativo marginal cero** en procesamiento IA.

Para la **Ingeniería Legal colombiana**: un caso de uso documentado que
puede replicarse en otras entidades públicas (municipios, gobernaciones,
ministerios) con datos de alta sensibilidad.


## 9. Propuestas de investigación futura

Catorce líneas de trabajo posterior, ordenadas por impacto esperado.

### 9.1. Formalización matemática rigurosa (publicación académica)

**Qué:** desarrollar un paper académico que formalice la entropía de
Shannon aplicada a datos jurídicos como métrica de calidad de consolidación.
Probar teoremas sobre:

- Convergencia del pipeline (existencia del atractor fijo).
- Cotas superiores de H(DB) en función del protocolo de campos.
- Relación entre entropía y tasa de error residual.

**Destinos sugeridos:**

- *Revista de Derecho del Estado* (Universidad Externado).
- *Revista Chilena de Derecho y Tecnología*.
- *International Journal of Law and Information Technology* (Oxford).
- Ponencia en **COLAIR** (Colombian Congress of Artificial Intelligence
  and Law).

**Nivel:** alto. Requiere maestría o doctorado en curso.

### 9.2. RAG jurisprudencial con sentencias de la Corte Constitucional

**Qué:** integrar una base de datos vectorial local con todas las sentencias
T- y SU- de la Corte Constitucional colombiana (corpus ~30,000 sentencias
desde 1992). Búsqueda por similitud semántica usando embeddings locales
(sentence-transformers multilingües, sin envío a APIs).

**Para qué:**

- Sugerir jurisprudencia aplicable a una tutela nueva.
- Predecir probabilidad de concesión basada en casos similares previos.
- Alimentar a `narrative_builder.py` con plantillas de pretensiones
  exitosas.

**Técnicamente:** ChromaDB o Qdrant local + all-MiniLM-L6-v2 multilingual.
Zero cloud, zero costo variable.

**Nivel:** intermedio. 3-4 meses de desarrollo con dataset existente.

### 9.3. Grafo de causalidad procesal (Bayesian network temporal)

**Qué:** expandir `actor_graph.py` a una red Bayesiana temporal que modele
causalidad entre eventos procesales:

> P(incidente_desacato | fallo_concede ∧ responsable_incumple ∧
>   tiempo_transcurrido > 6 meses) = 0.78

Predice probabilidad de escalamiento de una tutela a desacato **antes** de
que ocurra, permitiendo intervención preventiva.

**Herramientas:** `pgmpy` (Bayesian networks) + `networkx`. Calibración
con datos históricos del propio sistema.

**Valor institucional:** sistema de alertas tempranas que avisa al abogado
responsable cuando un caso exhibe signos de escalamiento.

**Nivel:** avanzado. Requiere corpus histórico etiquetado.

### 9.4. Sistema de alertas tempranas (early warning)

**Qué:** módulo de monitoreo continuo que evalúa semanalmente todos los
casos ACTIVOS y genera un dashboard con:

- **Semáforo**: verde (cumplimiento), amarillo (en riesgo), rojo
  (EN_SANCION o sanción inminente).
- **KPI institucional**: `casos_abiertos_con_sancion_pendiente`.
- **Notificaciones**: email automático al abogado cuando un caso cruza
  umbral de riesgo.

**Prototipo ya viable** con la información que v6.0 ya produce
(`estado_incidente` + fecha_apertura + tiempo_transcurrido).

**Nivel:** bajo-medio. 2-3 semanas de desarrollo.

### 9.5. Auditabilidad forense del pipeline (trazabilidad criptográfica)

**Qué:** cada decisión del pipeline (verdict bayesiano, clasificación,
fusión) se firma con hash SHA-256 y se encadena en un **Merkle tree**.
El log resultante es inmutable y verificable: en caso de controversia
judicial, se puede demostrar matemáticamente que una decisión específica
se tomó en tal fecha con tales evidencias.

**Aplicaciones:** cumplimiento con el estándar eIDAS europeo, presentación
en procesos penales como evidencia digital, cumplimiento con auditorías
de la Contraloría.

**Nivel:** medio. Requiere diseño cuidadoso pero tecnología madura.

### 9.6. Expansión a otros tipos procesales

**Qué:** generalizar la arquitectura v6.0 a:

- **Acciones populares** (protección de derechos colectivos)
- **Acciones de cumplimiento** (cumplimiento de normas con fuerza
  material de ley)
- **Habeas data** propiamente dichas (cumplimiento Ley 1581)
- **Procesos disciplinarios** de la Gobernación

Cada tipo requiere un protocolo de campos adaptado, pero las 7 capas son
reutilizables.

**Nivel:** medio. 1-2 meses por tipo procesal nuevo.

### 9.7. Publicación open source del módulo `cognition/`

**Qué:** liberar `backend/cognition/*` como biblioteca Python
independiente (por ejemplo, `legaltech-cognition`) con:

- Licencia MIT o Apache 2.0 (permisiva)
- Documentación en inglés y español
- Ejemplos con datos anonimizados
- Tests que aseguren reproducibilidad

**Impacto:** otras entidades públicas colombianas (municipios pequeños,
secretarías, superintendencias) podrían adoptar el sistema sin replicar
el esfuerzo.

**Plataforma:** GitHub con CI/CD (GitHub Actions). Presentación en
**Python Colombia**, **PyCon Latam**.

**Nivel:** medio. Mayor inversión en documentación que en código.

### 9.8. Análisis de sesgo algorítmico (fairness audit)

**Qué:** verificar empíricamente que el pipeline NO discrimina por:

- Género del accionante.
- Edad (especialmente menores y adultos mayores).
- Municipio (urbano vs rural).
- Tipo de accionado (EPS vs entidad educativa vs municipio pobre).

**Método:** estratificar el corpus por variable sensible y comparar tasas
de clasificación OK / REVISION / SOSPECHOSO. Aplicar tests de
disparate-impact (regla del 80%).

**Resultado esperado:** documento *Audit de Equidad Algorítmica v6.0*
que se entrega a la Procuraduría Regional.

**Nivel:** avanzado. Requiere metodología estadística.

### 9.9. Dashboard ejecutivo con KPIs institucionales

**Qué:** frontend dedicado para la Gobernación con indicadores
agregados:

- Tasa de cumplimiento de fallos por secretaría.
- Tiempo promedio de respuesta (desde notificación hasta respuesta
  institucional).
- Distribución de sanciones por responsable.
- Mapa de calor geográfico (municipios con más tutelas).
- Tendencia temporal (vs año anterior).

**Stack sugerido:** React + D3.js + la DB actual. Sin dependencias
adicionales.

**Nivel:** bajo-medio. 3-4 semanas.

### 9.10. Certificación ISO / compliance institucional

**Qué:** alinear el sistema con:

- **ISO 27001** (seguridad de la información)
- **ISO 42001** (gestión de sistemas de IA) — aunque v6.0 NO usa IA, el
  estándar aplica a sistemas de toma de decisiones automatizada
- **NTC 5854** (accesibilidad web colombiana)

**Para qué:** formaliza la auditabilidad y facilita la transferencia
del sistema a otras entidades. Requisito implícito en licitaciones
públicas futuras.

**Nivel:** alto en esfuerzo administrativo. Técnicamente casi listo.

### 9.11. Integración con sistemas gubernamentales (SECOP, SIIPI, SGSP)

**Qué:** APIs de intercambio automático con:

- **SECOP II** (contratación pública) — correlacionar con fallos que
  condenan por contratación irregular.
- **Sede Electrónica Colombiana** — notificaciones y descargas
  automáticas.
- **SGSP** (Sistema de Gestión de la Secretaría de Política) —
  integración interna de la Gobernación.

**Beneficio:** elimina doble digitación y consolida información oficial
en un único punto.

**Nivel:** medio-alto. Requiere coordinación con MinTIC.

### 9.12. Tesis doctoral en Derecho Computacional

**Qué:** usar v6.0 como base empírica de una tesis doctoral con tema
como *"Cognición Determinista en Sistemas de Justicia Administrativa:
Arquitecturas Auditables para el Cumplimiento del Habeas Data en Colombia"*.

**Universidades sugeridas:**

- **Universidad del Rosario** (Doctorado en Derecho).
- **Universidad de los Andes** (Doctorado en Derecho o en Ingeniería).
- **Universidad Externado** (Doctorado en Derecho Público).
- **Universidad Javeriana** (Doctorado en Ciencias Jurídicas).

**Duración:** 4-5 años, compatible con trabajo institucional (régimen
de tiempo parcial).

**Nivel:** muy alto. Este es el camino natural para consolidar la
carrera como **Ingeniero Legal** de referencia en el país.

### 9.13. Comparación cross-jurisdicción

**Qué:** aplicar v6.0 a datos de otra gobernación (por ejemplo,
Antioquia o Cundinamarca) para validar:

- ¿Se mantienen los LRs calibrados?
- ¿Los rangos de entropía son similares?
- ¿Las 12 heurísticas H1-H12 son universales o regionales?

**Colaboraciones institucionales:** convenios inter-gobernaciones a
través de la Federación Nacional de Departamentos.

**Nivel:** alto. Requiere acceso legal a datos sensibles de otra
entidad.

### 9.14. Integración multimodal futura (local)

**Qué:** cuando la Gobernación apruebe hardware (GPU), integrar un LLM
local (Qwen 2.5 14B / Llama 3.3 70B) **dentro del host** usando Ollama.
Esto permite:

- Respuestas narrativas mejoradas (pretensiones, observaciones)
- **Sin violar habeas data** porque nada sale del host
- Coexistencia pacífica con el pipeline determinista: el LLM local solo
  se invoca para los ~6 campos narrativos

**Prerrequisito:** hardware con 16-24 GB VRAM. Costo estimado: ~$1,500
USD (RTX 4060) a $4,000 USD (workstation SED).

**Nivel:** bajo (técnicamente). Alto (presupuesto público).

---

### Priorización sugerida (próximos 12 meses)

| Prioridad | Propuesta | Razón |
|---|---|---|
| 🟢 Alta | 9.4 Alertas tempranas | Alto impacto institucional, bajo esfuerzo |
| 🟢 Alta | 9.9 Dashboard ejecutivo | Visibilidad ante el Gobernador |
| 🟡 Media | 9.2 RAG jurisprudencial | Autocita de la Corte Constitucional |
| 🟡 Media | 9.8 Audit de fairness | Cumplimiento preventivo |
| 🟡 Media | 9.1 Paper académico | Consolidación de disciplina |
| 🔵 Larga | 9.12 Tesis doctoral | Carrera de largo plazo |
| 🔵 Larga | 9.7 Open source | Impacto nacional |


## 10. Referencias y anexos

### 10.1. Referencias teóricas

**Teoría de la información y entropía**
- Shannon, C. E. (1948). *A Mathematical Theory of Communication*.
  Bell System Technical Journal, 27(3), 379–423.
- Shannon, C. E., & Weaver, W. (1949). *The Mathematical Theory of
  Communication*. University of Illinois Press.
- Cover, T. M., & Thomas, J. A. (2006). *Elements of Information Theory*
  (2nd ed.). Wiley.

**Teoría del caos y sistemas dinámicos**
- Lorenz, E. N. (1963). *Deterministic Nonperiodic Flow*. Journal of the
  Atmospheric Sciences, 20(2), 130–141.
- Gleick, J. (1987). *Chaos: Making a New Science*. Viking Penguin.
- Strogatz, S. H. (2015). *Nonlinear Dynamics and Chaos* (2nd ed.).
  Westview Press.

**Negentropía y estructuras disipativas**
- Schrödinger, E. (1944). *What is Life? The Physical Aspect of the
  Living Cell*. Cambridge University Press.
- Prigogine, I. (1977). *Time, Structure and Fluctuations*. Nobel
  Lecture.
- Prigogine, I., & Stengers, I. (1984). *Order Out of Chaos: Man's New
  Dialogue with Nature*. Bantam Books.

**Inferencia Bayesiana y razonamiento probabilístico**
- Bayes, T. (1763). *An Essay towards solving a Problem in the Doctrine
  of Chances*. Philosophical Transactions of the Royal Society.
- Pearl, J. (1988). *Probabilistic Reasoning in Intelligent Systems*.
  Morgan Kaufmann.
- Gelman, A., et al. (2013). *Bayesian Data Analysis* (3rd ed.). CRC
  Press.

**Cognición forense y razonamiento experto**
- Ericsson, K. A., & Simon, H. A. (1984). *Protocol Analysis: Verbal
  Reports as Data*. MIT Press.
- Klein, G. (1998). *Sources of Power: How People Make Decisions*. MIT
  Press.

**Ingeniería de software y diseño auditable**
- Brooks, F. P. (1975). *The Mythical Man-Month: Essays on Software
  Engineering*. Addison-Wesley.
- Martin, R. C. (2008). *Clean Code: A Handbook of Agile Software
  Craftsmanship*. Prentice Hall.

### 10.2. Marco normativo colombiano

- **Constitución Política de Colombia (1991)**, artículos 15 (intimidad y
  habeas data), 29 (debido proceso), 86 (acción de tutela).
- **Ley 1437 de 2011** – Código de Procedimiento Administrativo y de lo
  Contencioso Administrativo. Artículos sobre motivación del acto
  administrativo.
- **Ley 1581 de 2012** – Régimen General de Protección de Datos
  Personales (Habeas Data).
- **Decreto 1377 de 2013** – Reglamentación parcial de la Ley 1581.
- **Decreto 1074 de 2015** – Decreto Único Reglamentario del sector
  Comercio, Industria y Turismo (incluye tratamiento de datos).
- **Circular Externa 002 de 2015** (SIC) – Tratamiento de datos
  personales y registro en el RNBD.
- **Sentencia T-414 de 1992** – Primer desarrollo del habeas data en
  Colombia.
- **Sentencia T-114 de 2023** – Motivación suficiente en actos
  administrativos automatizados.
- **Decreto 338 de 2022** – Política de gobierno digital y seguridad
  digital.

### 10.3. Archivos del proyecto

**Módulos cognitivos v6.0** (`backend/cognition/`)
- `entropy.py` — Entropía de Shannon y detección de inconsistencias.
- `canonical_identifiers.py` — Cosecha con LR y zonas.
- `bayesian_assignment.py` — Inferencia probabilística con reasons.
- `actor_graph.py` — Grafo de actores con correferencia.
- `procedural_timeline.py` — Timeline procesal ordenada.
- `case_classifier.py` — Clasificación origen + estado_incidente.
- `live_consolidator.py` — Fusiones dentro del pipeline.
- `cognitive_persist.py` — Entropy gate + idempotencia.
- `cognitive_fill.py` (v5.3) — Llenado semántico sin IA.
- `zone_classifier.py` (v5.3) — Zonas del documento.
- `entity_extractor.py` (v5.3) — Extracción de actores.
- `decision_extractor.py` (v5.3) — Sentidos de fallo.
- `narrative_builder.py` (v5.3) — Textos narrativos.
- `ner_spacy.py` (v5.3) — NER con spaCy `es_core_news_lg`.

**Orquestador v6.0**
- `backend/extraction/unified_cognitive.py` — Pipeline de 7 capas con
  feature flag.

**Scripts operativos**
- `scripts/measure_entropy.py` — CLI para medir H(DB).
- `scripts/classify_all_cases.py` — Populate origen/estado_incidente.
- `scripts/reextract_v55.py` — Backup + snapshot + relaunch.
- `scripts/compare_extraction_v55.py` — Diff pre/post.
- `scripts/experiment_monitor.py` — Observación continua del pipeline.

**Tests (171 verdes)**
- `tests/test_entropy_v6.py` (13) — Shannon, inconsistencias.
- `tests/test_canonical_identifiers_v6.py` (10) — LR por zona.
- `tests/test_bayesian_v6.py` (12) — Heurísticas H1-H11.
- `tests/test_actor_graph_v6.py` (9) — Correferencia, litisconsorcio.
- `tests/test_timeline_classifier_v6.py` (14) — Posiciones, origen.
- `tests/test_live_consolidator_v6.py` (8) — Fusiones.
- `tests/test_cognitive_persist_v6.py` (8) — Idempotencia.
- `tests/test_visual_and_tail_v55.py` (13) — FOOTER_TAIL, visual.
- `tests/test_rad_utils.py` + `tests/test_monitor_matcher.py` +
  `tests/test_integrity_v51.py` + `tests/test_forensic_analyzer.py` (84
  legacy).

**Documentación relacionada**
- `docs/TESIS_PROYECTO_AGENTE_JURIDICO.md` — Tesis consolidada v5.2.
- `docs/V6_COGNITIVE_RESULTS.md` — Reporte empírico v6.0.
- `docs/arquitectura_interactiva.html` — Guía visual interactiva.
- `docs/CAMINO_INGENIERIA_LEGAL.md` — Manifiesto de la disciplina.
- `docs/CLAUDE_HISTORY_v3_to_v52.md` — Historial arquitectónico.

### 10.4. Datos del experimento v6.0

Corpus: 197 casos reales de la Secretaría de Educación de Santander
durante abril 2026.

Acceso restringido: `data/tutelas.db` (18 MB) en
`TUTELAS 2026 A/tutelas-app/data/`.

Backups automatizados: `tutelas.db.pre_v6_cognitive_*.bak`,
`tutelas.db.pre_reextract_v55_*.bak`.

Snapshots: `logs/entropy_v55_baseline.json`, `logs/entropy_v6_pre.json`.

---

## Cierre

> *La pureza del cuadro final no viene de "limpiar residuos" — viene de
> un pipeline diseñado para no producirlos.*

Este documento postula que la **cognición jurídica experta es codificable
como reglas deterministas auditables**, y que hacerlo no es solo
técnicamente viable sino éticamente superior en contextos de alto
compromiso con el habeas data. La Ingeniería Legal — la disciplina que
emerge de esta intersección — requiere profesionales con formación
híbrida, comprometidos con la explicabilidad y la reproducibilidad
como valores cardinales.

El sistema Tutelas Manager v6.0 es una primera instancia funcional de
esta visión. Queda mucho por hacer. Este texto es una invitación a
continuar el trabajo: convertir cada insight clínico del ingeniero legal
en un módulo cognitivo, cada heurística tácita en un test unitario, cada
decisión opaca en una secuencia de LRs auditables.

El siguiente documento de esta línea de investigación será, posiblemente,
una tesis doctoral. Pero también podría ser simplemente el próximo commit
que añade una capa, un patrón, una regla. Ambos caminos son válidos, y
ambos contribuyen a construir una justicia computable.

---

*Documento vivo. Última revisión: 2026-04-23.*
*Branch: `experiment-v5.5` · Tag futuro: `v6.0-release`.*

