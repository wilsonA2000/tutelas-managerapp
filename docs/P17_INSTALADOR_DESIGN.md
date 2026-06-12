# P17 — Diseño del instalador del appliance (fase producto)

> Estado: DISEÑO (2026-06-11). Pendiente de aprobación de Wilson antes de implementar.
> Objetivo: que un despacho jurídico instale "Tutelas Manager" en una máquina Linux
> sin internet confiable y sin conocimientos técnicos, en < 30 minutos.

## 1. Qué se vende

Un **appliance local-first**: la plataforma corre 100% en la máquina del despacho
(LOCAL_ONLY — los datos nunca salen). Componentes:

| Componente | Hoy (dev) | En el producto |
|---|---|---|
| Backend FastAPI | venv 7.6 GB + uvicorn --reload | venv **adelgazado (~2.5 GB)** + systemd, sin reload |
| Frontend React | `npm run dev` (node_modules 410 MB) | **`dist/` estático pre-compilado** servido por FastAPI — el cliente NO necesita Node |
| LLM local | llama.cpp compilado a mano (37 MB) | binarios pre-compilados **Vulkan + CPU fallback** incluidos |
| Modelo | 5 GGUF (25 GB en lora-models) | **solo Qwen3-4B-Instruct-2507-Q4_K_M (2.5 GB)** |
| OCR | PaddleOCR + tesseract + marker | PaddleOCR + tesseract; **marker-pdf opcional** (arrastra torch/CUDA) |
| DB | tutelas.db de producción | **DB virgen** creada por `alembic upgrade head` |
| Gmail | OAuth proyecto de Wilson | **opcional** — wizard post-instalación; sin Gmail funciona con carga manual |

### Tamaño objetivo del bundle

| Pieza | Tamaño |
|---|---|
| Wheels Python (CPU-only, sin nvidia/triton) | ~1.8 GB |
| GGUF Qwen3-4B-Instruct-2507 | 2.5 GB |
| es_core_news_lg (spaCy) | 0.6 GB |
| llama.cpp binarios (vulkan + cpu) | ~80 MB |
| frontend dist + backend código | ~50 MB |
| **Total .tar.gz** | **~5 GB** (vs 33 GB del dev actual) |

**Decisión clave de slimming**: instalar `torch` CPU-only (`--index-url
https://download.pytorch.org/whl/cpu`) recorta 4.6 GB de nvidia/triton que el
appliance jamás usa (la iGPU se usa vía Vulkan en llama.cpp, no vía CUDA).
`sentence-transformers`/`faiss` (similitud BGE-M3) funcionan igual en CPU.
`marker-pdf` pasa a extra opcional `[ocr-avanzado]` — PaddleOCR cubre el 95%.

## 2. Estructura del bundle

```
tutelas-appliance-1.0.0/
├── install.sh                  # instalador interactivo (único punto de entrada)
├── VERSION
├── LICENSE.txt                 # licencia comercial (ver §5)
├── app/                        # código (backend/ frontend-dist/ scripts/ alembic/)
├── wheels/                     # pip wheels offline (--no-index --find-links)
├── models/
│   ├── Qwen3-4B-Instruct-2507-Q4_K_M.gguf
│   └── es_core_news_lg-3.x.whl
├── bin/
│   ├── llama-server-vulkan     # build genérico x86-64 + Vulkan
│   └── llama-server-cpu        # fallback AVX2
├── config/
│   ├── env.template            # .env con defaults de producto (LOCAL_ONLY=true)
│   └── tutelas.service         # unidad systemd (user service)
└── docs/
    ├── MANUAL_DESPACHO.pdf     # manual del abogado (ver §7)
    └── INSTALACION.md
```

## 3. `install.sh` — fases

1. **Pre-flight**: Ubuntu 22.04+/Debian 12+, x86-64 AVX2, ≥16 GB RAM, ≥20 GB disco,
   Python 3.11+, `apt install` de deps de sistema (tesseract-ocr-spa, poppler-utils,
   libvulkan1, fuser). Si no hay sudo: lista lo que falta y aborta con instrucción.
2. **Venv offline**: `python3 -m venv` + `pip install --no-index --find-links wheels/ -r requirements-product.txt`.
3. **Binarios LLM**: prueba `vulkaninfo`; instala `llama-server-vulkan` si hay GPU
   compatible, si no el CPU. Smoke: carga el GGUF y pide 5 tokens.
4. **DB virgen**: `alembic upgrade head` + `create_default_user()` con contraseña
   **generada aleatoria** impresa al final (no más `wilson/tutelas2026` hardcoded).
5. **Config**: wizard de 4 preguntas → genera `.env` (nombre del despacho, puerto,
   carpeta de expedientes `BASE_DIR`, ¿activar LLM local?). JWT_SECRET aleatorio.
6. **Servicio**: instala `tutelas.service` (systemd --user), habilita arranque
   automático. `start.sh` queda como modo manual/debug.
