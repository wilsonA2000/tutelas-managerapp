"""Validador post-extraccion unificado para Pipeline y Agent.

Ejecuta validaciones que AMBOS extractores deben aplicar despues de obtener campos.
Fuente unica de verdad para reglas de validacion de campos extraidos.
"""

import re
import json
import logging
from pathlib import Path

from backend.agent.forest_extractor import FOREST_BLACKLIST

logger = logging.getLogger("tutelas.validator")


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
    parsed_dates = {}  # campo -> (dia, mes, anio) para validacion cruzada
    for df in date_fields:
        val = fields.get(df, "")
        if val:
            m = re.match(r'^(\d{2})/(\d{2})/(\d{4})$', val.strip())
            if not m:
                corrected[df.lower()] = ""
                warnings.append(f"{df} '{val}' formato invalido (debe ser DD/MM/YYYY) — eliminado")
            else:
                d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
                if not (1 <= d <= 31 and 1 <= mo <= 12 and 2020 <= y <= 2027):
                    corrected[df.lower()] = ""
                    warnings.append(f"{df} '{val}' fuera de rango valido — eliminado")
                else:
                    parsed_dates[df.lower()] = (y, mo, d)

    # 3b. Consistencia de fechas: fallo >= ingreso
    fi = parsed_dates.get("fecha_ingreso")
    ff1 = parsed_dates.get("fecha_fallo_1st")
    if fi and ff1 and ff1 < fi:
        warnings.append(f"fecha_fallo_1st {ff1} anterior a fecha_ingreso {fi} — revisar")

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

    # 4b. INTERDEPENDENCIA de campos
    fallo_2nd = fields.get("sentido_fallo_2nd", "") or fields.get("SENTIDO_FALLO_2ND", "")
    impugnacion = fields.get("impugnacion", "") or fields.get("IMPUGNACION", "")
    if fallo_2nd and impugnacion != "SI":
        warnings.append(f"sentido_fallo_2nd='{fallo_2nd}' pero impugnacion='{impugnacion}' — revisar")
    incidente = fields.get("incidente", "") or fields.get("INCIDENTE", "")
    fecha_inc = fields.get("fecha_apertura_incidente", "") or fields.get("FECHA_APERTURA_INCIDENTE", "")
    if incidente == "SI" and not fecha_inc:
        warnings.append("incidente=SI pero sin fecha_apertura_incidente — revisar")
    quien_imp = fields.get("quien_impugno", "") or fields.get("QUIEN_IMPUGNO", "")
    if impugnacion == "SI" and not quien_imp:
        warnings.append("impugnacion=SI pero sin quien_impugno — revisar")

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
                    logger.warning("Abogado rechazado: '%s' (caso: %s)", abogado_val, folder_name)
        except Exception:
            pass

    # 6. IDIOMA: detectar respuestas en ingles en campos de texto libre
    # Threshold: >= 3 marcadores para evitar falsos positivos con terminos legales latinos
    english_markers = [
        "this case", "the plaintiff", "the court", "was filed",
        "the defendant", "therefore", "was granted", "hereby",
        "the ruling", "filed a", "requests that", "in accordance",
        "the respondent", "the petitioner",
    ]
    _text_fields = ["observaciones", "asunto", "pretensiones", "decision_incidente",
                     "decision_incidente_2", "decision_incidente_3"]
    for _tf in _text_fields:
        _tv = fields.get(_tf, "") or fields.get(_tf.upper(), "")
        if _tv and len(_tv) > 50:
            _tv_lower = _tv.lower()
            _eng_count = sum(1 for m in english_markers if m in _tv_lower)
            if _eng_count >= 3:
                corrected[_tf] = ""
                warnings.append(f"{_tf.upper()} en ingles detectado ({_eng_count} marcadores) — eliminado")

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
