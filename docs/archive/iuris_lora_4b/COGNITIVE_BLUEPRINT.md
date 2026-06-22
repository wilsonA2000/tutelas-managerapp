# IURIS — Blueprint Cognitivo (Ingeniería Inversa)
> Cómo razona Claude al extraer campos de tutelas colombianas. Documento maestro para training y system prompt.

---

## Modelo mental general

Cuando recibo un documento jurídico colombiano (tutela, auto, sentencia, incidente), mi proceso es secuencial:

1. **Identificar tipo de documento** — encabezado + verbos clave (RESUELVE / AUTO / SENTENCIA)
2. **Identificar fase procesal** — 1ra instancia, impugnación, incidente, sanción
3. **Identificar roles** — accionante, accionado, vinculados, tribunal
4. **Extraer eventos** — fallos, fechas, decisiones
5. **Cross-validar** — coherencia interna, orden temporal
6. **Confianza** — si dudo, prefiero `""` (vacío) a inventar

Regla de oro: **NO inventar**. Si el campo no aparece textualmente o no puede inferirse con certeza, devolver vacío.

---

## Campo por campo

### `accionante` — quien interpone la tutela

**Marcadores textuales**:
- "ACCIONANTE:" (encabezado)
- "presentada por la señora/el señor X"
- "interpuesta por X"
- "tutelante: X"
- "demandante: X"
- "actor: X"

**Reglas**:
- Es persona NATURAL (no entidad pública).
- Si dice "X actuando como agente oficioso de Y", el accionante puede ser X o Y según contexto. Default: X (el que firma).
- Si es padre/madre representando menor, accionante = el padre/madre (con apellido del menor a veces).
- Filtrar honoríficos: "el señor", "la señora", "Dr.", "Dra."

**Failure modes**:
- ❌ Confundir con "AGENTE OFICIOSO" cuando hay separación
- ❌ Tomar "PERSONERO MUNICIPAL DE X" como accionante cuando actúa por otro
- ✅ Pero si dice "PERSONERO MUNICIPAL DE X" como tutelante directo (acción colectiva), sí

**Few-shot**:
```
Texto: "Acción de tutela presentada por la señora NAYIBE CASTAÑO ARIAS, identificada con CC 1115082683..."
→ accionante: "NAYIBE CASTAÑO ARIAS"

Texto: "El PERSONERO MUNICIPAL DE SURATÁ, en representación de los habitantes..."
→ accionante: "PERSONERO MUNICIPAL DE SURATÁ"

Texto: "Acción interpuesta por LIBIA INES PATIÑO ROMÁN como agente oficiosa de su hijo K.L.M.R."
→ accionante: "LIBIA INES PATIÑO ROMÁN"
```

---

### `juzgado` — juzgado de primera instancia

**Marcadores**:
- "JUZGADO X CIVIL/PENAL/PROMISCUO MUNICIPAL DE [CIUDAD]"
- "JUZGADO X DEL CIRCUITO DE [CIUDAD]"
- Encabezado del documento + sello

**Reglas**:
- 1ra instancia es típicamente Municipal (Civil, Penal, Promiscuo, de Familia)
- Tribunal Superior NO es 1ra instancia, ES 2da (juzgado_2nd)
- Format: "JUZGADO [NÚMERO ORDINAL O CARDINAL] [TIPO] DE [CIUDAD]"

**Failure modes**:
- ❌ Confundir Tribunal Superior con juzgado (Tribunal = 2da)
- ❌ Capturar solo número sin tipo y ciudad

**Few-shot**:
```
"Juzgado Cuarto Civil Municipal de San Juan de Girón, Santander"
→ juzgado: "Juzgado Cuarto Civil Municipal de San Juan de Girón"

"JUZGADO PROMISCUO MUNICIPAL DE PIEDECUESTA"
→ juzgado: "Juzgado Promiscuo Municipal de Piedecuesta"
```

---

### `juzgado_2nd` — juzgado de segunda instancia

**Marcadores**:
- "TRIBUNAL SUPERIOR DEL DISTRITO JUDICIAL DE [CIUDAD]"
- "SALA [CIVIL|PENAL|LABORAL|DE DECISIÓN] del Tribunal..."
- "TRIBUNAL ADMINISTRATIVO DE [CIUDAD]"
- "CORTE SUPREMA DE JUSTICIA – SALA [X]"

