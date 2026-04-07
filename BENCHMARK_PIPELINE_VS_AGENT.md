# Benchmark: Pipeline vs Agent IA - Extraccion de Tutelas
> Fecha: 7 de abril de 2026 | 6 casos evaluados | Gobernacion de Santander

## Resumen Ejecutivo

| Metrica | Pipeline | Agent IA | Ganador |
|---------|----------|----------|---------|
| **Campos promedio** | 18.0/28 | 21.3/28 | Agent (+18%) |
| **Cobertura promedio** | 64.3% | 76.2% | Agent |
| **Tiempo promedio** | 92.5s | 50.9s | Agent (45% mas rapido) |
| **Confianza promedio** | N/A | 84.0% | Agent |
| **Errores fatales** | 1 (Gemini 503) | 0 | Agent |
| **Bugs detectados** | 0 | 2 (contaminacion cruzada) | Pipeline |

**Veredicto: Agent IA es superior en velocidad, cobertura y resiliencia.** Sin embargo, tiene un bug critico de contaminacion cruzada de contexto que debe corregirse.

---

## Resultados por Caso

### Caso 0: 2026-00008 Erika Paola Motta Ayala (45 docs) - Referencia

| Metrica | Pipeline | Agent |
|---------|----------|-------|
| Campos | 21/28 (75%) | 22/28 (79%) |
| Tiempo | 97.6s | 57.3s |
| Confianza | N/A | 86.0% |

**Diferencias clave:**
- SENTIDO_FALLO: Pipeline="CONCEDE", Agent="CONCEDE PARCIALMENTE" -> **Agent mas preciso**
- DERECHO_VULNERADO: Pipeline=5 derechos, Agent=2 -> **Pipeline mas detallado**
- JUZGADO: Pipeline tiene typo "CONFUNCIONES" -> **Agent mejor formato**
- OBSERVACIONES: Pipeline=VACIO, Agent=resumen completo -> **Agent gana**

---

### Caso A: 2026-00030 Laura Viviana Chacon Arce (46 docs) - Aleatorio medio

| Metrica | Pipeline | Agent |
|---------|----------|-------|
| Campos | **1/28 (4%)** | 20/28 (71%) |
| Tiempo | 45.3s | 55.9s |
| Confianza | N/A | 85.0% |

**ANOMALIA CRITICA en Pipeline:** Gemini devolvio error 503 (UNAVAILABLE) por alta demanda. El pipeline solo extrajo 1 campo (por regex). **El Agent no tuvo este problema** porque usa Smart Router con fallback a otros proveedores.

**Leccion:** El pipeline depende de un solo proveedor IA. Si falla, la extraccion queda casi vacia. El Agent tiene resiliencia multi-proveedor.

---

### Caso B: 2026-00095 Paola Andrea Garcia Nuñez (22 docs) - Aleatorio pequeno

| Metrica | Pipeline | Agent |
|---------|----------|-------|
| Campos | 25/28 (89%) | 25/28 (89%) |
| Tiempo | 107.8s | 46.3s |
| Confianza | N/A | 83.0% |

**Empate en cobertura, Agent 57% mas rapido.**

**Diferencias de calidad:**
| Campo | Pipeline | Agent | Mejor |
|-------|----------|-------|-------|
| RADICADO_23D | `682764189003-2026-00095-00` | `68276418900320260009500` | Pipeline (formato con guiones) |
| ASUNTO | Generico "vulneracion del derecho..." | Especifico "cupo escolar para menor con dislexia" | **Agent (mas preciso)** |
| OBSERVACIONES | Incluye fecha del auto admisorio | Incluye contexto de la menor | Ambos buenos |

---

### Caso C: 2026-00028 Diego Fernando Plata Alvarez (16 docs) - Aleatorio mini

| Metrica | Pipeline | Agent |
|---------|----------|-------|
| Campos | 20/28 (71%) | 20/28 (71%) |
| Tiempo | 91.3s | 63.2s |
| Confianza | N/A | 82.0% |

**Empate en cobertura, Agent 31% mas rapido.**

**DISCREPANCIA CRITICA:**
| Campo | Pipeline | Agent | Analisis |
|-------|----------|-------|----------|
| IMPUGNACION | **SI** | NO | Debe verificarse manualmente — dato contradictorio |

