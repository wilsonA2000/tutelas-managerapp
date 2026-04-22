"""Auto-catálogo de variantes textuales por campo (v5.3.2 roadmap).

Analiza los casos COMPLETO de la DB y cataloga:
- Variantes de formato de accionante (persona natural, institucional, agente oficioso).
- Estructura de accionados (singular, múltiple, mixto).
- Verbos de acción en pretensiones ("solicita", "pide", "pretende", "ordenar").
- Keywords de decisión por juzgado.

Objetivo: identificar los 5-10 patrones dominantes de cada campo para
codificar reglas nuevas en backend/cognition/ y subir cobertura de 80%→95%.
"""

import sys
import re
from pathlib import Path
from collections import Counter, defaultdict

APP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP))

from backend.database.database import SessionLocal
from backend.database.models import Case, Document


TOP_K = 8


def _starters(text: str, n_words: int = 3) -> str:
    words = text.split()[:n_words]
    return " ".join(words).upper()


def catalog_accionantes(cases):
    formats = Counter()
    starters = Counter()
    lengths = Counter()
    for c in cases:
        if not c.accionante:
            continue
        acc = c.accionante.strip()
        # Detectar formato
        if "PERSONERO" in acc.upper() or "PERSONER" in acc.upper():
            formats["PERSONERO_MUNICIPAL"] += 1
        elif re.search(r"\bOTROS\b", acc, re.IGNORECASE):
            formats["MULTIPLE_Y_OTROS"] += 1
        elif re.search(r"agente\s+oficios[oa]", acc, re.IGNORECASE):
            formats["AGENTE_OFICIOSO"] += 1
        elif re.search(r"representa", acc, re.IGNORECASE):
            formats["REPRESENTACION"] += 1
        else:
            formats["PERSONA_NATURAL"] += 1
        starters[_starters(acc)] += 1
        lengths[len(acc.split())] += 1
    return {"formats": formats, "starters": starters.most_common(TOP_K), "word_lengths": dict(lengths)}


def catalog_accionados(cases):
    entities = Counter()
    count_per_case = Counter()
    for c in cases:
        if not c.accionados:
            continue
        parts = [p.strip() for p in re.split(r"\s*-\s*", c.accionados) if p.strip()]
        count_per_case[len(parts)] += 1
        for p in parts:
            # Normalizar
            p_up = re.sub(r"\s+", " ", p).upper()
            # Abreviar instituciones comunes
            if "SECRETARÍA DE EDUCACIÓN" in p_up or "SECRETARIA DE EDUCACION" in p_up:
                entities["SECRETARIA DE EDUCACION"] += 1
            elif "NUEVA EPS" in p_up:
                entities["NUEVA EPS"] += 1
            elif "GOBERNACIÓN" in p_up or "GOBERNACION" in p_up:
                entities["GOBERNACION SANTANDER"] += 1
            elif "MINISTERIO DE EDUCACIÓN" in p_up or "MINISTERIO DE EDUCACION" in p_up:
                entities["MINISTERIO EDUCACION"] += 1
            elif "ALCALDÍA" in p_up or "ALCALDIA" in p_up:
                entities["ALCALDIA_MUNICIPAL"] += 1
            elif "EPS" in p_up:
                entities["OTRAS_EPS"] += 1
            else:
                # Primeras 4 palabras como key
                key = " ".join(p_up.split()[:4])
                entities[key] += 1
    return {"entities_top": entities.most_common(TOP_K * 2), "count_per_case": dict(count_per_case)}


def catalog_derechos(cases):
    derechos = Counter()
    combos = Counter()
    for c in cases:
        if not c.derecho_vulnerado:
            continue
        parts = [p.strip().upper() for p in re.split(r"\s*-\s*", c.derecho_vulnerado) if p.strip()]
        for p in parts:
            derechos[p] += 1
        if parts:
            combo = " + ".join(parts[:3])
            combos[combo] += 1
    return {"top_derechos": derechos.most_common(TOP_K * 2),
            "top_combos": combos.most_common(TOP_K)}


def catalog_decisiones(cases):
    fallos = Counter()
    segunda = Counter()
    impugnaciones = Counter()
    for c in cases:
        if c.sentido_fallo_1st:
            fallos[c.sentido_fallo_1st.strip().upper()] += 1
        if c.sentido_fallo_2nd:
            segunda[c.sentido_fallo_2nd.strip().upper()] += 1
        if c.impugnacion:
            impugnaciones[c.impugnacion.strip().upper()] += 1
    return {"primera": fallos.most_common(),
            "segunda": segunda.most_common(),
            "impugnacion": impugnaciones.most_common()}