**Reglas**:
- Solo existe si hubo impugnación (ver `impugnacion`)
- Format incluye Tribunal/Sala + ciudad del distrito
- Para tutelas contra sector público en algunos casos: Tribunal Administrativo

**Failure modes**:
- ❌ Tomar el juzgado de 1ra instancia
- ❌ No incluir la sala (Sala Civil, Sala de Decisión)

**Few-shot**:
```
"Tribunal Superior del Distrito Judicial de Bucaramanga, Sala Civil de Decisión"
→ juzgado_2nd: "Tribunal Superior del Distrito Judicial de Bucaramanga - Sala Civil de Decisión"
```

---

### `sentido_fallo_1st` — qué decidió el juez 1ra

**Valores válidos**: `CONCEDE`, `NIEGA`, `IMPROCEDENTE`

**Verbos→categoría**:
- TUTELAR / CONCEDER / AMPARAR / PROTEGER → **CONCEDE**
- NEGAR / DENEGAR / NO TUTELAR → **NIEGA**
- DECLARAR IMPROCEDENTE / RECHAZAR POR IMPROCEDENCIA → **IMPROCEDENTE**

**Marcadores**:
- "RESUELVE: PRIMERO: [VERBO]"
- "FALLA: [VERBO]"
- Sección "PARTE RESOLUTIVA"

**Reglas**:
- Buscar SOLO en sección RESUELVE / FALLA, NO en consideraciones previas
- Si el verbo está en gerundio o subjuntivo en consideraciones, ignorar
- Si concede parcialmente → **CONCEDE** (default a favor)

**Few-shot**:
```
"RESUELVE: PRIMERO: TUTELAR el derecho fundamental a la educación..."
→ sentido_fallo_1st: "CONCEDE"

"RESUELVE: PRIMERO: NEGAR la acción de tutela presentada..."
→ sentido_fallo_1st: "NIEGA"

"RESUELVE: PRIMERO: DECLARAR IMPROCEDENTE la acción..."
→ sentido_fallo_1st: "IMPROCEDENTE"
```

---

### `sentido_fallo_2nd` — qué decidió el tribunal 2da

**Valores válidos**: `CONFIRMA`, `REVOCA`, `MODIFICA`

**Verbos→categoría**:
- CONFIRMAR (la sentencia de primera instancia) → **CONFIRMA**
- REVOCAR → **REVOCA**
- MODIFICAR / ADICIONAR → **MODIFICA**

**Reglas**:
- Solo si hubo impugnación
- Buscar en RESUELVE del fallo de 2da instancia

---

### `impugnacion` — hubo impugnación SI/NO

**Marcadores**:
- "impugnación interpuesta", "impugna el fallo", "recurre el fallo"
- Existencia de fallo de 2da instancia
- Existencia de Tribunal en el caso

**Reglas**:
- SI si hay evidencia explícita Y/O documento de 2da instancia
- NO si el fallo de 1ra instancia no fue impugnado dentro del término
- Defecto: NO si no hay evidencia clara

---

### `quien_impugno` — actor que impugnó

**Valores válidos**: `ACCIONANTE`, `ACCIONADO`, `MINISTERIO_PUBLICO`

**Reglas inferenciales**:
- Sujeto del verbo "impugna" en el auto de impugnación
- Persona natural mencionada como impugnador → **ACCIONANTE**
- Entidad pública (Secretaría, Ministerio, EPS, alcaldía) → **ACCIONADO**
- Procurador, Defensor del Pueblo, Personero → **MINISTERIO_PUBLICO**

**Heurística por contexto del fallo 1ra**:
- Si fallo 1ra = NIEGA/IMPROCEDENTE → impugna probablemente el ACCIONANTE
- Si fallo 1ra = CONCEDE → impugna probablemente el ACCIONADO

**Failure modes**:
- ❌ Confundir destinatario de notificación con impugnador
- ❌ Tomar el primer nombre que aparece sin verificar contexto

**Few-shot**:
```
"Se procede a resolver la impugnación interpuesta por el accionante GERMAN MORENO contra la sentencia que negó el amparo."
→ quien_impugno: "ACCIONANTE"

"La SECRETARÍA DE EDUCACIÓN DE SANTANDER, mediante apoderado, IMPUGNÓ el fallo concesivo..."
→ quien_impugno: "ACCIONADO"

"El PROCURADOR DELEGADO en defensa del orden jurídico, impugna..."
→ quien_impugno: "MINISTERIO_PUBLICO"
```

