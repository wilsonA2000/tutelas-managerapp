"""Validador post-extraccion unificado para Pipeline y Agent.

Ejecuta validaciones que AMBOS extractores deben aplicar despues de obtener campos.
Fuente unica de verdad para reglas de validacion de campos extraidos.
"""

import re
import json
from pathlib import Path

from backend.agent.forest_extractor import FOREST_BLACKLIST


def validate_extraction(case, fields: dict) -> tuple[dict, list[str]]:
    """Validar y corregir campos extraidos.

    Args:
        case: Case ORM object (para folder_name, etc.)
        fields: dict de campo -> valor

    Returns:
        (campos_corregidos, warnings) — campos_corregidos solo contiene campos que cambiaron
    """
    corrected = {}
    warnings = []

    folder_name = case.folder_name or ""

    # 1. RADICADO vs CARPETA
    rad_m = re.match(r'(20\d{2})[-\s]?0*(\d+)', folder_name)
    if rad_m:
        case_seq = rad_m.group(2).lstrip('0')
        rad23 = fields.get("radicado_23_digitos", "") or fields.get("RADICADO_23_DIGITOS", "")
        if rad23:
            rad23_clean = re.sub(r'[\s\-\.]', '', rad23)
            if case_seq not in rad23_clean:
                corrected["radicado_23_digitos"] = ""
                warnings.append(f"Radicado 23d '{rad23}' no coincide con carpeta '{folder_name}' — eliminado")

    # 2. FOREST blacklist + formato
    for forest_field in ("radicado_forest", "RADICADO_FOREST", "forest_impugnacion", "FOREST_IMPUGNACION"):
        forest_val = fields.get(forest_field, "")
        if forest_val:
            clean = re.sub(r'\D', '', forest_val)
            if clean in FOREST_BLACKLIST:
                corrected[forest_field.lower()] = ""
                warnings.append(f"{forest_field} '{forest_val}' esta en blacklist — eliminado")
            elif "-" in forest_val:
                corrected[forest_field.lower()] = ""
                warnings.append(f"{forest_field} '{forest_val}' tiene guiones (no es FOREST) — eliminado")
            elif len(clean) < 7:
                corrected[forest_field.lower()] = ""
                warnings.append(f"{forest_field} '{forest_val}' muy corto ({len(clean)} digitos) — eliminado")

    # 3. FECHAS formato DD/MM/YYYY
    date_fields = [
        "fecha_ingreso", "fecha_respuesta", "fecha_fallo_1st", "fecha_fallo_2nd",
        "fecha_apertura_incidente", "FECHA_INGRESO", "FECHA_RESPUESTA",
        "FECHA_FALLO_1ST", "FECHA_FALLO_2ND", "FECHA_APERTURA_INCIDENTE",
    ]
    for df in date_fields:
        val = fields.get(df, "")
        if val and not re.match(r'^\d{2}/\d{2}/\d{4}$', val.strip()):
            corrected[df.lower()] = ""
            warnings.append(f"{df} '{val}' formato invalido (debe ser DD/MM/YYYY) — eliminado")

    # 4. FALLO enum
    fallo_fields = {
        "sentido_fallo_1st": {"CONCEDE", "NIEGA", "IMPROCEDENTE", "CONCEDE PARCIALMENTE"},
        "sentido_fallo_2nd": {"CONFIRMA", "REVOCA", "MODIFICA"},
        "SENTIDO_FALLO_1ST": {"CONCEDE", "NIEGA", "IMPROCEDENTE", "CONCEDE PARCIALMENTE"},
        "SENTIDO_FALLO_2ND": {"CONFIRMA", "REVOCA", "MODIFICA"},
    }
    for ff, valid_vals in fallo_fields.items():
        val = fields.get(ff, "")
        if val and val.strip().upper() not in valid_vals:
            corrected[ff.lower()] = ""
            warnings.append(f"{ff} '{val}' no es valor valido ({valid_vals}) — eliminado")

    # 5. ABOGADO en lista valida
    abogado_val = fields.get("abogado_responsable", "") or fields.get("ABOGADO_RESPONSABLE", "")
    if abogado_val:
        try:
            abogados_path = Path(__file__).resolve().parent.parent / "data" / "abogados_sed.json"
            if abogados_path.exists():
                with open(abogados_path) as f:
                    abogados_validos = json.load(f)
                import unicodedata
                def _norm(s):
                    return ''.join(c for c in unicodedata.normalize('NFD', s) if unicodedata.category(c) != 'Mn').upper()
                val_norm = _norm(abogado_val)
                match_found = False
                for av in abogados_validos:
                    av_norm = _norm(av)
                    av_words = set(av_norm.split())
                    val_words = set(val_norm.split())
                    if len(av_words & val_words) >= 2:
                        match_found = True
                        if av != abogado_val:
                            corrected["abogado_responsable"] = av
                        break
                if not match_found:
                    corrected["abogado_responsable"] = ""
                    warnings.append(f"Abogado '{abogado_val}' no esta en lista valida — eliminado")
        except Exception:
            pass

    # 6. IDIOMA: detectar respuestas en ingles
    obs = fields.get("observaciones", "") or fields.get("OBSERVACIONES", "")
    if obs:
        english_markers = ["this case", "the plaintiff", "the court", "was filed", "regarding", "the defendant"]
        obs_lower = obs.lower()
        english_count = sum(1 for m in english_markers if m in obs_lower)
        if english_count >= 2:
            corrected["observaciones"] = ""
            warnings.append(f"OBSERVACIONES en ingles detectado ({english_count} marcadores) — eliminado")

    # 7. RADICADO 23D formato con guiones
    rad23 = fields.get("radicado_23_digitos", "") or fields.get("RADICADO_23_DIGITOS", "")
    if rad23 and "radicado_23_digitos" not in corrected:
        clean = re.sub(r'[\s\.]', '', rad23)
        digits_only = re.sub(r'\D', '', clean)
        if len(digits_only) >= 23 and "-" not in rad23:
            d = digits_only
            formatted = f"{d[:2]}-{d[2:5]}-{d[5:7]}-{d[7:9]}-{d[9:12]}-{d[12:16]}-{d[16:21]}-{d[21:23]}"
            corrected["radicado_23_digitos"] = formatted

    return corrected, warnings
