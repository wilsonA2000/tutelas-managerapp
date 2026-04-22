# Resumen Ejecutivo — Plataforma de Agente Jurídico IA

**Tesis:** Plataforma híbrida de agente jurídico con cognición forense mecánica para procesamiento autónomo de acciones de tutela
**Autor:** Wilson — Ingeniero Legal, Gobernación de Santander
**Período:** Enero–Abril 2026 | **Versión final:** v5.2

---

## 1. Problema

La Secretaría de Educación Departamental de Santander recibe **~350 acciones de tutela al año**. El registro manual de cada expediente requiere **45–90 minutos** de un profesional jurídico (lectura de 5–15 documentos, digitación de 28 campos estructurados en Excel, verificación cruzada).

**Costo oculto:** 22–45 horas/mes solo en registro, sin redactar respuesta. Propenso a errores de digitación y duplicación. Sin trazabilidad. Imposible escalar.

**Problema técnico de fondo:** los sistemas genéricos de IA/OCR no reconocen particularidades jurídicas colombianas (radicado 23 dígitos, código de juzgado en posiciones 6-12, número FOREST interno de la Gobernación, múltiples formatos de oficio judicial).

---

## 2. Solución propuesta

Plataforma híbrida **determinista + heurística + IA**, con **cinco pipelines** especializados:

1. **Ingesta Gmail** — descarga automática, extracción de radicado con priorización por confiabilidad (rad23 > CC > FOREST > rad_corto)
2. **Extracción unificada (6 fases)** — normalización multi-tier → representación intermedia (IR) → 13 regex sobre zonas semánticas → enriquecimiento forense → IA solo para campos semánticos → merge con resolución de conflictos → persistencia validada
3. **Verificación documental** — 5 criterios multi-decisión por documento (OK / SOSPECHOSO / NO_PERTENECE)
4. **Cleanup y reconciliación** — consolidación de duplicados, sincronización de paths, WAL checkpoint automático
5. **Forense (novedad v5.2)** — 7 etapas que emulan cognición humana sin IA

**Diferenciadores técnicos clave:**
- **Motor jurídico específico Colombia**: reconoce código de juzgado del radicado 23d (evita colisión inter-juzgados)
- **Anti-contaminación cognitiva**: el prompt inyecta radicado oficial, no folder físico malformado
- **Fallback real multi-provider**: DeepSeek → Claude Haiku 3 con cooldown 60s post-429
- **Cognición forense offline**: 7 etapas deterministas que clasifican, extraen y correlacionan documentos sin llamar IA
- **Provenance email→documentos inmutable**: regla "hermanos viajan juntos" garantiza integridad de paquetes

---

## 3. Metodología aplicada

**Enfoque Sprint iterativo** con 8 iteraciones en 3 meses, cada una cerrada con:
- Tests de regresión (40 tests críticos al final)
- Benchmark cuantitativo antes/después
- Backup nombrado pre-cambio (SHA256 verificado)
- Documento markdown con evidencia

**Metodología de auditoría empírica** (Sprint v5.0): muestreo estratificado de 25 casos en 7 estratos, ficha de contraste por cada uno (disco ↔ DB ↔ email fuente ↔ observaciones IA). Esta técnica descubrió 13 bugs estructurales y un bug nuevo no catalogado (duplicación no reconsolidada).

**Ingeniería inversa de cognición** (Sprint v5.2): documentar el razonamiento humano en 7 etapas explícitas y traducir cada una a código Python determinista. Resultado: 414 líneas de pipeline forense con 0 llamadas a IA, capaz de extraer 10 tipos de identificadores y clasificar documentos por contenido.

---

## 4. Resultados cuantitativos (v4.9 → v5.2)

