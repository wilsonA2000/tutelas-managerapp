# Tutelas Manager gobernaciones

Plataforma de gestión, auditoría y seguimiento de acciones de tutela
de la Secretaría de Educación Departamental.

**Versión actual: v8.2 — Producción local** (Mayo 2026)

---

## Estado del sistema

| Métrica | Valor |
|---|---|
| Cases activos | 216 (205 TUTELA · 6 INCIDENTE_HUERFANO · 5 AMBIGUO) |
| Pureza tipológica | 94.9% TUTELA |
| Cobertura abogado canónico | 83.8% |
| Cobertura dependencia canónica | 63.9% |
| Emails ingestados | 1380 |
| Documentos | 4031 |
| Actuaciones administrativas (Excel) | 4141 |
| Compliance tracking (fallos) | 118 |
| Cases en Corte Constitucional | 9 |
| Directorio de contactos | 17 |
| Estado semáforo | 91 ROJO · 32 AMARILLO · 93 VERDE |

---

## Arquitectura general

```
┌────────────────────────┐    ┌────────────────────────┐
│  Frontend (React+Vite) │    │  Backend (FastAPI)     │
│  http://localhost:5174 │←──→│  http://localhost:8000 │
└────────────────────────┘    └───────────┬────────────┘
                                          ↓
                          ┌────────────────────────────┐
                          │  Pipeline cognitivo v6+    │
                          │  - Visual analyzer (PDFs)  │
                          │  - Bayesian assignment     │
                          │  - Procedural timeline     │
                          │  - Case classifier         │
                          │  - Compliance tracking     │
                          │  - EarlyWarning (10 reglas)│
                          └────────────────────────────┘
                                          ↓
                          ┌────────────────────────────┐
                          │  SQLite (data/tutelas.db)  │
                          │  150 MB local              │
                          └────────────────────────────┘
                                          ↑
                          ┌────────────────────────────┐
                          │  LLM Qwen3-4B + LoRA iuris │
                          │  127.0.0.1:8765 (local)    │
                          │  TF-IDF index (4584 docs)  │
                          └────────────────────────────┘
```

---

## Capas funcionales

### 1. Ingesta — Gmail monitor
- API REST OAuth2 con `tutelas@santander.gov.co`
- Matching emails ↔ cases por radicado_23/CC/FOREST/rad_corto
- Threading RFC 5322 + matcher multi-criterio (6 señales, score 0-160)

### 2. Pipeline cognitivo v6 (7 capas)
0. Percepción física — visual signature
1. Tipología documental
2. Identificadores canónicos (rad23/forest/cédula)
3. Actor graph + correferencia
4. Timeline procesal + classifier (TUTELA/HUERFANO/AMBIGUO)
5. Bayesian assignment per-doc (R10/R11/R12)
6. Live consolidator (fusión de duplicados)
7. Persist con entropy gate

### 3. Capas v8.2 (esta versión)
- **Catálogo canónico de abogados** — 17 oficiales con aliases (resuelve typos
  y variantes) — `backend/data/abogados_canonicos.json`
- **Catálogo canónico de dependencias** — mapeo Excel ↔ SED_ORG L1/L2/L3 —
  `backend/data/dependencias_resolver.py`
- **Importador del cuadro CONTROL TUTELAS .xlsx** — reconciliación dual-track
  con detección de disensos — `backend/services/control_tutelas_importer.py`
- **Bitácora de actuaciones** — `case_actuaciones` preserva todas las filas
  del Excel (4141) sin sobrescribir extracción
- **Auditoría integral de fallos** — endpoint y página `/auditoria` con vistas
  por etapa procesal, abogado y dependencia
- **Tabla `corte_revision`** + **`directorio_correos`** importadas del Excel
- **EarlyWarning con 10 reglas** — agrega R8 (plazo cumplimiento), R9 (apercibimiento
  en sentencia), R10 (drift de asignación)
- **Chat IA híbrido** Tier 1 (templates determinísticos) + Tier 2 (LLM Qwen 4B local)

### 4. Frontend (React + Tailwind + shadcn/ui)
Páginas principales:
- `/` Dashboard ejecutivo
- `/cases` Lista de tutelas
- `/cases/{id}` Detalle de caso (con campos canónicos + raw)
- `/auditoria` Auditoría integral por etapa/abogado/dependencia
- `/seguimiento` Compliance de fallos (semáforo plazos)
- `/alertas` EarlyWarning ROJO/AMARILLO
- `/ejecutivo` KPIs gobernador
- `/cuadro` Cuadro Excel exportable
- `/intelligence` Búsquedas y análisis
- `/correos` Gmail integrado
- `/reportes` Reportes y exportes