**Otras diferencias:**
- ACCIONADOS: Agent tiene typo "MINICIPAL" -> Pipeline mejor
- ASUNTO: Pipeline=tecnico (puente metalico), Agent=abstracto (derechos NNA) -> Pipeline mas informativo
- JUZGADO: Pipeline incluye "- SANTANDER", Agent no -> Pipeline mas completo

---

### Caso D: 2026-00014 Blanca Aurora Nino Mateus (103 docs) - Caso mas grande

| Metrica | Pipeline | Agent |
|---------|----------|-------|
| Campos | 18/28 (64%) | 18/28 (64%) |
| Tiempo | 76.0s | 36.0s |
| Confianza | N/A | 83.0% |

**Empate en cobertura, Agent 53% mas rapido.**

**DISCREPANCIAS CRITICAS:**
| Campo | Pipeline | Agent | Analisis |
|-------|----------|-------|----------|
| RADICADO_23D | `685723103001-2026-00014-00` | `680014088011-2026-00014-00` | **Diferentes** — 103 docs pueden tener multiples radicados |
| CIUDAD | Bucaramanga | Puente Nacional | **Critico** — deben verificar cual es el municipio de afectacion |
| DERECHO_VULNERADO | Peticion + Info | Seguridad Social + Debido Proceso | **Diferentes completamente** — posible caso con multiples tutelas acumuladas |
| OBSERVACIONES | En espanol | **En ingles!** | **Bug del Agent** — respondio en ingles |

**Leccion caso masivo (103 docs):** Con muchos documentos, ambos metodos pueden confundirse entre datos de diferentes actuaciones. El pipeline fue mas conservador (Bucaramanga = sede del juzgado). El Agent intento inferir el municipio de afectacion (Puente Nacional) lo cual es correcto segun las reglas. Sin embargo, el Agent genero observaciones en ingles, lo cual es un bug del prompt.

---

### Caso E: 2026-00032 Ingrid Tatiana Nino Munoz (95 docs) - Caso completo

| Metrica | Pipeline | Agent |
|---------|----------|-------|
| Campos | 23/28 (82%) | 23/28 (82%) |
| Tiempo | 137.9s | 46.6s |
| Confianza | N/A | 84.4% |

**Empate en cobertura, Agent 66% mas rapido.**

**BUG CRITICO DETECTADO EN AGENT:**
| Campo | Pipeline | Agent | Analisis |
|-------|----------|-------|----------|
| RADICADO_23D | `680813184002-2026-00032-00` | `6829840890012026-00008-00` | **Agent devolvio radicado del CASO 65 (Erika Paola Motta)!** |
| FECHA_INGRESO | 10/02/2026 | 20/03/2026 | Pipeline correcto (auto admisorio es de febrero) |
| ABOGADO | Otilia Luna Lopez | Angelica Barroso Sarmiento | **Verificar** — puede ser contaminacion cruzada |

**CONTAMINACION CRUZADA:** El Agent IA mezclo datos del caso anterior (65 - Erika Paola Motta) con el caso actual (95 - Ingrid Tatiana). El radicado `6829840890012026-00008-00` es claramente del caso 00008, no del 00032. Esto sugiere que el contexto del caso anterior queda residual en el modelo.

**Leccion:** El Agent necesita un mecanismo de limpieza de contexto entre extracciones consecutivas. El Pipeline no tiene este problema porque cada extraccion es independiente.

---

## Tabla Comparativa Global

| Caso | Docs | Pipeline | Agent | P_Time | A_Time | Conf | Ganador |
|------|------|----------|-------|--------|--------|------|---------|
| 0: Erika Motta | 45 | 21 (75%) | 22 (79%) | 97.6s | 57.3s | 86% | Agent |
| A: Laura Chacon | 46 | 1 (4%) | 20 (71%) | 45.3s | 55.9s | 85% | **Agent** |
| B: Paola Garcia | 22 | 25 (89%) | 25 (89%) | 107.8s | 46.3s | 83% | Agent (vel) |
| C: Diego Plata | 16 | 20 (71%) | 20 (71%) | 91.3s | 63.2s | 82% | Agent (vel) |
| D: Blanca Nino | 103 | 18 (64%) | 18 (64%) | 76.0s | 36.0s | 83% | Agent (vel) |
| E: Ingrid Nino | 95 | 23 (82%) | 23 (82%) | 137.9s | 46.6s | 84% | Agent (vel) |
| **PROMEDIO** | **54.5** | **18.0 (64%)** | **21.3 (76%)** | **92.5s** | **50.9s** | **84%** | **Agent** |

