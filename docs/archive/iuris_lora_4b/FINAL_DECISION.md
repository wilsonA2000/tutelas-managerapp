# IURIS — Decisión Final de Hardware (2026-05-02, actualizada)

> Objetivo: cerrar la decisión hardware después de revisión completa, incluyendo opciones que aparecieron en investigación (Strix Halo Ryzen AI MAX+ 395) y combinaciones óptimas (BitNet sobre CUDA).

---

## 🏆 DECISIÓN FINAL: Línea de producto IURIS de TRES SKUs

| SKU | Hardware | BOM | PVP | Margen | Target |
|-----|----------|-----|-----|--------|--------|
| **IURIS Lite** | ThinkCentre Tiny refurb + BitNet | ~$300 | $1,200 | 75% | Personerías, alcaldías pequeñas |
| **IURIS Pro** | Jetson Orin Nano Super + bitnet.cpp + CUDA | ~$450 | $1,800 | 75% | Gobernaciones, juzgados, secretarías medianas |
| **IURIS Max** | Strix Halo Framework Desktop 128GB | ~$2,800 | $4,500 | 38% | Tribunales superiores, ministerios, multi-usuario |

**Producto bandera para lanzamiento (julio 2026): IURIS Pro.**

---

## Por qué IURIS Pro como flagship

### Combinación ganadora: Jetson + BitNet en el mismo dispositivo

El secreto técnico: **no es Jetson XOR BitNet. Es Jetson CON BitNet.**

- **Jetson Orin Nano Super**: CUDA nativo para PaddleOCR, embeddings, vector store, reranker.
- **BitNet 2B4T sobre el mismo Jetson**: kernels ternarios consumen 0.4 GB en lugar de 4-5 GB de Llama 8B Q4. Performance equivalente para razonamiento jurídico (validar contra corpus dorado).
- **Resultado**: el cuello de botella de 8 GB del Jetson **desaparece**. Quedan ~6 GB libres para OCR + embeddings + base de datos + cache.

Comparativa con la opción "Jetson + Llama 8B Q4" (lo que recomendé antes):

| Métrica | Llama 8B Q4 | BitNet 2B4T | Mejora |
|---------|--------------|-------------|--------|
| RAM consumida por LLM | 4.3 GB | 0.4 GB | **10×** |
| Energía por token | 0.347 J | 0.028 J | **12×** |
| Calidad razonamiento (estimado) | 100% baseline | 85-95% baseline | -10% (aceptable, validar) |
| Headroom para otros módulos | 1.5 GB | 5.5 GB | **3.6×** |

### Ventajas estratégicas IURIS Pro

1. **NVIDIA Inception badge** — co-marketing oficial, prensa, roadmap privilegiado.
2. **CUDA stack preservado** — pipeline actual corre sin refactor (ahorra 2-3 semanas de trabajo).
3. **Power 7-25W, fanless** con disipador pasivo → silencio total, ideal para oficinas jurídicas.
4. **Tamaño 100×79mm** — más chico que Mac mini, cabe en portafolio.
5. **BOM bajo** ($249 + $40 SSD + $80 carcasa CNC = $369), margen 75% a $1,800 PVP.
6. **Pre-instalación encriptada** (LUKS) → secret empresarial protegido por hardware.

### Riesgos identificados y mitigaciones

| Riesgo | Probabilidad | Mitigación |
|--------|--------------|-------------|
| BitNet calidad < esperada en español jurídico | Media | Validar primero contra 50 casos dorados; fallback a Phi-3-mini Q4 si falla |
| Jetson 8GB techo con 2 usuarios concurrentes | Alta | Documentar "1 usuario por appliance" en SLA; vender IURIS Max para multi-tenant |
| Importación a Colombia ($249 → $1.7M nacionalizado) | Alta | Comprar lote de 5 vía Amazon US para promediar costos; explorar bulk via ThinkRobotics India |
| Límite 4 unidades/cuenta NVIDIA para R&D | Baja | Aplicar a cuenta empresarial Mipyme una vez registrada |

---

## Por qué descartar Mac mini M4 (definitivamente)

Investigación legal confirma que **Apple prohíbe explícitamente** que terceros usen el nombre "Apple", "Mac mini", o variaciones, como parte del nombre de producto comercializado. Solo se permite uso referencial ("compatible con Mac mini"). Esto significa que **IURIS no puede revender Mac minis embebidos** sin entrar en zona gris legal con Apple Trademark guidelines.

Apple además exige Authorized Service Provider para cualquier programa serio de hardware embebido — requisitos: registros financieros auditados, líneas de crédito aprobadas por Apple Finance, certificación de técnicos, auditorías periódicas. Inviable para Wilson en 2026.

**Conclusión**: Mac mini sigue siendo excelente para tu workstation personal, pero **NO viable como base del appliance IURIS comercial**.

---

## Por qué IURIS Max (Strix Halo) es el siguiente nivel