---

### `incidente` — hay incidente de desacato SI/NO

**Marcadores**:
- "incidente de desacato"
- "auto que apertura incidente"
- "trámite incidental"
- "sanción del Decreto 2591/91"

**Reglas**:
- SI si existe documento titulado/que mencione incidente abierto
- NO si solo hay requerimiento previo SIN apertura formal
- "REQUIERE PREVIO APERTURA" SOLO = NO (todavía no hay incidente formal)

---

### `responsable_desacato` — funcionario incidentado

**Marcadores**:
- "REQUERIR a [NOMBRE], en su calidad de [CARGO]"
- "INCIDENTAR a [NOMBRE]"
- "APERTURAR incidente contra [NOMBRE]"
- "SANCIONAR al señor/la señora [NOMBRE]"
- "DECLARAR INCIDENTADO a [NOMBRE]"
- "VINCULAR al señor [NOMBRE]"

**Reglas críticas**:
- Es la PERSONA FÍSICA, no la entidad
- Si dice "Secretaria de Educación" → buscar el NOMBRE de la persona que ocupa el cargo
- Format: nombres y apellidos completos en MAYÚSCULAS típicamente
- Filtrar prefijos: "la Dra.", "el señor", "el doctor", "Dr."
- Si hay múltiples nombres, tomar el PRIMERO mencionado (responsable principal)

**Failure modes**:
- ❌ Devolver "SECRETARÍA DE EDUCACIÓN DE SANTANDER" (es entidad)
- ❌ Devolver "la accionada" (genérico)
- ❌ Capturar prefijo honorífico: "Dra. YANETH" → debería ser "YANETH KARINA ARAUJO MAESTRE"

**Few-shot**:
```
Texto: "Así las cosas, se REQUERIRÁ a la Dra. YANETH KARINA ARAUJO MAESTRE - SECRETARIA DE EDUCACIÓN DE SANTANDER, para que..."
→ responsable_desacato: "YANETH KARINA ARAUJO MAESTRE"

Texto: "APERTURAR incidente de desacato contra el señor JUAN BAUTISTA SEPULVEDA, identificado con CC..."
→ responsable_desacato: "JUAN BAUTISTA SEPULVEDA"

Texto: "DECLARAR que los señores X, Y y Z, en su calidad de funcionarios..."
→ responsable_desacato: "X" (primer nombre)
```

---

### `decision_incidente` — qué decidió el juez en el incidente

**Categorías típicas** (frase corta):
- "Requerimiento previo de incidente"
- "Apertura formal del incidente"
- "Vinculación al trámite"
- "Sancionar con N días de arresto"
- "Archivar por cumplimiento"
- "Archivar por carencia actual de objeto"
- "Declarar terminado el incidente"
- "Confirmar / revocar la sanción"

**Marcadores**:
- "RESUELVE: PRIMERO: [VERBO + COMPLEMENTO]"
- "PARTE RESOLUTIVA" del auto incidental

**Reglas**:
- Capturar el verbo principal + objeto (frase corta, NO párrafo entero)
- Para sanción: incluir días/monto si aparece

**Few-shot**:
```
"PRIMERO: ARCHIVAR el presente incidente de desacato por carencia actual de objeto."
→ decision_incidente: "Archivar por carencia actual de objeto"

"PRIMERO: SANCIONAR a la doctora X con tres (3) días de arresto y multa de 1 SMLMV."
→ decision_incidente: "Sancionar con 3 días de arresto y multa 1 SMLMV"

"REQUIERE PREVIO APERTURA FORMAL DE INCIDENTE..."
→ decision_incidente: "Requerimiento previo de incidente"
```

---

### `ciudad` — donde ocurren los hechos

**Reglas**:
- Es la ciudad/municipio donde se desarrolla el HECHO vulnerador, NO la ciudad del juzgado.
- Si solo se menciona ciudad del juzgado, usar esa con baja confianza.
- Default Santander: Bucaramanga, Floridablanca, Girón, Piedecuesta, etc.
- Si el caso es de un colegio/institución, usar la ciudad de la institución.

**Marcadores**:
- "los hechos ocurren en X"
- "domiciliado en X"
- Encabezado del documento (si nada más)
- Ciudad del colegio/empresa accionada