---

## Fortalezas y Debilidades

### Pipeline
**Fortalezas:**
- Extraccion independiente por caso (sin contaminacion cruzada)
- Formato consistente (MAYUSCULAS, guiones en radicados)
- Mas detallado en DERECHO_VULNERADO (lista mas completa)
- Mas detallado en ACCIONADOS y VINCULADOS

**Debilidades:**
- Depende de un solo proveedor IA (fallo total si Gemini cae)
- 45-138s por caso (lento)
- No genera OBSERVACIONES consistentemente
- JUZGADO con typos ("CONFUNCIONES")
- No tiene Smart Router ni fallback

### Agent IA
**Fortalezas:**
- 45% mas rapido en promedio
- Smart Router con fallback multi-proveedor
- OBSERVACIONES siempre generadas y completas
- ASUNTO mas preciso y especifico
- CIUDAD correcta (municipio de afectacion vs sede del juzgado)
- Resiliente ante errores 503

**Debilidades:**
- **BUG: Contaminacion cruzada** entre casos consecutivos (radicado de caso anterior)
- Observaciones en ingles en caso masivo (bug de prompt)
- Formato inconsistente (mixed case vs MAYUSCULAS)
- RADICADO_23D sin guiones (menos legible)
- Typos propios ("MINICIPAL")

---

## Bugs Criticos a Corregir

### BUG-001: Contaminacion cruzada del Agent
- **Severidad:** CRITICA
- **Descripcion:** Al extraer casos consecutivos, el Agent mezcla datos del caso anterior
- **Evidencia:** Caso E (2026-00032) recibio radicado del caso 0 (2026-00008)
- **Causa probable:** Cache de contexto o estado residual en el ContextAssembler
- **Fix propuesto:** Limpiar estado/cache del ContextAssembler antes de cada extraccion. Agregar validacion cruzada: el radicado extraido debe coincidir con el numero de la carpeta

### BUG-002: Observaciones en ingles
- **Severidad:** MEDIA
- **Descripcion:** En caso con 103 docs, el Agent genero observaciones en ingles
- **Evidencia:** Caso D: "This case involves Blanca Aurora..."
- **Causa probable:** Prompt en espanol pero modelo cambia a ingles con contexto largo
- **Fix propuesto:** Agregar al prompt: "RESPONDE SIEMPRE EN ESPANOL. NUNCA en ingles."

### BUG-003: Pipeline sin fallback de proveedor
- **Severidad:** ALTA
- **Descripcion:** Si Gemini devuelve 503, el pipeline falla completamente (1/28 campos)
- **Evidencia:** Caso A: Error 503 UNAVAILABLE
- **Causa probable:** Pipeline usa solo un proveedor sin retry ni fallback
- **Fix propuesto:** Integrar Smart Router del Agent al Pipeline, o al menos agregar retry con backoff

---

## Mejoras Propuestas para Cada Motor

### Para el Pipeline
1. **Integrar Smart Router** — usar fallback a Groq/Cerebras si Gemini falla
2. **Siempre generar OBSERVACIONES** — actualmente las deja vacias frecuentemente
3. **Normalizar formato** — corregir typos en JUZGADO post-extraccion
4. **Agregar validacion de radicado** — el radicado corto debe coincidir con la carpeta

### Para el Agent IA
1. **Limpiar contexto entre casos** — evitar contaminacion cruzada
2. **Forzar espanol en prompt** — agregar instruccion explicita
3. **Validar radicado vs carpeta** — post-check que radicado coincida con folder_name
4. **Normalizar formato de salida** — MAYUSCULAS para nombres propios, guiones en radicados
5. **Incluir mas derechos vulnerados** — actualmente lista incompleta vs Pipeline

