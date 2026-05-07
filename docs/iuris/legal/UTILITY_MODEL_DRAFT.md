# Borrador — Solicitud de Patente de Modelo de Utilidad

> Trámite: Patente de Modelo de Utilidad
> Vía: SIC, formulario PI-2 + memoria descriptiva + reivindicaciones + dibujos
> Marco: Decisión 486/2000 CAN art. 81-87, Circular Única SIC

---

## ⚠️ Lectura previa importante

En Colombia, **el software "como tal" NO se patenta como modelo de utilidad**. Solo se protege la **configuración técnica novedosa de un producto físico**. Por ello esta solicitud se redacta sobre el **dispositivo IURIS como sistema appliance integrado hardware-software**, no sobre el algoritmo del pipeline cognitivo (que se protege por derecho de autor — ver `DNDA_COPYRIGHT_DRAFT.md`).

Si se pretende proteger la lógica algorítmica con efecto técnico, debe considerarse en cambio una **patente de invención** (más exigente, mayor costo, plazo 20 años). Ver sección final.

---

## 1. Datos del solicitante

| Campo | Valor |
|-------|-------|
| Inventor | Wilson Arguello |
| Cédula | [completar] |
| Domicilio | Bucaramanga, Santander, Colombia |
| Email | wilsonarguello@distribuidoraavisander.com |
| Solicitante | (Misma persona natural o IURIS TECH COLOMBIA SAS) |
| País | Colombia |

---

## 2. Título de la invención

**"DISPOSITIVO APPLIANCE EMBEBIDO PARA PROCESAMIENTO NEUROSIMBÓLICO LOCAL DE DOCUMENTOS JURÍDICOS, CON ASIGNACIÓN BAYESIANA DE DOCUMENTOS A EXPEDIENTES Y AUDITABILIDAD DE RAZONES"**

---

## 3. Sector técnico

Hardware embebido para procesamiento documental especializado en el ámbito jurídico, con énfasis en gestión de tutelas y procesos judiciales del sistema legal colombiano.

---

## 4. Estado de la técnica (referencias a superar)

Las soluciones existentes para gestión documental jurídica presentan los siguientes inconvenientes:

1. **Soluciones SaaS en nube** (LegalSec, Tu Asesor Legal, Lex Solo, etc.): requieren transmisión de datos personales sensibles a servidores externos, lo cual genera riesgo de incumplimiento de la Ley 1581 de 2012 (Habeas Data) y Decreto 1377 de 2013.
2. **Software de escritorio local** (LegalCase, Justify, etc.): no integran procesamiento de inteligencia artificial; requieren intervención humana intensiva en clasificación documental.
3. **Servicios de IA legal con LLM en nube** (LawGeex, Harvey, etc.): mismos problemas de transmisión de datos + costo recurrente alto + dependencia conectividad.
4. **Soluciones edge AI genéricas** (Jetson, mini PC con Ollama): requieren configuración técnica avanzada por usuario final; no incluyen pipeline jurídico ni razonamiento neurosimbólico calibrado al derecho colombiano.

**Lo que falta en el estado de la técnica:** un dispositivo físico cerrado, plug-and-play, que combine hardware embebido + capa cognitiva de extracción + módulo bayesiano de asignación documental + procesamiento 100% local sin transmisión externa, específicamente calibrado para tutelas colombianas.

---

## 5. Descripción de la invención

El dispositivo IURIS es un **appliance embebido** con las siguientes características técnicas estructurales:

### 5.1 Composición física

- Carcasa cerrada con disipación pasiva o activa controlada, con dimensiones máximas 150×150×60mm.
- Unidad de procesamiento principal (UPP) con acelerador de inferencia neuronal (NPU/GPU integrado o externo según versión).
- Memoria volátil (RAM) entre 8 GB y 32 GB.
- Almacenamiento no volátil SSD M.2 NVMe entre 256 GB y 2 TB.
- Interfaz de red Ethernet Gigabit y/o WiFi 6.
- Puertos USB 3.x y al menos un puerto HDMI/DisplayPort opcional.
- Botón de encendido único; sin BIOS configurable por usuario final.
- Dispositivo de seguridad TPM 2.0 o equivalente para cifrado at-rest.

### 5.2 Software preinstalado (componente integrado al producto)