**Failure modes**:
- ❌ Tomar ciudad del estudiante de origen (ej: "nacido en Socorro" si estudia en Bucaramanga)
- ❌ Tomar primera ciudad mencionada sin contexto

---

### `derecho_vulnerado` — derecho fundamental afectado

**Categorías comunes** (palabras clave):
- Educación, Salud, Vida digna, Trabajo, Petición, Debido proceso
- Mínimo vital, Pensión, Igualdad, Habeas data
- Vivienda digna, Libre desarrollo de la personalidad

**Reglas**:
- Capturar UNA frase corta o palabra clave (ej: "Educación", "Salud y vida digna")
- Si hay múltiples, tomar los principales mencionados en pretensión

---

### Fechas (`fecha_fallo_1st`, `fecha_fallo_2nd`, `fecha_apertura_incidente`)

**Formatos válidos**:
- DD/MM/YYYY → "15/03/2026"
- "DD de MES de YYYY" → "15 de marzo de 2026"
- Aceptar AMBOS, normalizar a DD/MM/YYYY si es posible

**Marcadores**:
- "FECHA DEL FALLO:"
- "Bucaramanga, 15 de marzo de 2026"
- Pie de firma del juez
- "proferido el día X"

**Reglas**:
- Si hay múltiples fechas, tomar la del fallo (no fecha de notificación)
- Cross-validar: fecha_fallo_2nd > fecha_fallo_1st cronológicamente

---

## Reglas globales de validación cruzada

1. **Coherencia impugnación**:
   - Si `quien_impugno = ACCIONANTE` → fallo 1ra fue probablemente NIEGA/IMPROCEDENTE
   - Si `quien_impugno = ACCIONADO` → fallo 1ra fue probablemente CONCEDE

2. **Coherencia incidente**:
   - Si `incidente = SI` → debe haber `responsable_desacato` y `decision_incidente`
   - Si fallo 1ra = NIEGA → no debería haber incidente (no hay orden que incumplir)

3. **Coherencia temporal**:
   - `fecha_fallo_2nd > fecha_fallo_1st`
   - `fecha_apertura_incidente > fecha_fallo_1st`

4. **Coherencia entidad-persona**:
   - `responsable_desacato` siempre es persona natural
   - Si solo aparece la entidad → marcar `""` y dejar a humano

---

## Reglas de confianza

| Confianza | Cuándo | Acción |
|-----------|--------|--------|
| Alta | Marcador textual exacto + contexto coherente | Devolver valor |
| Media | Marcador textual pero contexto ambiguo | Devolver valor con flag |
| Baja | Inferencia indirecta, no marcador textual | Devolver `""` o flag REVISAR |
| Vacío | Sin evidencia textual | Devolver `""` |

**Regla absoluta**: **antes de inventar, devolver vacío**. Mejor 50% recall y 100% precision que 100% recall y 60% precision.

---

## Anti-patterns (qué NO hacer)

1. ❌ **No memorizar valores frecuentes**: si el dataset tiene mucho "YANETH KARINA ARAUJO" como Secretaria, NO devolver ese nombre por defecto cuando no aparece.
2. ❌ **No confundir cargos con personas**: "Secretaría de Educación" es entidad, "Yaneth Araujo" es persona.
3. ❌ **No copiar frases enteras**: extraer SOLO el campo, no el párrafo donde aparece.
4. ❌ **No inventar formatos**: si la fecha en el texto está en formato "15 de marzo", devolverla así, no convertir a "15/03/2026" si no se pide explícitamente.
5. ❌ **No responder en inglés**: siempre español, sin importar el system prompt.
6. ❌ **No incluir reasoning visible** en producción: el `<think>` o equivalente debe filtrarse antes de devolver.

---

## Salida estructurada esperada

Por cada campo:
```json
{
  "field": "responsable_desacato",
  "value": "YANETH KARINA ARAUJO MAESTRE",
  "confidence": 0.92,
  "evidence_span": "se REQUERIRÁ a la Dra. YANETH KARINA ARAUJO MAESTRE",
  "reasoning": "Marcador 'REQUERIR a' identifica responsable. Filtré honorífico 'Dra.'. Cargo 'SECRETARIA' confirma persona ocupando el rol."
}
```

Para `value` solo: respuesta directa una línea.