### Para Ambos
1. **Validacion cruzada post-extraccion** — radicado_corto vs carpeta, ciudad vs juzgado
2. **IMPUGNACION verificable** — buscar explicitamente "impugna" en sentencias
3. **Formato consistente de radicado 23D** — siempre con guiones XX-XXX-XX-XX-XXX-YYYY-NNNNN-NN
4. **Log de fuente** — registrar de que documento se extrajo cada campo para auditoria

---

## Datos Crudos por Caso

### Caso 0: 2026-00008 Erika Paola Motta Ayala

| Campo | Pipeline | Agent |
|-------|----------|-------|
| radicado_23_digitos | 6829840890012026-00008-00 | 6829840890012026-00008-00 |
| radicado_forest | 20260025457 | 20260025457 |
| abogado_responsable | Otilia Luna Lopez | Otilia Luna Lopez |
| accionante | ERIKA PAOLA MOTTA AYALA, COMO AGENTE OFICIOSO... | Erika Paola Motta Ayala - Como agente oficiosa... |
| accionados | DPTO SANTANDER - SED - IE LA PALMA | Gobernacion de Santander - SED |
| derecho_vulnerado | EDUCACION - ACCESIBILIDAD - ACCESO - PERMANENCIA - INTERES SUPERIOR | EDUCACION - INTERES SUPERIOR DEL MENOR |
| juzgado | JPM CONFUNCIONES CONTROL GARANTIAS GAMBITA | JPM con Funciones de Control de Garantias de Gambita |
| ciudad | Gambita | Gambita |
| sentido_fallo_1st | CONCEDE | CONCEDE PARCIALMENTE |
| observaciones | (vacio) | Resumen completo con cronologia |

### Caso B: 2026-00095 Paola Andrea Garcia Nunez

| Campo | Pipeline | Agent |
|-------|----------|-------|
| radicado_23_digitos | 682764189003-2026-00095-00 | 68276418900320260009500 |
| asunto | Generico "vulneracion del derecho..." | Especifico "cupo escolar menor con dislexia" |
| quien_impugno | Secretaria Educacion Floridablanca | SECRETARIA EDUCACION FLORIDABLANCA |

### Caso C: 2026-00028 Diego Fernando Plata Alvarez

| Campo | Pipeline | Agent |
|-------|----------|-------|
| impugnacion | SI | NO |
| asunto | Tecnico: "paralizacion puente metalico" | Abstracto: "proteccion derechos NNA" |
| accionados | Correcto | Typo "MINICIPAL" |

### Caso D: 2026-00014 Blanca Aurora Nino Mateus (103 docs)

| Campo | Pipeline | Agent |
|-------|----------|-------|
| radicado_23_digitos | 685723103001-2026-00014-00 | 680014088011-2026-00014-00 |
| ciudad | Bucaramanga | Puente Nacional |
| derecho_vulnerado | PETICION - INFO | SEGURIDAD SOCIAL - DEBIDO PROCESO |
| observaciones | Espanol correcto | **EN INGLES (bug)** |

### Caso E: 2026-00032 Ingrid Tatiana Nino Munoz (95 docs)

| Campo | Pipeline | Agent |
|-------|----------|-------|
| radicado_23_digitos | 680813184002-2026-00032-00 | **6829840890012026-00008-00 (CONTAMINADO!)** |
| fecha_ingreso | 10/02/2026 | 20/03/2026 |
| abogado_responsable | Otilia Luna Lopez | Angelica Barroso Sarmiento |

---

## Conclusion

El **Agent IA** es el motor recomendado por velocidad, resiliencia y calidad de OBSERVACIONES/ASUNTO. Sin embargo, tiene **2 bugs criticos** (contaminacion cruzada + idioma) que deben corregirse antes de usarlo en produccion para extraccion masiva.

El **Pipeline** es mas confiable para extracciones aisladas (sin contaminacion) y genera datos mas detallados en campos como DERECHO_VULNERADO y ACCIONADOS, pero su dependencia de un solo proveedor lo hace fragil.

**Estrategia optima:** Usar Agent IA como motor principal con validacion post-extraccion que verifique radicado vs carpeta. Para campos donde el Pipeline es mejor (DERECHO_VULNERADO, ACCIONADOS), considerar un paso hibrido que combine ambos resultados.
