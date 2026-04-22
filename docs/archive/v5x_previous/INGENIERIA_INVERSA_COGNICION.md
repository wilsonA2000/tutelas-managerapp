# Ingeniería inversa de cognición — cómo analizo documentos y cómo emularlo mecánicamente

**Objetivo:** reducir dependencia de IA cara reemplazando mi razonamiento con código determinista, regex avanzados e índices. Investigación aplicada sobre los 6 archivos huérfanos de Sprint 5.

**Caso de estudio:** los 6 PDFs de `_docs_huerfanos_revision_humana/` que tu plataforma NO pudo clasificar.

---

## Parte 1: Mi proceso mental explícito (lo que hice con cada PDF)

Para cada documento ejecuto un pipeline cognitivo de **7 etapas**. Las documento aquí en orden para que sepas cuál va en qué componente de tu plataforma.

### Etapa 1 — Extracción de texto: primeras 2 páginas

**Decisión:** leer solo primeros 1,500-3,000 chars de página 1 y 2. Los campos clave de una tutela siempre están ahí.

**Tu equivalente actual:** `pdftext` + `normalize_pdf_lightweight()` ya lo hacen. ✅

**Mejora propuesta:** no hay — tu pipeline ya extrae bien.

### Etapa 2 — Clasificación del TIPO de documento por estructura léxica

Antes de extraer entidades, clasifico por **patrones estructurales invariantes**:

| Tipo | Patrón estructural |
|------|-------------------|
| Email Outlook forwarded | Primera línea = `Outlook` + siguientes 5 líneas contienen `Desde\|Fecha\|Para\|CC` |
| Escrito de tutela | Primeras líneas = `Señor(a)\|Señora` + `JUEZ` + `E.S.D` + `ACCIONANTE:` |
| Acta de reparto | Contiene `ACTA DE REPARTO` + `REPARTIDO AL JUZGADO` |
| Auto admisorio | Contiene `AVOCA CONOCIMIENTO` o `ADMITE LA PRESENTE ACCIÓN` |
| Sentencia | Contiene `RESUELVE:` + `CONCEDE\|NIEGA\|IMPROCEDENTE` en las primeras 3 páginas |
| Tutela en línea (sistema) | Contiene `Se ha registrado la Tutela en Línea con número NNNNNNN` |
| Anexo escaneado | 0 chars o texto corrupto + suffix `_Anexo` o `_2`/`_3` en nombre |

**Tu equivalente actual:** `classify_doc_type(filename)` en `pipeline.py:74` clasifica por **nombre de archivo**, no por contenido. Bug: si el archivo se llama `001_EscritoTutela.pdf` pero el contenido es otra cosa, lo clasifica mal.

**Mejora propuesta:** agregar `classify_by_content(text)` que clasifique por las primeras 500 chars.

### Etapa 3 — Extracción de entidades por patrones (sin IA)

Para cada tipo identificado, busco entidades en posiciones específicas:

**Escrito de tutela:**
```
ACCIONANTE:\s+([A-ZÁÉÍÓÚÑ\s]{8,60})\s+(?:mayor|TIPO|identificad|C\.C\.|CC|CÉDULA)
ACCIONADA?:\s+([A-ZÁÉÍÓÚÑ\s/]{10,100})
C\.?C\.?\s*[Nº°No.]*\s*(\d{6,11})
Juez\s+(?:Promiscuo|Penal|Civil)\s+(?:Municipal|del\s+Circuito)\s+de\s+([A-ZÁÉÍÓÚÑ][a-záéíóúñ\s]+?)(?:\s+[EeSsDd])
```

**Email tutela en línea:**
```
Tutela\s+en\s+Línea\s+con\s+número\s+(\d{7,})       # 3645440, 3722226
Ciudad:\s+([A-Z][A-Z\s]+)
Accionante:\s+([A-ZÁÉÍÓÚÑ\s]+?)\s+Identificado
documento:\s+(\d{6,11})
Correo\s+Electrónico\s+Accionante\s*:\s*(\S+@\S+)
```

**Acta de reparto:**
```
ACTA\s+DE\s+REPARTO\s+CIVIL\s+No\.\s*(\d+)            # 148, 149...
ACCIONANTE:\s+([A-ZÁÉÍÓÚÑ\s]{8,60})
REPARTIDO\s+AL\s+JUZGADO\s+_+(\d+)_+\s+PROMISCUO.+?DE\s+([A-ZÁÉÍÓÚÑ]+)
```

**Tu equivalente actual:** `backend/agent/regex_library.py` tiene ~12 patrones, principalmente para RADICADO y FOREST. **Faltan** los patrones específicos de cada tipo de documento.

**Mejora propuesta:** expandir `regex_library.py` con sección por tipo de documento (ver código abajo).

### Etapa 4 — Extracción de identificadores numéricos

Extraigo TODOS los números del texto y los clasifico:

| Tipo | Longitud | Ejemplo | Regex |
|------|----------|---------|-------|
| **Radicado 23d** | 23 dígitos | `68001408800320260005700` | `\b68\d{21}\b` |
| **CC colombiana** | 6-10 dígitos | `1077467661`, `91071881` | `(?:CC\|C\.C\.\|cédula)\s*(\d{6,10})` |
| **NUIP menor** | 10-11 dígitos después de `RC` | `1130104808` | `(?:RC\|Registro\s+Civil)\s+(?:No\.?)?\s*(\d{10,11})` |
| **Tutela en línea** | 7-8 dígitos después de "Tutela en Línea" | `3722226` | `Tutela\s+(?:en\s+Línea\s+)?(?:No\.?\s*)?(\d{7,8})` |
| **FOREST** | 11 dígitos empieza `2026` | `20260054965` | `(?:con\s+)?(?:número\s+de\s+)?radicado\s+(20\d{9,11})` (v5.0 esto lo cerramos con F1) |
| **NIT** | 9-10 dígitos + guión | `899999000-1` | `NIT[.\s:]+(\d{8,10}-?\d?)` |
| **Expediente disciplinario** | formato `NNN-YY` | `160-25` | `Expediente\s+(?:No\.?\s*)?(\d{3,4}-\d{2})` |

