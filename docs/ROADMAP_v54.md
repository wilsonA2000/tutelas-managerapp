# Roadmap v5.4 — IA local (cuando haya presupuesto hardware)

> Estado: propuesta. Condición: aprobación de recurso hardware por Gobernación.

## Contexto

En v5.3, incluso con la capa de anonimización, **seguimos enviando texto a proveedores internacionales** (DeepSeek CN, Anthropic US). La anonimización reduce el riesgo a "tokens estructurales sin PII directa", pero no lo elimina:
- Metadata en tokens (rango edad, región) podría correlacionarse.
- Correlación lingüística (género/edad por contexto) no se mitiga.
- Depende de la precisión del detector — si falla, fuga.

**La única solución definitiva: no enviar absolutamente nada fuera de la máquina de Wilson.**

## Solución: IA local

### Stack propuesto

| Componente | Opción recomendada | Alternativas | Notas |
|---|---|---|---|
| Runtime | **Ollama** | llama.cpp, vLLM | Más simple, instalación 1 comando |
| Modelo principal | **Qwen 2.5 14B Instruct Q4_K_M** (~9 GB) | Qwen 3 30B MoE (~18 GB), Llama 3.3 70B Q3 (~30 GB) | Español jurídico sólido |
| Modelo fallback | **Qwen 2.5 7B Instruct Q5** (~6 GB) | Mistral Small 24B | Si VRAM limitada |
| Integración | Cliente OpenAI-compatible | Ollama API nativa | Ollama expone `/v1/chat/completions` |

### Hardware mínimo / recomendado

| Escenario | Especificación | Throughput esperado | Costo estimado |
|---|---|---|---|
| **Mínimo**: CPU only | 32 GB RAM DDR4, sin GPU | 5-10 tokens/s | $0 (usa hardware existente) |
| **Recomendado**: GPU dedicada | RTX 4060 8 GB VRAM + 16 GB RAM | 40-60 tokens/s | ~$1,500 USD laptop/PC |
| **Óptimo**: GPU premium | RTX 4090 24 GB / workstation SED | 150+ tokens/s, Qwen 30B | ~$4,000 USD workstation |

Con 90 llamadas/mes y promedio 4,500 tokens input + 500 output por llamada:
- Mínimo: ~15 minutos por llamada (aceptable para batch nocturno, no para re-extract interactivo).
- Recomendado: ~90 segundos por llamada (aceptable interactivo).
- Óptimo: ~30 segundos por llamada (casi idéntico a IA cloud actual).

## Integración con arquitectura existente

### 1. Nuevo provider en `ai_extractor.py`

```python
PROVIDERS["local"] = {
    "name": "IA local (Ollama)",
    "models": {
        "qwen2.5:14b-instruct-q4_K_M": {
            "label": "Qwen 2.5 14B (local)",
            "input_price": 0, "output_price": 0,  # Gratis
            "max_tokens": 8192, "context_window": 131072,
            "multimodal": False,
            "best_for": ["extraction", "general", "complex_reasoning", "legal_analysis"],
        },
    },
    "env_key": "OLLAMA_HOST",  # e.g. http://localhost:11434
}


def _call_ollama(messages, model, max_tokens, system_prompt) -> dict:
    """Llama al endpoint local de Ollama (OpenAI-compatible)."""
    import httpx
    host = os.getenv("OLLAMA_HOST", "http://localhost:11434")
    r = httpx.post(f"{host}/v1/chat/completions", json={
        "model": model, "messages": messages,
        "max_tokens": max_tokens, "temperature": 0.1,
    }, timeout=300)
    r.raise_for_status()
    return r.json()
```

### 2. Prepend al routing chain en `smart_router.py`

```python
# En route(), antes de iterar ROUTING_CHAINS:
if os.getenv("OLLAMA_HOST") and _ollama_healthcheck():
    # IA local disponible → úsala antes que cualquier provider remoto
    return RouteDecision(
        provider="local", model="qwen2.5:14b-instruct-q4_K_M",
        reason="IA local Ollama (sin PII fuera del host)",
        cost_per_1m_input=0, cost_per_1m_output=0,
        context_window=131072,
    )
```

### 3. Capa PII **sigue activa**

Incluso con IA local, mantener el redactor/rehidrator por:
- **Defensa en profundidad**: si un día accidentalmente se cambia `OLLAMA_HOST` y cae a un remoto, la redacción aún protege.
- **Logs de auditoría**: `privacy_stats` sigue recolectando métricas útiles.
- **Portabilidad**: si en el futuro se migra parte de la carga a cloud privado, el código ya está listo.

Podrá relajarse **modo por defecto** a `selective` con confianza plena (la IA local ve todo pero no sale de la máquina).

### 4. Dockerfile (opcional) para despliegue reproducible

```dockerfile
FROM ollama/ollama:latest
# Model warmup en build time:
RUN ollama serve & sleep 5 && ollama pull qwen2.5:14b-instruct-q4_K_M
# ... resto del stack
```

## Plan de fases para v5.4

1. **Fase 1 — Prueba concepto** (1 día): Wilson instala Ollama en su laptop actual y corre Qwen 2.5 7B sobre 5 casos. Mide calidad vs DeepSeek.
2. **Fase 2 — Propuesta formal** (1 semana): Wilson redacta informe con benchmark para solicitar hardware a la Gobernación, apoyado en `docs/PRIVACY_THREAT_MODEL.md` y `docs/BENCHMARK_V52_V53.md`.
3. **Fase 3 — Adquisición hardware** (1-3 meses): proceso interno de la Gobernación.
4. **Fase 4 — Integración** (2 días): añadir `_call_ollama`, routing, tests.
5. **Fase 5 — Migración** (1 semana): casos nuevos usan local por defecto, cloud como fallback emergencia.

## Entregables cuando se apruebe v5.4

- [ ] `backend/extraction/ai_extractor.py`: `PROVIDERS["local"]` + `_call_ollama()`.
- [ ] `backend/agent/smart_router.py`: prepend local al routing chain.
- [ ] `scripts/setup_ollama.py`: instalación + pull modelo idempotente.
- [ ] `tests/test_ai_local.py`: smoke test con Qwen 2.5 7B o mock.
- [ ] `docs/BENCHMARK_V54_LOCAL.md`: comparativa calidad IA local vs cloud.
- [ ] Update `.env.example` con `OLLAMA_HOST=http://localhost:11434`.
- [ ] Update `CLAUDE.md`: regla #3 → "IA local primary con Ollama/Qwen 14B, cloud solo emergencia".

## Beneficios de v5.4 (cuando se implemente)

| Dimensión | v5.3 (actual) | v5.4 (IA local) |
|---|---|---|
| PII fuera de la máquina | 🟡 Solo tokens (96-98% reducción) | 🟢 **CERO** — nada sale |
| Cumplimiento habeas data | ✅ Parcial (datos disociados) | ✅ Total (sin transferencia) |
| Costo por llamada | ~$0.002 (DeepSeek) | $0 (electricidad) |
| Latencia | 2-4s | 1-3s (con GPU) |
| Dependencia red | Alta (si falla red, falla IA) | Nula (offline-capable) |
| Calidad campos narrativos | 92% (selective) | 88-92% (Qwen 14B) |
| Privacidad correlación | ⚠️ Residual (A2 threat model) | ✅ No aplica |