### 5. Asistente jurídico (Chat IA)
Sidebar lateral con 18 templates Tier 1 (instantáneos) + Qwen 4B (preguntas abiertas).

Ejemplos:
- Estadísticas: `cuántos casos rojos`, `casos por abogado`, `distribución de fallos`
- Por persona: `qué tiene Angelica`, `casos urgentes de Victor`
- Por área: `casos de talento humano`, `casos de financiera`
- Conceptual: `explica el grado de consulta`, `diferencia incidente vs sanción`
- Análisis: `casos parecidos al 142`, `recomendación protocolo sanción`

---

## Despliegue local

### Requisitos
- Linux/WSL2, Python 3.10+, Node 18+
- 8 GB RAM mínimo (Qwen 4B + backend + frontend)
- 8 cores CPU (sin GPU funciona, lento; con GPU recomendado)

### Setup primera vez
```bash
# Backend
cd tutelas-app
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt

# Frontend
cd frontend && npm install
cd ..

# DB (si está vacía, run init)
python3 -c "from backend.database.database import init_db; init_db()"

# Construir índice TF-IDF (1 segundo, 1.9 MB)
python3 -m backend.ml.embeddings.tfidf_index --rebuild
```

### Arranque diario
```bash
cd tutelas-app
bash start.sh   # arranca backend + frontend
```

### LLM local (opcional)
```bash
# Solo si tienes el modelo descargado en data/lora-models/
~/llama.cpp/build/bin/llama-server \
  -m data/lora-models/Qwen3-4B-Q4_K_M.gguf \
  --lora data/lora-models/iuris-lora-qwen3-4b.gguf \
  --port 8765 --ctx-size 4096 -t 6 --host 127.0.0.1
```

Sin LLM: el chat funciona via Tier 1 (cubre 18 preguntas operativas).

### Login
Usuario: `wilson` · Contraseña: `tutelas2026`

---

## Privacidad y seguridad

- ✅ **Datos locales únicamente** — DB, emails, docs en disco propio
- ✅ **LLM local** — Qwen 4B en `127.0.0.1` (sin Internet)
- ✅ **Sin telemetría** ni tracking externo
- ✅ **`.gitignore` protege** DB, datasets, modelos, backups, credenciales
- ✅ **PII selective/aggressive** modo en cada case (anonimización pre-IA externa
  cuando se usa Claude Haiku como fallback de DeepSeek)

---

## Documentación

| Archivo | Para qué |
|---|---|
| `AGENTE_JURIDICO_IA.md` | Detalle del agente Qwen + tools |
| `GUIA_USUARIO.md` | Manual operativo del abogado |
| `BENCHMARK_PIPELINE_VS_AGENT.md` | Comparativa de pipelines |
| `docs/V8_FIXES_SESSION.md` | Cambios de la sesión v8 |
| `docs/iuris/` | LoRA training y dataset |
| `CLAUDE.md` | Instrucciones del proyecto para Claude |

---

## Comandos rápidos

```bash
# Tests del classifier + cognitive
python3 -m pytest tests/test_timeline_classifier_v6.py tests/cognition/ -v

# Validador heurístico masivo (firmante↔accionante, mezcla rad)
curl -X POST http://localhost:8000/api/cleanup/validate-all

# Auditoría dashboard (91 ROJO, etc.)
curl http://localhost:8000/api/auditoria/dashboard

# Importar cuadro CONTROL TUTELAS de la oficina
curl -X POST http://localhost:8000/api/import/control-tutelas-from-path \
  -H 'Content-Type: application/json' \
  -d '{"path": "/ruta/CONTROL TUTELAS.xlsx"}'

# Reconstruir índice de búsqueda semántica
python3 -m backend.ml.embeddings.tfidf_index --rebuild

# E2E Playwright (requiere frontend en :5174)
cd frontend && node ../scripts/e2e_auditoria.mjs
```

---

## Versión actual y roadmap

**v8.2** (actual) — Production-ready local
- Catálogos canónicos abogados/dependencias
- Importador Excel con reconciliación
- Auditoría integral
- LLM Qwen 4B + TF-IDF index
- Chat IA híbrido Tier 1+2

**Pendiente / mejora**:
- BGE-M3 para búsqueda semántica más precisa (requiere GPU)
- Reentrenar LoRA con dataset balanceado para chat conversacional
- Vista Corte Constitucional dedicada en frontend
- Notificaciones push para vencimientos críticos

---

Wilson Andrés Argüello Castellanos · Ingeniero Legal · SED Santander
