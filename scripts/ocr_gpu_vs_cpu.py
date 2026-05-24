#!/usr/bin/env python3
"""Benchmark DEFINITIVO en tu hardware: RapidOCR (backend OpenVINO) en CPU vs
iGPU (Iris Xe). RapidOCR hardcodea device='CPU' en openvino/main.py:59 →
monkeypatch de openvino.Core.compile_model para forzar GPU cuando --device gpu.

Single-instance (la iGPU es un solo dispositivo compartido). Warmup explícito
porque la 1ra inferencia en GPU incluye compilación de kernels. DRY-RUN.

Uso: venv/bin/python scripts/ocr_gpu_vs_cpu.py --device gpu --pages 30
     venv/bin/python scripts/ocr_gpu_vs_cpu.py --device cpu --pages 30
"""
import os, sys, time, argparse, sqlite3
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

ap = argparse.ArgumentParser()
ap.add_argument("--device", choices=["cpu", "gpu"], default="gpu")
ap.add_argument("--pages", type=int, default=30)
ap.add_argument("--warmup", type=int, default=3)
args = ap.parse_args()

# Monkeypatch: forzar device en compile_model si pedimos GPU.
import openvino
_orig_compile = openvino.Core.compile_model
_DEV = "GPU" if args.device == "gpu" else "CPU"
def _patched_compile(self, model, device_name="CPU", *a, **k):
    return _orig_compile(self, model, _DEV, *a, **k)
openvino.Core.compile_model = _patched_compile

import fitz, numpy as np
from rapidocr import RapidOCR, EngineType, LangRec

print(f"[{args.device.upper()}] cargando RapidOCR (OpenVINO)...", flush=True)
t0 = time.time()
ocr = RapidOCR(params={
    "Det.engine_type": EngineType.OPENVINO,
    "Rec.engine_type": EngineType.OPENVINO,
    "Cls.engine_type": EngineType.OPENVINO,
    "Rec.lang_type": LangRec.LATIN,
    "Global.use_cls": False,
})
print(f"  init: {time.time()-t0:.1f}s (incluye compilación de kernels si GPU)", flush=True)

# Reunir páginas de PDFs escaneados reales
DB = os.path.join(os.path.dirname(__file__), "..", "data", "tutelas.db")
con = sqlite3.connect(DB); con.row_factory = sqlite3.Row
rows = con.execute("""select file_path from documents
   where lower(file_path) like '%.pdf' order by id desc limit 60""").fetchall()
imgs = []
for r in rows:
    if len(imgs) >= args.pages + args.warmup:
        break
    p = r["file_path"]
    if not p or not os.path.exists(p):
        continue
    try:
        d = fitz.open(p)
        for pg in d:
            pix = pg.get_pixmap(dpi=200)
            im = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
            if pix.n == 4: im = im[:, :, :3]
            elif pix.n == 1: im = np.repeat(im, 3, axis=2)
            imgs.append(im)
            if len(imgs) >= args.pages + args.warmup:
                break
        d.close()
    except Exception:
        continue
con.close()

# Warmup (no medir: la GPU compila kernels en la 1ra)
for im in imgs[:args.warmup]:
    ocr(im)
bench = imgs[args.warmup:args.warmup + args.pages]
print(f"  warmup {args.warmup} págs hecho · midiendo {len(bench)} págs...", flush=True)

t1 = time.time()
chars = 0
for im in bench:
    res = ocr(im)
    chars += len(" ".join(res.txts or [])) if res and res.txts else 0
dt = time.time() - t1
print(f"\n=== [{args.device.upper()}] {len(bench)} págs · {dt:.1f}s · "
      f"{len(bench)/dt:.3f} págs/s · {dt/len(bench):.2f}s/pág · {chars} chars ===", flush=True)