| Indicador | v4.9 (inicio auditoría) | v5.2 (final) | Mejora |
|-----------|-------------------------|--------------|--------|
| Folders `[PENDIENTE REVISION]` activos | 2 | **0** | −100% |
| Casos COMPLETO sin radicado judicial | 18 | **0** | −100% |
| Folders con radicado disonante (bug B1) | 35 | **0** | −100% |
| Cobertura `radicado_23_digitos` | 94.2% | **100%** | +5.8 pp |
| Documentos verificados OK | 3,474 | **3,587** | +113 |
| Documentos PENDIENTE_OCR | 83 | **11** | −87% |
| Inconsistencias históricas | 434 | **~29** | −93% |
| Costo por caso (IA) | $0.008 (v4.6) | **$0.0025** | −69% |
| Tiempo por caso (IA) | 205s (v4.6) | **41s** | −80% |
| Tests regresión | 0 | **40** | +40 |
| Herramientas del agente | 16 | **27** | +69% |
| Patterns regex especializados | 12 | **17** | +42% |
| Formatos documento soportados | 3 | **6** | +100% |

**Impacto operativo medido:** trabajo manual de registro pasa de 45–90 min/caso a **~5 min/caso** (revisión y confirmación). Ahorro estimado: **20–40 horas/mes por secretaría**.

**Evaluación empírica de heurísticas vs IA:** ~70% de los 28 campos del protocolo son extraíbles con heurísticas deterministas (costo $0). La IA agrega valor solo en 4-5 campos semánticos (observaciones, pretensiones, asunto, derecho_vulnerado).

---

## 5. Contribuciones académicas

1. **Metodología de ingeniería inversa de cognición jurídica**: técnica reproducible para documentar razonamiento humano en etapas ejecutables por código.

2. **Taxonomía de 7 clases de heurísticas** aplicables al dominio legal: priorización por confiabilidad, puntuación multi-criterio con boost, cascada de fallback, correlación estructural, clasificación por densidad, validación cruzada de interdependencia, filtro por stop tokens.

3. **Motor jurídico específico Colombia**: primer sistema open-compatible que reconoce código de juzgado (dígitos 6-12 del rad 23d) para evitar colisión inter-juzgados.

4. **Paradigma de anti-contaminación cognitiva del prompt**: el prompt contractual con la IA usa radicado oficial en lugar del folder físico. Evita que la IA ventriloquee datos erróneos.

5. **Consolidación disciplinar de la Ingeniería Legal** como profesión emergente en Colombia, con ciclo metodológico de 6 fases y 9 competencias específicas documentadas.

---

## 6. Viabilidad y proyección

**Monetización (tres vías):**
- **SaaS gubernamental**: ~160 secretarías potenciales en Colombia × $3M COP/mes = mercado ~$5,760M COP/año
- **Licenciamiento OEM**: motor `regex_library + forensic_analyzer` a estudios jurídicos grandes
- **Servicios + datasets**: análisis masivos por contrato + venta de dataset anonimizado

**Extensibilidad a otros procesos legales** (reutilización 60–80% del código):
acciones populares, derechos de petición, procesos disciplinarios, contratación pública, acciones de grupo.

**Rol institucional**: el ingeniero legal se consolida como perfil de **planta** en el sector público colombiano, liderando transformación digital desde dentro (no como consultoría externa).

---

## 7. Conclusión

El proyecto demuestra empíricamente que **el 70-80% del trabajo de registro jurídico inicial es mecanizable** con ingeniería determinista especializada, reduciendo drásticamente la dependencia de IA costosa sin sacrificar calidad.

La combinación de **regex especializado + representación intermedia + heurísticas multi-criterio + IA solo para ambigüedad genuina** constituye un paradigma replicable que supera tanto a la IA pura (cara, no determinista, ventríloqua) como a la automatización algorítmica clásica (frágil, sin comprensión semántica).

La tesis aporta además un **marco disciplinar** propio — la Ingeniería Legal — con método, herramientas y objeto de estudio diferenciados respecto a derecho clásico, legaltech y ciencia de datos aplicada.

El sistema está **en producción** en la Secretaría de Educación de Santander procesando 394 tutelas, con 27 herramientas de agente, 5 pipelines, 40 tests de regresión y 1,092 líneas de documentación académica. Es **evidencia viva** de la viabilidad técnica, económica y profesional de la Ingeniería Legal como disciplina emergente en Colombia.

---

**Repositorio:** Gobernación de Santander — TUTELAS 2026 / tutelas-app
**Documentación completa:** `docs/TESIS_PROYECTO_AGENTE_JURIDICO.md` (1,092 líneas, 12 capítulos)
**Contacto:** Wilson — Ingeniero Legal contratista, Gobernación de Santander
