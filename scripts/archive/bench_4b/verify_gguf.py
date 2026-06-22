#!/usr/bin/env python3
"""Verifica la IDENTIDAD REAL de un GGUF leyendo su metadata (no el nombre del archivo).
Uso: venv/bin/python scripts/bench/verify_gguf.py <a.gguf> <b.gguf> ..."""
import sys
from gguf import GGUFReader

WANT = ("general.architecture", "general.name", "general.size_label", "general.basename",
        "block_count", "embedding_length", "expert_count", "expert_used_count",
        "context_length", "vocab_size", "general.quantization")


def field_val(f):
    for attr in ("contents",):
        if hasattr(f, attr):
            try:
                return f.contents()
            except Exception:
                pass
    try:
        return bytes(f.parts[f.data[-1]]).decode("utf-8", "replace")
    except Exception:
        try:
            return f.parts[f.data[-1]].tolist()
        except Exception:
            return "?"


for path in sys.argv[1:]:
    name = path.split("/")[-1]
    print(f"\n### {name}")
    try:
        r = GGUFReader(path)
    except Exception as e:  # noqa: BLE001
        print(f"  ⚠ no se pudo leer (¿parcial/corrupto?): {e}")
        continue
    for k, f in r.fields.items():
        if any(w in k for w in WANT):
            print(f"  {k:32} = {field_val(f)}")