7. **Verificación**: `curl /api/health/appliance` → todo `ok` o reporte de qué falló.

Idempotente: re-ejecutar repara (no duplica usuarios ni pisa `.env` existente sin
preguntar).

## 4. Cambios de código necesarios (pre-requisitos del instalador)

| # | Cambio | Por qué |
|---|---|---|
| C1 | FastAPI sirve `frontend/dist` como estáticos (`StaticFiles` + catch-all SPA) | eliminar Node del runtime del cliente |
| C2 | `requirements-product.txt` (CPU-only, sin presidio si LOCAL_ONLY, sin marker) | slimming 7.6→2.5 GB |
| C3 | Contraseña admin aleatoria en `create_default_user` cuando `PRODUCT_MODE=true` | seguridad de producto |
| C4 | Página de **gestión de usuarios** (admin crea/desactiva, roles admin/abogado/lectura) — backend ya tiene tabla `users`+roles | multiusuario vendible |
| C5 | `JWT_SECRET` persistente: hoy si está vacío se regenera **en cada arranque** (`auth/service.py:15`) → todas las sesiones mueren al reiniciar. El instalador lo genera una vez y lo escribe al `.env` | una instalación = un secreto estable |
| C6 | Paths portables: `backend/` ya está limpio (verificado 2026-06-11); los paths de Wilson viven solo en `scripts/` one-shot que NO van al bundle. Falta: path del llama-server (`~/llama.cpp/...`) configurable vía `.env` | portabilidad |
| C7 | Endpoint `/api/license/status` + chequeo de licencia al boot (ver §5) | licenciamiento |
| C8 | Build reproducible: `make bundle` (script que arma el .tar.gz desde CI/local) | releases |

## 5. Licenciamiento (propuesta — decidir con Wilson)

- **Modelo simple offline-friendly**: archivo `license.key` firmado (Ed25519) con
  {despacho, NIT, fecha_expiración, nº usuarios}. El backend valida firma al boot
  y muestra banner si expiró (modo lectura tras vencer, nunca bloqueo destructivo).
- Sin "phone home" — coherente con la promesa LOCAL_ONLY.
- Herramienta privada `gen_license.py` (NO va en el bundle) con la clave privada.
- Nota: el stack es open-source (FastAPI/React/llama.cpp MIT/Apache; Qwen
  Apache 2.0) — vendible sin problema; incluir `THIRD_PARTY_LICENSES.txt`.

## 6. Multiusuario (alcance v1)

- Ya existe: tabla `users` (id/username/role/password_hash), JWT, `require_auth`.
- Falta: UI de administración (C4), roles efectivos (hoy todo usuario autenticado
  puede todo — añadir guard `require_role("admin")` en endpoints destructivos:
  cleanup, merge, delete, settings), y auditoría por usuario (audit_log ya existe,
  verificar que registre `username` del token).
- Fuera de alcance v1: SSO/LDAP, multi-tenancy (1 instalación = 1 despacho).

## 7. Manual del despacho

Base: `GUIA_USUARIO.md` existente. Reestructurar a: (1) instalación express,
(2) primer día — crear usuarios, conectar Gmail (opcional), importar expedientes,
(3) operación diaria — ingesta, cuadro, extracción, alertas de plazos,
(4) emergencias — backup/restore, health check, soporte. Exportar a PDF
(pandoc) dentro del bundle.

## 8. Plan de implementación (orden propuesto)

1. **C2 + C6** — requirements-product + auditoría de paths (medio día, desbloquea todo)
2. **C1** — servir dist estático + `npm run build` verificado (medio día)
3. **C3 + C5** — endurecimiento credenciales (rápido)
4. **`make bundle` + `install.sh`** — el corazón (1-2 días, probar en VM limpia)
5. **C4** — UI usuarios + roles (1 día)
6. **C7 + §5** — licencias (1 día)
7. **Manual + PDF** (medio día)
8. **Prueba de fuego**: instalación completa en una VM Ubuntu 22.04 virgen sin
   internet, con cronómetro — criterio de éxito < 30 min y health all-green.

## 9. Riesgos conocidos

- **Vulkan/iGPU**: el GPU hang del batch (memoria `project_vulkan_gpu_hang_fix`)
  obliga a default conservador: LLM en CPU salvo opt-in, una carga pesada a la vez.
- **PaddlePaddle** es la wheel más frágil (ABI/numpy); fijar versión exacta probada.
- **DrvFs/WSL**: si el cliente instala en WSL sobre /mnt/c, SQLite sufre "disk I/O
  error" — el pre-flight debe detectarlo y negarse o forzar disco nativo.
- **Gmail OAuth**: cada despacho necesita su propio proyecto Google Cloud o
  un proyecto multi-cliente verificado por Google — para v1, documentar el
  procedimiento manual (como `docs/OAUTH_GMAIL_PRODUCTION.md`) y dejarlo opcional.
