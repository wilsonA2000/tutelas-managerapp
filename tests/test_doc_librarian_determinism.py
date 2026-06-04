"""Blinda el fix de determinismo de `doc_librarian.classify` (2026-06-03).

Bug: el ganador `max(combined, key=combined.get)` se calculaba sobre un dict derivado de
un `set`, cuyo orden depende de PYTHONHASHSEED → en EMPATES el mismo documento podía
clasificarse distinto en dos procesos (visto en el backfill: doc 3654 SENTENCIA_1RA vs
OFICIO_CUMPLIMIENTO). Fix: `max(sorted(combined, key=lambda d: d.value), key=...)`.

Este test corre la clasificación en subprocesos con PYTHONHASHSEED distinto y exige
resultados idénticos.
"""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Documentos representativos (filename + texto) para clasificar bajo distintos seeds.
_DOCS = [
    ("EscritoTutela.pdf", "SENOR JUEZ. ACCIONANTE: Maria. interpongo la presente accion de tutela. PRETENSIONES: tutelar."),
    ("Sentencia2da.pdf", "SENTENCIA SEGUNDA INSTANCIA. CONFIRMA el fallo. RESUELVE: PRIMERO confirmar."),
    ("AutoAdmite.pdf", "AUTO. ADMITASE la accion de tutela. AVOCAR CONOCIMIENTO. RESUELVE avocar."),
    ("RespuestaSED.pdf", "RESPUESTA. La Secretaria de Educacion contesta la accion de tutela radicada."),
    ("Seguimiento_cumplimiento_sentencia.pdf", "Oficio de seguimiento al cumplimiento de la sentencia de tutela proferida."),
]

_RUNNER = (
    "import sys; sys.path.insert(0, %r);"
    "from backend.v9.doc_io import DocText;"
    "from backend.v9.doc_librarian import classify;"
    "docs=%r;"
    "print('|'.join(classify(DocText(path='x',filename=f,text=t,method='pymupdf')).doc_type.value for f,t in docs))"
) % (str(ROOT), _DOCS)


def _classify_with_seed(seed: str) -> str:
    env = {"PYTHONHASHSEED": seed, "PATH": "/usr/bin:/bin"}
    out = subprocess.run([sys.executable, "-c", _RUNNER], capture_output=True, text=True, env=env, cwd=str(ROOT))
    assert out.returncode == 0, out.stderr
    return out.stdout.strip()


def test_clasificacion_estable_entre_hashseeds():
    r0 = _classify_with_seed("0")
    r1 = _classify_with_seed("12345")
    r2 = _classify_with_seed("99999")
    assert r0 == r1 == r2, f"clasificación no determinista entre PYTHONHASHSEED: {r0!r} / {r1!r} / {r2!r}"
    assert r0.count("|") == len(_DOCS) - 1  # produjo un tipo por doc
