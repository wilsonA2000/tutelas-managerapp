"""Pipeline v9 — extracción plana, determinística, una sola autoridad por campo.

Reemplaza los 3 pipelines paralelos de v5.5/v6/v8 (3155 LOC) por una pasada
lineal de 5 etapas:

    doc_io  →  regex_pass  →  catalog_resolve  →  excel_reconcile  →  llm_gap_fill  →  persist

Reglas de oro:

1. **Una autoridad por campo**. Cada campo del cuadro Excel tiene exactamente
   un módulo que puede escribirlo en cada etapa, y el orden es estricto:
   regex < catálogo < excel < llm. La etapa posterior solo escribe si la
   anterior dejó el campo vacío.

2. **LLM es último recurso**. Si regex+catálogo+excel resuelven el campo, el
   LLM nunca se invoca. En el peor caso se hace UNA pasada multi-campo, no
   varias seriales como en v8.

3. **Sin escrituras cruzadas**. Ningún módulo modifica un campo que ya tiene
   valor. El `persist` registra `source` por campo en `field_sources_json`
   para que la auditoría sea trivial.

4. **Sin contradicciones por construcción**. Si un campo aparece vacío al
   final, está vacío. No hay "fallback que pisa al primary".

Salida: el dict `ExtractedFields` con las 28 columnas del cuadro Excel
(`frontend/src/pages/Cuadro.tsx`). Persistencia opcional en `Case` ORM.
"""

from backend.v9.types import ExtractedFields, FieldSource, ExtractionResult

__all__ = ["ExtractedFields", "FieldSource", "ExtractionResult"]