- Sistema operativo Linux endurecido (hardened) con servicios mínimos.
- Pipeline de procesamiento documental con **siete capas cognitivas secuenciales**:

  - **Capa 0**: Percepción física del documento (firma visual, sellos, calidad de OCR).
  - **Capa 1**: Tipología documental (clasificación contradicciones nombre vs contenido).
  - **Capa 2**: Identificadores canónicos (radicados, FOREST, números de fallo) con razones de verosimilitud (LR) calibradas por zona física del documento.
  - **Capa 3**: Grafo de actores (correferencia, litisconsorcio, deduplicación).
  - **Capa 4**: Línea de tiempo procesal (clasificación TUTELA / INCIDENTE_HUERFANO / AMBIGUO; estado del incidente).
  - **Capa 5**: Asignación bayesiana documento-expediente con priors calibrados, LRs por señal, y umbrales duales de aceptación (≥0.92) / rechazo (≤0.08), con generación de **listas legibles human-readable de razones a favor y en contra** de cada asignación.
  - **Capa 6**: Consolidador en vivo (live consolidator) que fusiona expedientes huérfanos a padres y deduplica documentos similares con score ≥0.85.
  - **Capa 7**: Persistencia cognitiva con compuerta de entropía (entropy gate); las contradicciones siempre fuerzan estado de revisión humana.

### 5.3 Modos de operación

- **Modo offline absoluto**: el dispositivo NO transmite ningún dato del usuario a servidores externos durante la operación normal.
- **Modo licenciamiento**: contacto periódico cifrado a servidor central de licencias para validar suscripción activa, sin transmisión de contenido documental.
- **Modo backup**: respaldos cifrados localmente, exportables a almacenamiento externo USB o NAS local del usuario.

### 5.4 Características técnicas distintivas frente al estado de la técnica

(a) Integración hardware+software preinstalado como **producto físico cerrado**, no como software descargable.

(b) Procesamiento **100% local** del contenido documental, garantizando cumplimiento Habeas Data sin auditoría compleja de tránsito de datos.

(c) Módulo bayesiano con **razones explícitas legibles** human-readable a favor y en contra, lo que constituye una ventaja técnica sobre sistemas tipo black-box. La auditabilidad de la decisión es propiedad estructural del producto.

(d) Calibración de razones de verosimilitud por **señal física del documento**, incluyendo posición zonal (encabezado, cuerpo, firma, sello) y estado de rotación del sello (sello rotado tiene LR mayor por baja probabilidad de aparición espuria).

(e) Compuerta de entropía pre-persistencia que **bloquea automáticamente** la persistencia de extracciones contradictorias, forzando revisión humana — ventaja de seguridad técnica.

---

## 6. Reivindicaciones (versión preliminar para abogado)

> **Nota**: las reivindicaciones son el corazón legal de la patente. Estas son borradores; un abogado de PI debe pulirlas para maximizar amplitud y resistencia ante oposiciones.

**Reivindicación 1 (independiente, principal):**

> Un dispositivo appliance embebido para procesamiento neurosimbólico local de documentos jurídicos, **caracterizado** porque comprende:
> 
> (i) una unidad de procesamiento principal con acelerador de inferencia integrado;
> (ii) un módulo de extracción documental por zonas físicas del documento;
> (iii) un módulo de asignación bayesiana documento-expediente con razones de verosimilitud calibradas según señal física, configurado para producir umbrales duales de aceptación y rechazo;
> (iv) un módulo de consolidación en vivo configurado para fusión de expedientes huérfanos y deduplicación documental;
> (v) un módulo de persistencia cognitiva con compuerta de entropía configurada para bloquear automáticamente la persistencia de extracciones con contradicciones internas;
> 
> donde el dispositivo opera en modo offline absoluto sin transmisión del contenido documental a servidores externos, dentro de un único enclosure portable.

**Reivindicación 2 (dependiente):** El dispositivo según la reivindicación 1, donde el módulo de asignación bayesiana genera listas legibles human-readable de razones a favor y en contra de cada asignación.

**Reivindicación 3 (dependiente):** El dispositivo según la reivindicación 1, donde las razones de verosimilitud del módulo de asignación bayesiana son calibradas por la posición zonal del identificador en el documento físico, incluyendo zonas de encabezado, cuerpo, firma y sello.

**Reivindicación 4 (dependiente):** El dispositivo según la reivindicación 3, donde la presencia de un sello rotado o desplazado del eje vertical en el documento incrementa la razón de verosimilitud asignada al identificador correspondiente.

**Reivindicación 5 (dependiente):** El dispositivo según la reivindicación 1, donde la compuerta de entropía utiliza una función de entropía de Shannon sobre el conjunto de extracciones candidatas y bloquea la persistencia cuando dicha entropía supera un umbral predefinido.