def catalog_asunto_verbs(cases):
    """Primer verbo del campo ASUNTO (patrón de acción)."""
    verbs = Counter()
    for c in cases:
        if not c.asunto:
            continue
        words = c.asunto.strip().split()
        if len(words) >= 2:
            first_two = " ".join(words[:2]).lower()
            verbs[first_two] += 1
    return {"top_starters": verbs.most_common(TOP_K * 2)}


def catalog_juzgados(cases):
    juzgados = Counter()
    for c in cases:
        if not c.juzgado:
            continue
        juz = c.juzgado.strip().upper()
        # Categorizar por jerarquía
        if "PROMISCUO" in juz:
            category = "PROMISCUO_MUNICIPAL"
        elif "MUNICIPAL" in juz:
            category = "PENAL_MUNICIPAL"
        elif "CIRCUITO" in juz:
            category = "CIRCUITO"
        elif "TRIBUNAL" in juz:
            category = "TRIBUNAL"
        elif "CORTE" in juz:
            category = "CORTE"
        else:
            category = "OTRO"
        juzgados[category] += 1
    return juzgados.most_common()


def main():
    db = SessionLocal()
    try:
        cases = (
            db.query(Case)
            .filter(Case.processing_status == "COMPLETO")
            .all()
        )
        print(f"Analizando {len(cases)} casos COMPLETO...\n")

        print("=" * 70)
        print("CATÁLOGO DE ACCIONANTES")
        print("=" * 70)
        acc = catalog_accionantes(cases)
        print("Formatos:")
        for fmt, n in acc["formats"].most_common():
            pct = 100 * n / len(cases)
            print(f"  {fmt:25s} {n:4d} ({pct:5.1f}%)")
        print(f"\nStarters comunes (top {TOP_K}):")
        for s, n in acc["starters"]:
            print(f"  {s:40s} {n}")

        print("\n" + "=" * 70)
        print("CATÁLOGO DE ACCIONADOS")
        print("=" * 70)
        acd = catalog_accionados(cases)
        print("Entidades más comunes:")
        for ent, n in acd["entities_top"]:
            pct = 100 * n / len(cases)
            print(f"  {ent:40s} {n:4d} ({pct:5.1f}%)")
        print(f"\nAccionados por caso (cantidad):")
        for cnt, n in sorted(acd["count_per_case"].items()):
            print(f"  {cnt} accionado(s): {n} casos")

        print("\n" + "=" * 70)
        print("CATÁLOGO DE DERECHOS VULNERADOS")
        print("=" * 70)
        der = catalog_derechos(cases)
        print("Top derechos individuales:")
        for d, n in der["top_derechos"]:
            pct = 100 * n / len(cases)
            print(f"  {d:40s} {n:4d} ({pct:5.1f}%)")
        print(f"\nCombos más frecuentes:")
        for c, n in der["top_combos"]:
            print(f"  {n:3d}× {c}")

        print("\n" + "=" * 70)
        print("CATÁLOGO DE DECISIONES")
        print("=" * 70)
        dec = catalog_decisiones(cases)
        print("Primera instancia:")
        for s, n in dec["primera"]:
            print(f"  {s:25s} {n}")
        print("Segunda instancia:")
        for s, n in dec["segunda"]:
            print(f"  {s:25s} {n}")
        print("Impugnación:")
        for s, n in dec["impugnacion"]:
            print(f"  {s:25s} {n}")

        print("\n" + "=" * 70)
        print("CATÁLOGO DE ACCIONES (asunto)")
        print("=" * 70)
        asu = catalog_asunto_verbs(cases)
        for s, n in asu["top_starters"]:
            print(f"  {n:3d}× {s!r}")

        print("\n" + "=" * 70)
        print("CATÁLOGO DE JUZGADOS (jerarquía)")
        print("=" * 70)
        for cat, n in catalog_juzgados(cases):
            pct = 100 * n / len(cases)
            print(f"  {cat:25s} {n:4d} ({pct:5.1f}%)")
    finally:
        db.close()


if __name__ == "__main__":
    main()