**Tu equivalente actual:** solo radicado 23d + FOREST + CC parcial.

**Mejora propuesta:** función `extract_all_identifiers(text) -> dict[tipo, list[valor]]` que devuelva *todo* de una pasada.

### Etapa 5 — Correlación de archivos (el paso que tu plataforma NO hace)

Cuando tengo 3 archivos en una carpeta (`001_EscritoTutela.pdf`, `002_Anexos.pdf`, `003_ActaReparto.pdf`), **no los analizo uno por uno independientemente**. Uso:

**Heurísticas de correlación:**

1. **Serie numérica** `001_X.pdf`, `002_Y.pdf`, `003_Z.pdf` → **mismo caso**
   - Regla: si 2+ archivos comparten prefijo `NNN_` y hay al menos uno con texto extraíble que identifica accionante, los demás heredan.

2. **Anexos huérfanos**: `*_Anexos.pdf` sin texto, pero hay `_EscritoTutela.pdf` con texto → anexos van al mismo caso.

3. **Mismo accionante en múltiples PDFs de la carpeta** → claramente un caso.

4. **Contradicción de accionantes** → múltiples casos mezclados en la carpeta.

**Tu equivalente actual:** cada documento se procesa aislado en `process_folder()`. No hay correlación entre archivos de una misma carpeta.

**Mejora propuesta:** nuevo módulo `folder_correlator.py` que ANTES de procesar, agrupe archivos por patrones de nombre y decida si son 1 caso o varios.

### Etapa 6 — Cross-check con la DB existente

Antes de crear caso nuevo, busco match por múltiples criterios (en orden de prioridad):

```
1. rad23 exacto (≥20 dígitos normalizados)      → match DEFINITIVO
2. rad23 parcial (mismo juzgado + misma seq)    → match ALTO
3. CC del accionante (match exacto)              → match ALTO
4. FOREST exacto                                 → match MEDIO (FOREST se reusa)
5. Accionante: ≥2 tokens de nombre + ciudad      → match MEDIO
6. Tutela en línea No + fecha                    → match ESPECÍFICO
7. Solo rad corto (2026-NNNNN) sin juzgado       → match BAJO (peligro colisión)
```

**Tu equivalente actual:** `match_to_case()` en `gmail_monitor.py:303` hace match por rad23/rad_corto/personería/accionante. **No usa CC** (la cédula es el identificador más confiable).

**Mejora propuesta:** agregar CC como criterio de match.

### Etapa 7 — Decisión final + logging

Con toda la info, decido:

- **Mover a caso existente**: si tengo score ≥ "match ALTO"
- **Crear caso nuevo**: si score < match MEDIO pero tengo accionante + ciudad + algún identificador
- **`PENDIENTE_REVISION_HUMANA`**: si no tengo suficiente info (menos de accionante + ciudad)

Logueo toda la cadena de razonamiento para auditoría.

**Tu equivalente actual:** `reasoning_logs` existe pero se llena solo durante extracción IA. No se llena durante clasificación de huérfanos.

---

## Parte 2: Código mecánico que emula el proceso

### 2.1 Módulo nuevo: `backend/services/forensic_analyzer.py`

Ver archivo creado. Implementa las 7 etapas como pipeline puro (0 llamadas IA).

### 2.2 Expansión de `regex_library.py`

Agregar sección **PATTERNS POR TIPO DE DOCUMENTO**. Ver abajo.

### 2.3 Nuevo módulo: `backend/services/folder_correlator.py`

Implementa la Etapa 5. Agrupa archivos de una carpeta por patrones de serie antes de procesarlos.

### 2.4 Ampliar `match_to_case()` con CC

---

## Parte 3: Resultados del análisis forense sobre los 6 huérfanos

Aplicando mi proceso mental se obtuvo:

| Grupo | PDFs | Accionante | Ciudad | Tipo | Destino |
|-------|------|-----------|--------|------|---------|
| 1 | 001_EscritoTutela + 002_AnexosTutela + 003_ActaReparto | ALIS YURLEDYS MORENO MORENO (CC 1077467661) | Cimitarra | Escrito + Anexos + Acta reparto | **Caso nuevo 570** |
| 2 | 002. AccionDeTutela + 003. AnexoAnexoEscritoTutela | EDGAR DIAZ VARGAS (CC 91071881) | Encino | Email tutela en línea 3645440 + Petición | **Caso nuevo 571** |
| 3 | EscritoTutelayAnexos | JORGE DUVAN JIMENEZ GUERRERO (CC 1005461409) + menor JUIETA JIMÉNEZ PEÑA (RC 1130104808) | Sabana de Torres | Escrito de tutela | **Caso nuevo 572** |

**Conclusión:** los 6 "huérfanos sin pistas" en realidad tenían TODA la información necesaria. Tu plataforma no los clasificó porque:

1. **No leyó el texto de los PDFs** con texto extraíble — procesó solo el nombre del archivo
2. **No correlacionó archivos de la misma carpeta** (001/002/003 son una serie)
3. **No usó CC como identificador** — el más confiable de todos
4. **No extrajo "Tutela en línea N°"** — patrón muy específico del sistema judicial

Estos 4 gaps son arreglables con código (no IA). Es lo que voy a implementar.
