# Estrategia LLM, soberanía de datos y hardware — Tutelas App

> Investigado 2026-06-22. Insumo para decisión de arquitectura. **No es asesoría legal**:
> el punto de protección de datos debe confirmarlo el oficial de protección de datos /
> oficina jurídica de la Gobernación.

## 1. Soberanía de datos (Ley 1581/2012) — el punto crítico

- La **Ley 1581 de 2012** prohíbe la transferencia internacional de datos personales a
  países **sin "nivel adecuado de protección"** según la lista de la **SIC**.
- **Lista de países adecuados** (SIC): Alemania, EE.UU., España y resto de UE, Reino Unido,
  Japón, **Corea del Sur**, México, Perú, Costa Rica, Serbia, etc.
  **China NO está en la lista.**
- **DeepSeek** (sus propios términos): operado por **Hangzhou DeepSeek (China)**; datos
  **almacenados en servidores en China continental**; inputs retenidos ~30 días, logs ~90
  días; inputs/outputs pueden usarse para mejorar el modelo (con opt-out).
- Los datos de tutelas son **datos sensibles** (judiciales + salud + menores) → protección
  reforzada, y son **datos de una entidad pública** → estándar más estricto.
- **Riesgo:** mandar PII de tutelas directo a DeepSeek/China **muy probablemente infringe
  la Ley 1581** (sin adecuación, datos sensibles, datos del Estado). Vías de cumplimiento:
  (a) consentimiento expreso del titular (impráctico en tutelas), (b) **anonimización
  previa** (si se quitan nombres/cédulas/etc., deja de ser dato personal → no hay
  transferencia regulada), o (c) declaración de conformidad ante la SIC.

> **Puente técnico:** reintroducir la capa de anonimización (la plataforma la tuvo y se
> quitó por LOCAL_ONLY) **antes** de llamar a la nube hace viable un tier en la nube.

## 2. Modelo de negocio (revender API / premium)

- Los términos de DeepSeek **permiten** integrar sus modelos en una app/servicio para
  usuarios finales (R1 es MIT). Construir un **tier premium sobre la plataforma** = SaaS
  normal y válido. Revender la API "en crudo" (passthrough) es más gris; el valor agregado
  (la plataforma) es el modelo seguro.
- El límite real **no son los términos, es la ley de datos**: para datos de gobierno /
  judiciales se necesita anonimización **o** un proveedor en país adecuado.
- **Mejor jugada legal que DeepSeek:** modelo en la nube **alojado en EE.UU.**
  (Anthropic / OpenAI / Azure) — EE.UU. **sí está en la lista** → transferencia permitida.
  Más caro que DeepSeek, pero legal para datos del Estado. China no lo es.
- Tier sugerido: **4B local = básico**; **nube = premium** (eligiendo proveedor por
  compatibilidad legal, no por precio: US-hosted ≫ China-hosted).

## 3. Hardware — la vía que resuelve calidad Y soberanía a la vez

| Opción | Precio (2026) | LLM local | Veredicto |
|---|---|---|---|
| **NVIDIA DGX Spark** | ~$3,999 (subió a $4,699 feb-2026) | hasta 200B quant; 70B FP16 (128GB unificada) | 🏆 salto enorme |
| **Jetson AGX Orin 64GB** | ~$1,999 | 4-20B cómodo; 30B MoE (Qwen3-30B-A3B ~61 tok/s) ajustado | 👍 punto medio |
| **Jetson Orin Nano Super** | ~$249 | hasta ~8B | ❌ apenas mejor que el 4B actual |

**Insight clave:** un **DGX Spark** (o AGX Orin 64GB) corre un **30B-70B LOCAL** → calidad
clase-DeepSeek **sin que los datos salgan del país** → resuelve calidad + soberanía a la vez.
Para un appliance jurídico con PII, ese es el camino ideal a futuro.

## Síntesis / recomendación
1. No mandar PII de tutelas a DeepSeek/China tal cual (riesgo Ley 1581) — confirmar con jurídica.
2. El mejor producto premium no es revender API extranjera, es el **appliance local potente**
   (DGX Spark + plataforma) vendible como caja cerrada, compliant, offline.
3. Por fases: hoy 4B local básico → con hardware (AGX Orin ~$2k entrada, DGX Spark ~$4k meta)
   30-70B local premium, sin tocar la ley.
4. Si se usa nube ya: **anonimizar primero** o proveedor **US-hosted** (en la lista), nunca China para datos del Estado.

## Decisión tomada por Wilson (2026-06-22)
Migrar la plataforma a **DeepSeek API** (retirar el 4B local), aceptando la limitación de
recursos para hardware mayor. **Pendiente de gestión legal:** anonimización previa o
autorización/SIC para el envío de datos a servidores en China. Ver implementación en la
sesión de migración.

## Fuentes
- Ley 1581/2012 — Función Pública: https://www.funcionpublica.gov.co/eva/gestornormativo/norma.php?i=49981
- SIC, transferencia internacional: https://www.sic.gov.co/sites/default/files/files/Proteccion_Datos/consulta_avanzada/TRANSFERENCIA-INTERNACIONAL-DE-DATOS-PERSONALES-09-03-2017.pdf
- Régimen de transferencias — Ámbito Jurídico: https://www.ambitojuridico.com/noticias/comercial/regimen-de-transferencias-internacionales-de-datos-personales-una-guia-rapida
- DeepSeek Privacy Policy: https://cdn.deepseek.com/policies/en-US/deepseek-privacy-policy.html
- DeepSeek Open Platform ToS: https://cdn.deepseek.com/policies/en-US/deepseek-open-platform-terms-of-service.html
- NVIDIA DGX Spark: https://www.nvidia.com/en-us/products/workstations/dgx-spark/
- Jetson AGX Orin / Orin Nano: https://www.nvidia.com/en-us/autonomous-machines/embedded-systems/jetson-orin/
