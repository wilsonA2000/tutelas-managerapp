# Threat Model — Capa de Anonimización PII (v5.3)

> Última revisión: 2026-04-21. Autor: Wilson (ingeniero legal) + plan de v5.3.

## Objetivo

Proteger datos personales identificables (PII) de accionantes, menores y funcionarios contra **divulgación a terceros procesadores de IA** (DeepSeek CN, Anthropic US, Groq/Cerebras/OpenAI US) sin degradar la capacidad del agente jurídico para extraer los 28 campos del protocolo.

El **operador interno autorizado** siempre ve los datos crudos (esto es operación normal — el funcionario tiene responsabilidad legal para procesar tutelas). El problema que resolvemos es que la información salga fuera del entorno autorizado.

## Marco legal

| Ley | Aplicación | Cumplimiento v5.2 | Cumplimiento v5.3 |
|---|---|---|---|
| Ley 1581/2012 (Habeas Data) | Autorización para tratamiento. Transferencia internacional requiere autorización o datos disociados. | ❌ Transferencia a DeepSeek (CN) y US sin autorización | ✅ Datos disociados (selective) / completamente tokenizados (aggressive) |
| Ley 1098/2006 art. 33 | Intimidad de NNA. NUIP de menor es dato especial. | ❌ NUIP literal a IA externa | ✅ `[NUIP_MENOR_1]` siempre |
| Decreto 1377/2013 | Política de tratamiento. Requiere consentimiento explícito. | ⚠️ No hay aviso de privacidad específico | ⚠️ Pendiente (responsabilidad Gobernación) |
| Circular 003/2018 SIC | Transferencia internacional + medidas apropiadas | ❌ Sin medidas | ✅ Anonimización + cifrado AES-128 de mapeos |

## Activos

1. **Nombres completos** de accionantes, menores, abogados.
2. **Cédulas** (CC) — identificador único.
3. **NUIP de menores** (RC) — dato especial, protección reforzada.
4. **Direcciones exactas** (residencia, institución educativa).
5. **Teléfonos y emails** personales.
6. **Diagnósticos médicos detallados** (CIE-10 .x).
7. **Radicados FOREST internos** — identifican casos específicos de la Gobernación.
8. **Fechas exactas** de hechos sensibles.

## Actores y confianza

| Actor | Confianza | Acceso a PII cruda |
|---|---|---|
| Wilson (operador) | 🟢 Alta (funcionario autorizado) | ✅ Sí (UI, DB local) |
| DB SQLite local | 🟡 Media (protegida por OS permissions) | ✅ Sí (pero `pii_mappings` cifrada) |
| Backups `.bak` | 🟡 Media (misma máquina) | ✅ Sí |
| DeepSeek API (CN) | 🔴 Baja (país extranjero, jurisdicción distinta) | ❌ v5.3: no |
| Anthropic API (US) | 🟡 Media (DPA disponible) | ❌ v5.3: no |
| Groq/Cerebras/OpenAI (US) | 🟡 Media | ❌ v5.3: no |
| Tráfico HTTPS interceptado | 🟢 Baja probabilidad (TLS) | ✅ sí ve tokens, no PII |

## Amenazas identificadas

### A1 — Fuga directa de PII a procesador IA (crítica, mitigada)

**Antes v5.3**: DeepSeek recibía nombre, CC, NUIP de menor, diagnóstico exacto en cada llamada. ~90 llamadas/mes → ~300-500 PII únicos al mes.

**Mitigación v5.3**: redactor + gate zero-PII. Reducción medida **96.4%** en selective, **98%** en aggressive.

**Residual**: ~2-4% escapa al detector (nombres raros, CC con OCR sucio). Gate en modo strict bloquea el envío y marca REVISION.

### A2 — Correlación lingüística (baja, no mitigada)

Aunque redactemos identificadores, la IA puede inferir género/edad por contexto gramatical ("la accionante está embarazada", "el menor no puede caminar").

**Mitigación v5.3**: ninguna. Fuera de alcance.
**Propuesta v5.4+**: neutralización morfológica en generación.

### A3 — Fuga por tokens informativos (media, parcialmente mitigada)

Un token como `[MENOR_1_EDAD_6_10_HIJO_ACC1_DX_G80]` preserva demasiada metadata. Combinado con un juzgado y ciudad conocidos, puede permitir re-identificación.

**Mitigación v5.3**: tokens en selective preservan menos info (solo rango edad si aparece). Aggressive tokeniza juzgado y ciudad.
**Calibración**: futuro — reducir metadata en tokens si caso específico lo requiere.

### A4 — Pérdida o rotación de `PII_MASTER_KEY` (media, mitigada operacionalmente)

Si la key se pierde, los mapeos existentes en `pii_mappings` no se pueden descifrar. Los datos en la UI quedarían como tokens.

**Mitigación v5.3**:
- Key en `.env` con backup manual.
- Si falta, el sistema usa key efímera en memoria con warning (nuevos mapeos no sobrevivirán reinicio).
- Rotación: documentar procedimiento cuando se implemente.

### A5 — Acceso no autorizado a DB local (alta)

Si un atacante accede al sistema operativo, lee `data/tutelas.db` directamente.

**Mitigación v5.3**:
- `pii_mappings.value_encrypted` cifrada con Fernet → atacante necesita también `PII_MASTER_KEY`.
- Resto de columnas PII (accionante, CC en `cases` tabla) siguen en claro (por diseño — el operador las usa).
**Propuesta v5.4+**: cifrado at-rest de columnas PII sensibles con decryption transparente para operador autorizado.

### A6 — Reversión por frecuencia de tokens (baja)

Si `[ACCIONANTE_1]` aparece 30 veces y siempre es el mismo valor, ataques de frecuencia sobre muchos casos podrían hipotéticamente correlacionar.

**Mitigación v5.3**: salt por `case_id` impide correlación inter-casos. Dentro del mismo caso, la IA ya sabe que el accionante es único.

## Residual aceptable

- 2-4% de PII puede escapar en el primer mes (falsos negativos del detector). El gate en modo warn permite calibrar antes de activar strict.
- Nombres en modo selective: aceptado por política (son públicos en gacetas judiciales, listas de personeros, autos publicados).
- Correlación lingüística (A2): aceptado por imposibilidad práctica de neutralizar sin IA local.

## Métricas de monitoreo continuo

- `privacy_stats.violations_count` por caso → si crece, recalibrar.
- `privacy_stats.tokens_minted` → distribución esperada 3-10 (selective) / 50-150 (aggressive).
- `privacy_stats.gate_blocked` → bloqueos en strict mode. Umbral alarma: > 5% casos/semana.
- Audit log de cambios `pii_mode` por caso (quién, cuándo, por qué).

## Plan de respuesta a incidente

Si se detecta fuga de PII:
1. Activar `PII_GATE_STRICT=True` y `PII_MODE_DEFAULT="aggressive"` de inmediato.
2. Rotar `PII_MASTER_KEY`. Todos los mapeos viejos quedan inaccesibles (aceptable — re-extrae casos afectados).
3. Notificar a SIC según Art. 17 Ley 1581/2012 si involucra NNA o datos sensibles.
4. Post-mortem documentado en `docs/incidents/`.