El AMD Ryzen AI MAX+ 395 "Strix Halo" es un quantum leap real:

- **128 GB LPDDR5X-8000** (memoria unificada, 256 GB/s)
- **40 CUs RDNA 3.5** + 50 TOPS XDNA 2 NPU
- Corre **modelos 70B-122B** localmente a 19 tok/s
- Performance comparable a M4 Pro para inferencia LLM
- Plataformas: Framework Desktop ($2,599), Minisforum MS-S1 Max ($2,799), Beelink GTR9 Pro v2.2 ($4,399), HP Z2 Mini G1a (enterprise)

**Caso de uso para IURIS Max:**
- Tribunal Superior procesa 5,000 tutelas/mes, 10 funcionarios concurrentes.
- Necesita Llama 70B para razonamiento jurídico de alta complejidad.
- Tiene presupuesto $5,000-10,000 USD para una estación que reemplace 3 puestos de trabajo.

**No vendes esto a personerías municipales. Vendes a entidades top-tier.**

Refactor pipeline para Strix Halo: 1-2 semanas (port CUDA → ROCm/Vulkan via llama.cpp, ya soportado).

---

## Plan de ejecución 4 semanas

### Semana 1 (mayo 5-11, 2026)
- ☐ Compra **1 Jetson Orin Nano Super** vía Amazon US (~$320 nacionalizado a Colombia, llega 7-14 días).
- ☐ Inscribe Mipyme en Cámara de Comercio Bucaramanga (lunes, $200K COP, desbloquea reducción 25% SIC).
- ☐ Inicia DNDA derecho de autor en línea (gratis, 30 días).
- ☐ En paralelo: instala `bitnet.cpp` sobre tu workstation actual y prueba **BitNet 2B4T** contra 20 casos de tu corpus.

### Semana 2 (mayo 12-18)
- ☐ Mide calidad BitNet vs DeepSeek/Haiku en los 5 campos cognitivos (forest_impugnacion, responsable_desacato, etc.).
- ☐ Llega Jetson — instala JetPack 6.x + bitnet.cpp + tutelas-app.
- ☐ Benchmark end-to-end: tiempo por caso, RAM peak, calidad output.
- ☐ Diseño 3D del enclosure CNC (Fusion 360 / Bucaramanga local taller mecanizado).

### Semana 3 (mayo 19-25)
- ☐ Corte y mecanizado primer prototipo de carcasa IURIS Pro.
- ☐ Integración firmware: boot directo a IURIS UI, MAC address como ID de licencia.
- ☐ Búsqueda fonética SIPI marca "IURIS" ($50K COP).
- ☐ Pago tasa SIC marca clases 9 y 42 ($930K COP con reducción Mipyme).

### Semana 4 (mayo 26-junio 1)
- ☐ Demo en piloto: Personería de Floridablanca o Bucaramanga.
- ☐ Solicitud modelo de utilidad SIC con abogado PI ($3-5M COP honorarios + $1.125M COP tasas).
- ☐ Decisión condicional: si BitNet pasa validación → ramping IURIS Lite con refurb mini PCs.

---

## Decisiones inmediatas confirmadas (sin esperar más respuestas)

A menos que digas lo contrario, asumo:
1. ✅ Hardware flagship: **IURIS Pro = Jetson Orin Nano Super + BitNet 2B4T**.
2. ✅ Compras Jetson esta semana ($320).
3. ✅ Inscribes Mipyme antes de fin de mayo.
4. ✅ Marca SIC + DNDA antes de junio.
5. ✅ Modelo de utilidad post-validación piloto (julio-agosto).
6. ✅ Strix Halo (IURIS Max) queda en backlog para Q4 2026 si tracción justifica.

---

## Fuentes adicionales (esta investigación)
- [Strix Halo Local LLM Guide (GitHub)](https://github.com/hogeheer499-commits/strix-halo-guide)
- [Strix Halo Real LLM Workflows (Medium)](https://medium.com/@orami98/strix-halo-unleashed-real-llm-workflows-on-128gb-ryzen-ai-max-395-mini-pcs-and-laptops-5dabdd3fcae3)
- [Minisforum MS-S1 Max AMD AI Max+ 395 Review](https://akitaonrails.com/en/2026/03/31/minisforum-ms-s1-max-amd-ai-max-395-review/)
- [BitNet b1.58 Technical Report (arxiv)](https://arxiv.org/html/2504.12285v1)
- [How to Run BitNet B1.58 Locally](https://onedollarvps.com/blogs/how-to-run-bitnet-b1-58-locally)
- [Apple Trademark Guidelines for 3rd Parties](https://www.apple.com/legal/intellectual-property/guidelinesfor3rdparties.html)
- [Apple Authorized Service Provider Program](https://support.apple.com/aasp-program)
- [NVIDIA Jetson Edge AI Generative Open Source](https://blogs.nvidia.com/blog/jetson-generative-ai-edge-oss/)
