# IURIS — Estrategia de Propiedad Intelectual (Colombia, 2026)

> Titular: **Wilson Arguello**, Ingeniero Legal contratista, Gobernación de Santander.
> Producto: **IURIS** — appliance jurídico on-prem para procesamiento neurosimbólico de tutelas.
> Marco normativo: Decisión 486/2000 CAN, Ley 23/1982, Ley 1581/2012, Decreto 410/2002, Ley 1648/2013.

---

## ⚠️ Hallazgo crítico de investigación

**Los programas de computador "como tales" NO son patentables en Colombia ni como modelo de utilidad.** Lo dice expresamente la SIC.

Lo que sí se puede:
- **Software puro** → derecho de autor (DNDA, gratis, automático desde la creación).
- **Sistema integrado hardware+software con configuración técnica novedosa** → modelo de utilidad (sí aplica).
- **Invención implementada por computadora con efecto técnico concreto** → patente de invención (más exigente, más costosa).

Esto **redirige la estrategia**: el modelo de utilidad debe redactarse sobre el **appliance físico IURIS** y su arquitectura de procesamiento, no sobre el software del pipeline cognitivo.

---

## 4 capas de protección recomendadas

### Capa 1 — Marca SIC "IURIS" (PRIMERA, urgente)

| Concepto | Detalle |
|----------|---------|
| Tipo | Marca mixta (denominación + logo) |
| Clases Niza | Clase 9 (software, dispositivos electrónicos) + Clase 42 (servicios SaaS, consultoría tecnológica) |
| Costo SIC 2026 | $620.000 COP por clase × 2 clases = $1.240.000 COP (~$310 USD) |
| Reducción 25% si Mipyme | Sí aplica (registrar empresa antes) → $930.000 COP |
| Tiempo concesión | 6-9 meses si no hay oposiciones |
| Vigencia | 10 años renovables indefinidamente |
| Trámite | Online vía https://www.sic.gov.co o presencial Bogotá |

**Acción**: ver `legal/TRADEMARK_SIC_DRAFT.md`.

### Capa 2 — Derecho de Autor DNDA (INMEDIATA, gratis)

| Concepto | Detalle |
|----------|---------|
| Tipo | Inscripción de soporte lógico (software) |
| Costo | **GRATIS** (Dirección Nacional de Derecho de Autor) |
| Tiempo | 30 días |
| Marco | Ley 23/1982, Decisión 351/1993 CAN |
| Cubre | Código fuente del pipeline tutelas-app v6+, manuales técnicos, documentación |
| Plazo de protección | Vida del autor + 80 años |
| Trámite | Online vía https://www.derechodeautor.gov.co |

**Valor probatorio**: en caso de copia desleal, el certificado DNDA es prueba de fecha cierta de creación. Crítico para defender capa cognitiva si un competidor la replica.

**Acción**: ver `legal/DNDA_COPYRIGHT_DRAFT.md`.

### Capa 3 — Modelo de Utilidad (estratégica, 6-18 meses)

**Objeto a proteger**: NO el software, sino el **sistema appliance IURIS** entendido como producto físico con configuración técnica novedosa.

**Reivindicaciones núcleo posibles** (deben pulirse con abogado de PI):

1. *"Dispositivo embebido para procesamiento neurosimbólico de documentos jurídicos, caracterizado por una arquitectura de cómputo edge que integra una unidad de procesamiento con acelerador de inferencia, una capa de extracción determinística por zonas físicas del documento, y un módulo bayesiano de asignación documental con razones de verosimilitud calibradas por señal física del documento (sello rotado, posición zonal), todo dentro de un único enclosure portable."*

2. *"Configuración hardware-software del dispositivo según reivindicación 1, donde el módulo bayesiano produce decisiones de asignación con umbrales duales (aceptación ≥0.92, rechazo ≤0.08) y bandas explicativas legibles human-readable que documentan razones a favor/contra cada asignación."*

3. *"Sistema según reivindicación 1 donde el procesamiento neurosimbólico opera en modo offline absoluto sin transmisión de datos del usuario a servidores externos, garantizando cumplimiento de Ley 1581/2012 colombiana de Habeas Data."*

| Concepto | Detalle |
|----------|---------|
| Costo SIC 2026 (sin reducción) | ~$1.500.000 COP (~$370 USD) |
| Reducción 25% Mipyme | $1.125.000 COP |
| Tiempo concesión | 12-24 meses |
| Vigencia | **10 años no renovables** desde solicitud |
| Marco | Decisión 486/2000 CAN art. 81-87 |
| Riesgo de oposición | Medio-bajo (tu arquitectura es novel en Colombia) |