**Reivindicación 6 (dependiente):** El dispositivo según la reivindicación 1, integrado en una carcasa cerrada con dimensiones máximas 150×150×60mm y consumo eléctrico promedio inferior a 25W.

**Reivindicación 7 (dependiente):** El dispositivo según la reivindicación 1, que adicionalmente comprende un módulo de validación de licencia conectado a un servidor central a través de canal cifrado, sin transmisión de contenido documental.

---

## 7. Dibujos a anexar

1. **Diagrama de bloques** del dispositivo: hardware (UPP, RAM, SSD, red, carcasa) + software (7 capas).
2. **Diagrama de flujo** del pipeline cognitivo de procesamiento documental.
3. **Vista isométrica** del enclosure físico final.
4. **Diagrama de la asignación bayesiana** con flujo de razones a favor/en contra.

[A producir con CAD y herramientas de diagramación. Costo: ~$300-500 USD si se contrata diseñador técnico.]

---

## 8. Resumen (hasta 200 palabras)

> *"Un dispositivo appliance embebido para procesamiento neurosimbólico local de documentos jurídicos, particularmente tutelas del ordenamiento legal colombiano. El dispositivo integra hardware de cómputo edge con acelerador de inferencia y un pipeline cognitivo de siete capas secuenciales (percepción física, tipología, identificadores canónicos, grafo de actores, línea de tiempo procesal, asignación bayesiana y persistencia con compuerta de entropía), todo dentro de un enclosure portable. La asignación bayesiana documento-expediente utiliza razones de verosimilitud calibradas por señal física del documento, incluyendo posición zonal y estado de rotación del sello, y produce listas legibles human-readable de razones a favor y en contra de cada decisión. El dispositivo opera en modo offline absoluto, garantizando cumplimiento de la Ley 1581 de 2012 sin auditoría compleja del tránsito de datos personales sensibles. La compuerta de entropía bloquea automáticamente la persistencia de extracciones contradictorias forzando revisión humana, lo que constituye una ventaja técnica de seguridad estructural sobre sistemas de inteligencia artificial tipo black-box."*

---

## 9. Tasas a pagar (SIC 2026)

| Concepto | Tasa plena | Mipyme (-25%) |
|----------|------------|----------------|
| Solicitud de modelo de utilidad | $1.020.000 | $765.000 |
| Examen de patentabilidad | $480.000 | $360.000 |
| **Total** | **$1.500.000** | **$1.125.000** |

Anualidades posteriores: ~$120.000 COP/año durante los 10 años de vigencia.

---

## 10. Vía alternativa: Patente de Invención

Si el examinador SIC determina que IURIS es realmente una invención de procedimiento (más que un producto físico), debe redirigirse a **patente de invención**. Diferencias clave:

| | Modelo de Utilidad | Patente de Invención |
|---|---|---|
| Plazo | 10 años | 20 años |
| Examen de altura inventiva | NO requerido | Requerido (más exigente) |
| Tasas totales aprox. | $1.5M COP | $3-5M COP |
| Tiempo concesión | 12-24 meses | 24-48 meses |
| Protege procedimientos | NO | SÍ |
| Protege productos | SÍ | SÍ |

**Recomendación**: presentar primero como modelo de utilidad. Si SIC requiere reformular como patente de invención, hacerlo en respuesta al requerimiento (la fecha de prioridad se preserva).

---

## 11. Próximos pasos operativos

1. **Búsqueda de antecedentes** en bases internacionales (USPTO, EPO, WIPO PATENTSCOPE) para confirmar novedad mundial. Costo: ~$300-500 USD si se contrata firma de PI; gratis si se hace manualmente.
2. **Contratar abogado de PI** especializado en software/hardware para Colombia. Honorarios estimados: $3-5M COP one-time.
3. **Producir dibujos técnicos** (CAD del enclosure + diagramas de bloques).
4. **Radicar solicitud SIC** una vez disponible el RUES Mipyme y los dibujos.
5. **Acompañar el examen** durante 12-24 meses.

---

## Fuentes
- [SIC — Patente de Modelo de Utilidad](https://www.sic.gov.co/patente-de-modelo-de-utilidad)
- [SIC — Documentos para la solicitud de patentes de modelo de utilidad](https://www.sic.gov.co/node/39)
- [SIC — Antes de solicitar una patente de modelo de utilidad](https://www.sic.gov.co/patente-de-modelo-de-utilidad/antes-de-solicitar)
- [Decisión 486/2000 CAN — Régimen Común sobre Propiedad Industrial](http://www.comunidadandina.org/Normativa.aspx)
