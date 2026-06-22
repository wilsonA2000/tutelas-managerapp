"""Mapa de consumidores = gate de código muerto (Fase 0 de la de-sobreingeniería).

Operacionaliza "verificar antes de borrar". Reporta, con evidencia:
  - backend: módulos .py importados por NADIE (candidatos a muerto)
  - frontend: exports de services/api.ts consumidos por NINGÚN componente/página

Es grep-based (no AST), conservador: si hay CUALQUIER referencia textual al símbolo /
módulo fuera de su definición, NO lo marca muerto. Pensado para correr en
run_safety_net.sh y antes de cualquier borrado.

Uso:
  python3 scripts/consumer_map.py backend         # módulos backend sin importador
  python3 scripts/consumer_map.py api             # exports api.ts sin consumidor
  python3 scripts/consumer_map.py check SYMBOLS    # ¿estos símbolos/módulos se usan?
"""
import os, re, sys, subprocess

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _grep_count(pattern: str, path: str, exclude_file: str | None = None) -> list[str]:
    """Devuelve líneas 'file:line:txt' que matchean, excluyendo exclude_file."""
    try:
        out = subprocess.run(
            ["grep", "-rnE", pattern, path, "--include=*.py", "--include=*.ts", "--include=*.tsx"],
            capture_output=True, text=True, cwd=ROOT,
        ).stdout.splitlines()
    except Exception:
        out = []
    if exclude_file:
        out = [l for l in out if not l.startswith(exclude_file)]
    return out


def cmd_backend():
    """Lista módulos backend/**/*.py que ningún otro .py importa."""
    mods = []
    for dp, _, fs in os.walk(os.path.join(ROOT, "backend")):
        for fn in fs:
            if fn.endswith(".py") and fn != "__init__.py":
                full = os.path.join(dp, fn)
                rel = os.path.relpath(full, ROOT)
                mod = rel[:-3].replace("/", ".")          # backend.x.y
                modname = fn[:-3]                            # y
                mods.append((rel, mod, modname))
    dead = []
    for rel, mod, modname in sorted(mods):
        # importadores: 'from backend.x.y import' o 'import backend.x.y' o 'from .y import' o 'from ..x.y'
        pat = rf"(from {re.escape(mod)} import|import {re.escape(mod)}\b|from [.]+[\w.]* import [^#]*\b{re.escape(modname)}\b|from [.]+{re.escape(modname)} import)"
        hits = _grep_count(pat, "backend", exclude_file=rel)
        if not hits:
            dead.append(rel)
    print(f"=== Módulos backend sin importador detectado: {len(dead)} ===")
    print("(VERIFICAR manualmente — entrypoints, routers montados por string, y cron")
    print(" pueden no aparecer; este gate es una SEÑAL, no una sentencia)\n")
    for d in dead:
        print(f"  {d}")
    return dead


def cmd_api():
    """Lista exports de api.ts sin consumidor en pages/components."""
    api = os.path.join("frontend", "src", "services", "api.ts")
    full = os.path.join(ROOT, api)
    if not os.path.exists(full):
        print("no existe api.ts"); return []
    names = re.findall(r"export const (\w+)\s*=", open(full, encoding="utf-8").read())
    dead = []
    for n in sorted(set(names)):
        hits = _grep_count(rf"\b{re.escape(n)}\b", "frontend/src", exclude_file=api)
        if not hits:
            dead.append(n)
    print(f"=== Exports api.ts sin consumidor: {len(dead)} de {len(set(names))} ===\n")
    for d in dead:
        print(f"  {d}")
    return dead


def cmd_check(symbols: list[str]):
    """Para cada símbolo/módulo, muestra consumidores (para decidir borrado)."""
    for s in symbols:
        hits = _grep_count(rf"\b{re.escape(s)}\b", "backend", None) + \
               _grep_count(rf"\b{re.escape(s)}\b", "frontend/src", None)
        # quitar auto-definición (líneas con 'def s'/'class s'/'export const s'/'const s =')
        consumers = [h for h in hits if not re.search(
            rf"(def|class|export const|const) {re.escape(s)}\b", h)]
        print(f"\n### {s}: {len(consumers)} consumidor(es)")
        for c in consumers[:15]:
            print(f"  {c[:160]}")


def main():
    if len(sys.argv) < 2:
        print(__doc__); sys.exit(1)
    cmd = sys.argv[1]
    if cmd == "backend":
        cmd_backend()
    elif cmd == "api":
        cmd_api()
    elif cmd == "check":
        cmd_check(sys.argv[2].split(",") if len(sys.argv) > 2 else [])
    else:
        print(__doc__); sys.exit(1)


if __name__ == "__main__":
    main()