**Recomendación**: contratar abogado de PI especializado en software (~$3-5M COP honorarios, una sola vez). Vale la pena.

**Acción**: ver `legal/UTILITY_MODEL_DRAFT.md`.

### Capa 4 — Trade Secrets (PERMANENTE, $0)

**Qué proteger:**
- Código de la capa cognitiva (`backend/cognition/`) — mantener cerrado, no open-source.
- Calibración de priors bayesianos y LRs por zona física.
- Corpus dorado de tutelas anotadas.
- Configuración exacta de modelos cuantizados y kernels custom.

**Cómo:**
- NDA estándar con todo cliente del appliance (incluido en EULA del producto).
- Cifrado at-rest del código entregado en cada appliance (LUKS / FileVault equivalente).
- Servidor central de licencias verifica integridad; si alguien intenta extraer el modelo, el appliance se autoinhabilita.
- Cláusula de auditoría de procedencia en el contrato de venta.

**Marco**: Decisión 486/2000 CAN art. 260-266 (secreto empresarial). Protección sin trámite, indefinida, mientras se mantenga la confidencialidad.

---

## Cronograma sugerido

| Mes | Acción | Costo COP | Estado |
|-----|--------|-----------|--------|
| Mayo 2026 | Inscribir empresa Mipyme (LegalEntity Colombia) para obtener reducción 25% en tasas | $200.000 | Pendiente |
| Mayo 2026 | DNDA derecho de autor sobre código tutelas-app v6 | $0 | Inmediato |
| Junio 2026 | Marca SIC "IURIS" + logo (clases 9 y 42) | $930.000 | Pendiente |
| Jun-Jul 2026 | Búsqueda fonética + figurativa SIC (verificar disponibilidad) | $50.000 | Pendiente |
| Agosto 2026 | Contratar abogado PI especialista | $3-5M (one-time) | Pendiente |
| Sep-Oct 2026 | Solicitud Modelo de Utilidad sobre appliance IURIS | $1.125.000 | Pendiente |
| 2027 (post-validación) | Eventual patente de invención si tracción comercial confirma valor | $5-10M | Condicional |

**Total Mipyme + sin patente: ~$5-7M COP one-time** (~$1,200-1,750 USD).

---

## Patentes ajenas — análisis defensivo

**Riesgo bajo (libres de uso):**
- PaddleOCR (Apache 2.0) — sin patentes problemáticas activas.
- llama.cpp / bitnet.cpp (MIT) — Microsoft liberó BitNet sin patentar.
- GGUF / quantization formats — públicos.
- FastAPI, React, SQLite, Postgres — todos seguros.

**Riesgo medio (uso autorizado por SDK):**
- TensorRT-LLM optimizations (NVIDIA) — el uso del SDK Jetson otorga licencia implícita.
- CUDA libraries — idem.

**Riesgo alto (evitar replicar):**
- Patentes específicas de Microsoft sobre arquitectura BitNet (si las presenta a futuro). Mitigación: usar el framework oficial bitnet.cpp como cliente, no reimplementar el algoritmo.
- Patentes Apple sobre Neural Engine y MLX → solo importa si pivotas a Mac mini (descartado).

---

## Decisiones que necesito de Wilson

1. **¿Registramos empresa Mipyme primero (esta semana) para obtener reducción 25% en tasas?** Sin esto pagas un 25% más en marca y modelo de utilidad.
2. **¿Avanzo con DNDA derecho de autor (gratis) en paralelo a otras tareas?** Tarda 30 días, sin costo.
3. **¿Contratamos abogado PI en agosto o intentas auto-presentar el modelo de utilidad para ahorrar honorarios?** (Auto-presentar es legal pero el rechazo formal es 60-70% más probable).
4. **¿Qué nombre comercial registramos junto a "IURIS"?** Opciones: "Arguello Legal Engineering", "IURIS by W. Arguello", "Iuris Tech Colombia SAS".

---

## Fuentes
- [SIC — Patente de Modelo de Utilidad (oficial)](https://www.sic.gov.co/patente-de-modelo-de-utilidad)
- [SIC — Tasas Patentes 2026](https://www.sic.gov.co/tasas-patentes)
- [SIC — Qué se puede patentar como modelo de utilidad](https://www.sic.gov.co/node/37)
- [DNDA — Derecho de Autor Colombia](https://www.derechodeautor.gov.co)
- [Decisión 486/2000 CAN — Régimen Común sobre Propiedad Industrial](http://www.comunidadandina.org/Normativa.aspx)
