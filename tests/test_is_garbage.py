"""Tests del backstop anti-degeneración `_is_garbage` (backend/v9/llm_gap_fill).

Casos reales de degeneración del Qwen3-4B local (c499/c500/c502, ingesta 2026-05-26)
vs valores jurídicos legítimos que NO deben marcarse (abreviaturas E.P.S./S.A.S.,
separadores '------', notas con '#', listas enumeradas)."""
from backend.v9.llm_gap_fill import _is_garbage


GARBAGE = [
    ",.AND__U1.IG_DE#._JCONT.J_IN..  CONTIES...._FACT.F_AND.S_MAY.OLUCK.OF.UK.INGINUP.0(",  # c502 vinculados
    '. o " o ¿ o ** " ** donde ¿ **_ _ _ ¿ " ¿ " **_ ¿, ¿ ¿ ¿ para ¿ ** ¿ donde, ¿ **',       # c502 observaciones
    "垒 in  in, .II,,    the,1,II, ,, de, de 11 11, , ,, de de  11,,,,,,,,, , , ,,,,,,,,",      # c499 vinculados (no latino)
    "1 1 1 1 1 1 1",            # bucle repetitivo clásico
    "CONTCONTCONTCONT",         # subcadena repetida
]

LEGIT = [
    "SECRETARÍA DE EDUCACIÓN DEL DEPARTAMENTO DE SANTANDER",
    "SANITAS E.P.S. - I.P.S. NIÑOS DE PAPEL I.C.B.F.",            # abreviaturas con puntos
    "Colegio Newport School S.A.S.; Redcol Holding S.A.S.",
    "Sujeto de especial protección: adulto mayor / tercera edad",
    "DEBIDO_PROCESO - IGUALDAD",                                   # enum con guion bajo
    "TRASLADO",
    "ACCIONANTE",
    "68001400302520260036800",                                    # rad 23 dígitos
    "2-2026-104200-001186",                                       # FOREST
    "Solicito respetuosamente al despacho: 1. Tutelar el derecho. 2. Ordenar a la entidad.",
]


def test_is_garbage_detecta_degeneracion():
    for v in GARBAGE:
        assert _is_garbage(v) is True, f"NO detectó basura: {v!r}"


def test_is_garbage_respeta_legitimos():
    for v in LEGIT:
        assert _is_garbage(v) is False, f"FALSO POSITIVO: {v!r}"
