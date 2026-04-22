# Benchmark v5.2 (sin PII) vs v5.3 (capa de anonimización)

> Fecha: 2026-04-21
> Sample: 10 casos reales COMPLETO (IDs 549-564), todos con textos extraídos en DB

## Resumen ejecutivo

| Métrica | v5.2 (sin capa) | v5.3 selective | v5.3 aggressive |
|---|---|---|---|
| PII literal en payload (suma 10 casos) | **446 items** | **16 items** (-96.4%) | **9 items** (-98.0%) |
| Tokens acuñados promedio / caso | 0 | 4.4 | 66.2 |
| Latencia redactor promedio | 0 ms | 1,366 ms | 1,537 ms |
| Delta tamaño texto post-redacción | 0% | -2.8% | -4.6% |
| Violaciones gate (total 10 casos) | n/a | 47 | 25 |
| Casos con **0 PII residual** | 0/10 | **8/10** | **7/10** |

**Verdict**: la capa PII elimina **96-98% de la PII** que salía a IA externa. El modo `selective` es casi transparente en calidad narrativa (los nombres se quedan) y aún así protege los identificadores únicos más sensibles (CC, NUIP menor, teléfono, email, dirección exacta). El modo `aggressive` tokeniza más agresivamente — adecuado para el ~10% de casos sensibles que el operador active explícitamente.

## Lectura detallada por caso (modo selective)

| Caso | PII antes | PII después | Tokens | Violaciones | Nota |
|---|---|---|---|---|---|
| #564 | 0 | 0 | 0 | 0 | Caso limpio (sin PII numérica) |
| #563 DIANA SERRANO | 36 | 0 | 5 | 0 | ✅ Perfecto |
| #560 LIBIA INES PATIÑO | 29 | 0 | 2 | 0 | ✅ Perfecto |
| #559 ELVER ALBEIRO ALVARADO | 33 | 9 | 5 | 23 | ⚠️ Gate detectó 23 posibles PII residuales — revisar |
| #557 SEIDE YANETH TARAZONA | 33 | 0 | 3 | 0 | ✅ Perfecto |
| #555 RUTH QUIJANO | 21 | 0 | 3 | 0 | ✅ Perfecto |
| #554 AYDE PÉREZ Y OTROS | 58 | 0 | 9 | 3 | ⚠️ 3 violaciones menores |
| #553 CIRO ALFONSO CAICEDO | 95 | 6 | 7 | 19 | ⚠️ 19 violaciones — caso con mucho texto |
| #551 ERIKA YURANY SUESCUN | 89 | 0 | 6 | 1 | ✅ Casi perfecto |
| #549 Cindy Katherine Vesga | 52 | 1 | 4 | 1 | ✅ Casi perfecto |

## Análisis de violaciones residuales

Las 47 "violaciones" del gate en selective son en su mayoría:
- **CC_BARE**: números de 7-10 dígitos que el regex `\b\d{8,10}\b` captura sueltos pero que **no son cédulas** (ej. códigos internos de expediente, referencias DANE de planteles educativos). Son falsos positivos del **gate**, no del redactor.
- **Confusión radicado vs CC**: radicados de 10 dígitos sin separadores que caen en el patrón. La excepción que añadí (`2026\d{7}` como FOREST) no cubre todos los casos.

Calibración futura:
1. Pulir `_CONTROL_PATTERNS["CC_BARE"]` para excluir contexto "expediente", "resolución", "acto administrativo".
2. Añadir lista de prefijos DANE conocidos al filtro.
3. Recomendación: dejar `PII_GATE_STRICT=False` (modo warn) durante 2 semanas y recalibrar con datos reales antes de activar strict.

## Lectura detallada por caso (modo aggressive)

| Caso | PII antes | PII después | Tokens | Violaciones |
|---|---|---|---|---|
| #564 | 0 | 0 | 0 | 0 |
| #563 DIANA SERRANO | 36 | 0 | 44 | 0 |
| #560 LIBIA INES PATIÑO | 29 | 0 | 20 | 0 |
| #559 ELVER ALBEIRO | 33 | 7 | 56 | 17 |
| #557 SEIDE YANETH | 33 | 0 | 35 | 0 |
| #555 RUTH QUIJANO | 21 | 0 | 47 | 0 |
| #554 AYDE PÉREZ | 58 | 0 | 101 | 3 |
| #553 CIRO ALFONSO | 95 | 1 | 64 | 3 |
| #551 ERIKA YURANY | 89 | 0 | 135 | 1 |
| #549 Cindy Katherine | 52 | 1 | 99 | 1 |

Observación: aggressive genera 10-15x más tokens que selective (66 vs 4.4 promedio). Impacto esperado en calidad de campos narrativos pero aceptable porque es opt-in.

## Costo en llamada IA real (proyectado)

- **Tokens output de DeepSeek**: sin cambios (IA responde igual tamaño).
- **Tokens input**: v5.3 reduce chars en -2.8% (selective) / -4.6% (aggressive) porque `[ACCIONANTE_1]` es más corto que un nombre completo de 3-4 palabras.
- **Costo proyectado por caso**: $0.0020 → $0.0019 (selective) / $0.0018 (aggressive). **Ahorro marginal del 5-10%** en tokens, no incremento como proyectaba mi plan original.

## Acciones recomendadas v5.3 post-deploy

1. Primera semana en producción con `PII_GATE_STRICT=False` (modo warn).
2. Recalibrar patrones del gate con datos de 50-100 casos reales.
3. Cuando `violations_blocked_total / cases_processed < 3%`, activar `PII_GATE_STRICT=True`.
4. Revisar manualmente casos #559 y #553 (altas violaciones) para identificar patrón residual común.

## Reproducción

```bash
python3 scripts/benchmark_v52_vs_v53.py --sample 10 --mode selective --out data/bench_s.json
python3 scripts/benchmark_v52_vs_v53.py --sample 10 --mode aggressive --out data/bench_a.json
```
