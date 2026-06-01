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
    # La carpeta puede nombrarse con:
    #  (a) radicado judicial corto (secuencia 1-4 dígitos, ej: "2026-00095"), o
    #  (b) radicado FOREST interno (secuencia 5+ dígitos, ej: "2026-63875").
    # Solo podemos validar el radicado 23d contra la carpeta si estamos en el caso (a).
    # Heurística: si la secuencia significativa tiene ≥5 dígitos o coincide con el FOREST
    # conocido, la carpeta es tipo FOREST y no sirve para validar el radicado judicial.
    rad_m = re.match(r'(20\d{2})[-\s]?0*(\d+)', folder_name)
    if rad_m:
        case_seq = rad_m.group(2).lstrip('0')
        rad23 = fields.get("radicado_23_digitos", "") or fields.get("RADICADO_23_DIGITOS", "")
        forest_val = (
            fields.get("radicado_forest", "")
            or fields.get("RADICADO_FOREST", "")
            or getattr(case, "radicado_forest", "") or ""
        )
        forest_clean = re.sub(r'\D', '', str(forest_val))
        folder_matches_forest = bool(case_seq) and bool(forest_clean) and case_seq in forest_clean
        folder_is_forest_shape = len(case_seq) >= 5  # 5+ dígitos → es FOREST, no judicial
        if rad23 and not folder_matches_forest and not folder_is_forest_shape:
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

    # 4. FALLO enum — normalizar a valor canonico + extraer detalle para observaciones.
    # El accionante puede agregar matices ("CONCEDE PARCIALMENTE diagnostico - NIEGA tutor sombra")
    # que son informacion valiosa pero NO pertenecen al enum. Los movemos a OBSERVACIONES
    # con prefijo [DETALLE FALLO] para que el usuario pueda consultarlos sin romper el enum.
    # Orden importa: los mas especificos/compuestos primero.
    ENUM_FALLO_1ST = [
        "CONCEDE PARCIALMENTE", "HECHO SUPERADO", "DESISTIMIENTO",
        "IMPROCEDENTE", "CONCEDE", "NIEGA", "AMPARA",
    ]
    ENUM_FALLO_2ND = ["CONFIRMA PARCIALMENTE", "REVOCA PARCIALMENTE", "CONFIRMA", "REVOCA", "MODIFICA"]
    # Sinonimos juridicos → valor canonico
    FALLO_1ST_SYNONYMS = {
        "AMPARA": "CONCEDE",
        "AMPARADO": "CONCEDE",
        "CARENCIA ACTUAL DE OBJETO POR HECHO SUPERADO": "HECHO SUPERADO",
        "CARENCIA DE OBJETO": "HECHO SUPERADO",
        "DESISTIMIENTO ACEPTADO": "DESISTIMIENTO",
    }

    def _normalize_fallo(raw: str, enum_list: list, synonyms: dict = None) -> tuple[str, str]:
        """Devuelve (valor_canonico, detalle_extra). Si no hay match, ("", raw)."""
        if not raw:
            return "", ""
        up = raw.strip().upper()
        # Exact match a sinonimo
        if synonyms and up in synonyms:
            return synonyms[up], ""
        # Busqueda por token (mayor especificidad primero)
        for canon in enum_list:
            if canon in up:
                detalle = up.replace(canon, "", 1).strip(" -—()[]:;,.")
                mapped = (synonyms or {}).get(canon, canon)
                return mapped, detalle
        # Busqueda por sinonimo parcial
        for syn, canon in (synonyms or {}).items():
            if syn in up:
                detalle = up.replace(syn, "", 1).strip(" -—()[]:;,.")
                return canon, detalle
        return "", raw  # No match — marcar para reintento

    fallo_detalles = []  # acumula (campo, detalle) para anexar a obs
    for field_canonical, enum_list, syns in (
        ("sentido_fallo_1st", ENUM_FALLO_1ST, FALLO_1ST_SYNONYMS),
        ("sentido_fallo_2nd", ENUM_FALLO_2ND, None),
    ):
        raw = fields.get(field_canonical) or fields.get(field_canonical.upper()) or ""
        if not raw:
            continue
        canon, detalle = _normalize_fallo(raw, enum_list, syns)
        if canon and canon != raw.strip().upper():
            corrected[field_canonical] = canon
            if detalle:
                fallo_detalles.append((field_canonical, detalle[:300]))
            warnings.append(f"{field_canonical} normalizado: '{raw}' → '{canon}'")
        elif not canon:
            # No se pudo normalizar — limpiar y avisar
            corrected[field_canonical] = ""
            warnings.append(f"{field_canonical}='{raw}' no reconocido en enum — eliminado, revisar manualmente")

    # Anexar detalles extraidos a observaciones (si hay)
    if fallo_detalles:
        obs_raw = fields.get("observaciones") or fields.get("OBSERVACIONES") or ""
        appendices = " ".join(f"[DETALLE {campo.upper()}] {det}." for campo, det in fallo_detalles)
        # Solo anexar si no esta ya presente
        if appendices not in obs_raw:
            nueva_obs = (obs_raw.rstrip(" .") + " " + appendices).strip()
            corrected["observaciones"] = nueva_obs[:3000]
            warnings.append(f"Detalles de fallo movidos a observaciones: {len(fallo_detalles)}")

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

    # 8. F4 (v5.0) — RADICADOS AJENOS EN CAMPOS NARRATIVOS
    # Si observaciones/asunto/pretensiones mencionan "20YY-NNNNN" que no es el
    # rad_corto del caso, advertir; si el patron es "Caso 20YY-NNNNN" en
    # observaciones (indicador de contaminacion B3), eliminar esa oracion.
    final_rad23 = corrected.get("radicado_23_digitos", "") or rad23 or ""
    rc_official = ""
    if final_rad23:
        _digits = re.sub(r"\D", "", final_rad23)
        _m = re.search(r"(20\d{2})(\d{5})\d{2}$", _digits)
        if _m:
            rc_official = f"{_m.group(1)}-{_m.group(2)}"
    rc_folder = ""
    _fm = re.match(r"(20\d{2})-0*(\d{1,5})", folder_name)
    if _fm:
        rc_folder = f"{_fm.group(1)}-{int(_fm.group(2)):05d}"
    # F4: si folder difiere del rad23 oficial, el folder esta malformado (bug B1).
    # No tolerar menciones que coincidan con el folder — solo con el oficial.
    if rc_official and rc_folder and rc_folder != rc_official:
        rc_folder = ""  # descartar folder como "legitimo"

    # Keywords que indican mencion legitima de otros radicados (tutelas acumuladas)
    _LEGIT_KW = (
        "acumulad", "conex", "relacionad", "tutela previa",
        "anterior tutela", "radicados acumulados",
    )

    for narrative_field in ("observaciones", "asunto", "pretensiones"):
        val = fields.get(narrative_field) or fields.get(narrative_field.upper()) or ""
        # No tocar valor ya corregido por otras reglas
        if not val or narrative_field in corrected:
            continue
        # Excluir menciones de FOREST literales (11 digitos continuos prefijados por keyword)
        val_scan = re.sub(
            r"(?i)(?:forest|radicado\s+(?:numero|n[uú]mero|interno)|n[uú]mero\s+de\s+radicado)\s*:?\s*\d{7,}",
            " ",
            val,
        )
        mentions = set()
        for mm in re.finditer(r"\b(20\d{2})[-\s]0*(\d{1,5})(?!\d)\b", val_scan):
            norm = f"{mm.group(1)}-{int(mm.group(2)):05d}"
            mentions.add(norm)
        foreign = set()
        for m in mentions:
            if rc_official and m == rc_official:
                continue
            if rc_folder and m == rc_folder:
                continue
            foreign.add(m)
        if not foreign:
            continue
        # Si la obs usa keyword de acumuladas, tolerar (son legitimas)
        if narrative_field == "observaciones" and any(kw in val.lower() for kw in _LEGIT_KW):
            warnings.append(
                f"{narrative_field}: radicados ajenos {sorted(foreign)} pero keyword 'acumulada/conexa' — tolerado"
            )
            continue
        # Para observaciones: intentar remover oraciones que digan "Caso 20YY-NNNNN..."
        # (patron B3: "Caso 2026-66132 en estado ACTIVO. ..." → eliminar esa oracion)
        if narrative_field == "observaciones" and rc_official:
            sentences = re.split(r"(?<=[\.\!])\s+", val)
            cleaned = []
            removed = 0
            for s in sentences:
                s_mentions = set()
                s_scan = re.sub(
                    r"(?i)(?:forest|radicado\s+(?:numero|n[uú]mero|interno)|n[uú]mero\s+de\s+radicado)\s*:?\s*\d{7,}",
                    " ",
                    s,
                )
                for mm in re.finditer(r"\b(20\d{2})[-\s]0*(\d{1,5})(?!\d)\b", s_scan):
                    s_mentions.add(f"{mm.group(1)}-{int(mm.group(2)):05d}")
                s_foreign = s_mentions - ({rc_official} if rc_official else set()) - ({rc_folder} if rc_folder else set())
                if s_foreign and re.search(r"(?i)\bcaso\s+20\d{2}[-\s]\d", s):
                    removed += 1
                    continue  # eliminar oracion contaminada
                cleaned.append(s)
            if removed:
                new_val = " ".join(cleaned).strip()
                if new_val and new_val != val.strip():
                    corrected[narrative_field] = new_val[:3000]
                    warnings.append(
                        f"{narrative_field}: {removed} oracion(es) con radicado ajeno eliminadas "
                        f"(oficial={rc_official}, ajenos={sorted(foreign)})"
                    )
                    continue
        # Warning pero no modificar
        warnings.append(
            f"{narrative_field}: menciona radicados ajenos {sorted(foreign)} "
            f"(oficial={rc_official or 'NULL'}, folder={rc_folder or 'NULL'}) — revisar"
        )

    # ============================================================
    # F11 (v8.3): impugnacion=NO debe implicar fallo_2nd vacio.
    # Si la IA o el regex llenaron fallo_2nd cuando impugnacion=NO,
    # los limpiamos y marcamos warning. Evita las 42 inconsistencias
    # detectadas por audit_cases R1.
    # ============================================================
    impugnacion_val = (
        fields.get("impugnacion", "")
        or fields.get("IMPUGNACION", "")
        or getattr(case, "impugnacion", "") or ""
    ).strip().upper()
    if impugnacion_val == "NO":
        for f_2nd in ("sentido_fallo_2nd", "juzgado_2nd", "fecha_fallo_2nd",
                       "SENTIDO_FALLO_2ND", "JUZGADO_2ND", "FECHA_FALLO_2ND"):
            v = fields.get(f_2nd, "")
            if v and str(v).strip():
                corrected[f_2nd.lower()] = ""
                warnings.append(
                    f"F11: impugnacion=NO pero {f_2nd}={v!r} — eliminado por incoherencia"
                )

    # ============================================================
    # F12 (v8.3): juzgado y juzgado_2nd no pueden ser idénticos.
    # 2a instancia siempre es jerárquicamente superior.
    # ============================================================
    j1 = (
        fields.get("juzgado", "") or fields.get("JUZGADO", "")
        or getattr(case, "juzgado", "") or ""
    ).strip().upper()
    j2 = (
        fields.get("juzgado_2nd", "") or fields.get("JUZGADO_2ND", "")
        or getattr(case, "juzgado_2nd", "") or ""
    ).strip().upper()
    if j1 and j2 and j1 == j2:
        corrected["juzgado_2nd"] = ""
        warnings.append(
            f"F12: juzgado y juzgado_2nd idénticos ({j1}) — juzgado_2nd eliminado"
        )

    # ============================================================
    # F13 (v8.3): orden cronológico fechas. Si una fecha posterior es
    # anterior a una previa, descartar la inconsistente (mantener la primera).
    # Aplica solo entre pares directos. fecha_ingreso es ancla.
    # ============================================================
    def _date_tuple(field_key):
        for k in (field_key, field_key.upper()):
            v = fields.get(k, "")
            if v:
                m = re.match(r'(\d{1,2})[/-](\d{1,2})[/-](\d{4})', str(v))
                if m:
                    try:
                        d, mth, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
                        if 1 <= d <= 31 and 1 <= mth <= 12 and 2018 <= y <= 2030:
                            return (y, mth, d), v, k
                    except (ValueError, TypeError):
                        pass
        existing = getattr(case, field_key, None)
        if existing:
            m = re.match(r'(\d{1,2})[/-](\d{1,2})[/-](\d{4})', str(existing))
            if m:
                try:
                    d, mth, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
                    if 1 <= d <= 31 and 1 <= mth <= 12 and 2018 <= y <= 2030:
                        return (y, mth, d), existing, field_key
                except (ValueError, TypeError):
                    pass
        return None

    # F13 v8.3.1: detecta fechas inconsistentes pero NO las modifica.
    # Razon: el bug raiz puede estar en una fecha ANTERIOR de la cadena
    # (ej. fecha_ingreso erronea). Auto-eliminar la "posterior" puede
    # borrar el dato correcto. Solo emite warning para revisión humana.
    chrono_seq = ["fecha_ingreso", "fecha_fallo_1st", "fecha_fallo_2nd",
                   "fecha_apertura_incidente"]
    prev = None
    for fkey in chrono_seq:
        cur = _date_tuple(fkey)
        if cur is None:
            continue
        if prev is not None and cur[0] < prev[0]:
            warnings.append(
                f"F13: {fkey}={cur[1]} es anterior a {prev[2]}={prev[1]} — REVISAR (sin auto-correccion)"
            )
        prev = cur

    # ============================================================
    # F15 (v9.x, 2026-05-28): Flag falta de legitimación pasiva.
    # SED Santander NO es competente en municipios certificados (Bcga,
    # Floridablanca, Girón, Piedecuesta, Barrancabermeja). Si ciudad ∈ certificados
    # Y SED Santander accionada → agregar warning sin auto-cambiar estado.
    # ============================================================
    _CERTIFICADOS = {"BUCARAMANGA", "FLORIDABLANCA", "GIRON", "GIRÓN",
                     "PIEDECUESTA", "BARRANCABERMEJA"}
    ciudad_val = (
        fields.get("ciudad", "") or fields.get("CIUDAD", "")
        or getattr(case, "ciudad", "") or ""
    ).strip().upper()
    accionados_val = (
        fields.get("accionados", "") or fields.get("ACCIONADOS", "")
        or getattr(case, "accionados", "") or ""
    ).upper()
    if ciudad_val in _CERTIFICADOS:
        sed_accionada = (
            ("SECRETARÍA DE EDUCACI" in accionados_val
             or "SECRETARIA DE EDUCACI" in accionados_val)
            and "SANTANDER" in accionados_val
            and "MUNICIPAL" not in accionados_val
        )
        if sed_accionada:
            warnings.append(
                f"F15: ciudad={ciudad_val} (municipio certificado) + SED Santander "
                f"accionada — posible falta de legitimación pasiva. "
                f"Sugerir estado=IMPROCEDENTE y verificar competencia."
            )
            # 1D: también agregar flag a observaciones (append-only, no pisa texto manual)
            flag_f15 = f"Falta legitimación pasiva: {ciudad_val} es municipio certificado"
            obs_actual = str(
                corrected.get("observaciones") or fields.get("observaciones") or
                getattr(case, "observaciones", "") or ""
            )
            if flag_f15 not in obs_actual:
                corrected["observaciones"] = (
                    (obs_actual.rstrip() + "\n" + flag_f15) if obs_actual else flag_f15
                )

    # ============================================================
    # F16 (2026-06-01): Accionante con texto basura al final del nombre.
    # El LLM o el regex a veces captura "Y PADRES DE FAMILIA...", "VS GOBERNACIÓN",
    # "CORREO ELECTRONICO" etc. pegado al nombre. Truncar en el primer marcador.
    # ============================================================
    _RE_ACCIONANTE_BASURA = re.compile(
        r"\s+(?:Y\s+PADRES?\s+DE\s+FAMILIA|Y\s+OTROS|Y\s+DEM[AÁ]S|"
        r"Y\s+ACUMULADOS|CON\s+FOREST\b|CORREO\s+ELECTR[OÓ]NICO|"
        r"VS\.?\s+[A-Z]|CON\s+LA\s+GOBERNACI[OÓ]N|"
        r"QUIEN\s+ACTÚA|QUIEN\s+ACTUA|LISTA\s+DE\s+ACCIONANTES).*$",
        re.IGNORECASE,
    )
    accionante_raw = str(corrected.get("accionante") or fields.get("accionante") or "")
    if accionante_raw:
        accionante_clean = _RE_ACCIONANTE_BASURA.sub("", accionante_raw).strip()
        if accionante_clean != accionante_raw:
            warnings.append(
                f"F16: accionante truncado: {accionante_raw!r} → {accionante_clean!r}"
            )
            corrected["accionante"] = accionante_clean

    # ============================================================
    # F14 (v9.x, 2026-05-28): sentido_fallo sin fecha = sentido a la deriva.
    # Solo emite WARNING — NO modifica datos. Razón: detectado 41 cases con
    # esta inconsistencia (audit 2026-05-28). El test F11 espera que el
    # validator NO toque fields cuando hay solo sentido o solo fecha; F14
    # respeta esa contract y solo flaggea para revisión humana posterior.
    # ============================================================
    def _from_fields(field_key):
        v = fields.get(field_key, "") or fields.get(field_key.upper(), "")
        return v.strip() if isinstance(v, str) else ""

    for sent_key, fecha_key in (
        ("sentido_fallo_1st", "fecha_fallo_1st"),
        ("sentido_fallo_2nd", "fecha_fallo_2nd"),
    ):
        s_f = _from_fields(sent_key)
        f_f = _from_fields(fecha_key)
        case_s = str(getattr(case, sent_key, "") or "").strip()
        case_f = str(getattr(case, fecha_key, "") or "").strip()
        s_total = s_f or case_s
        f_total = f_f or case_f
        if s_total and not f_total:
            warnings.append(
                f"F14: {sent_key}={s_total!r} sin {fecha_key} — REVISAR (sin auto-corrección)"
            )
        elif f_total and not s_total:
            warnings.append(
                f"F14: {fecha_key}={f_total!r} sin {sent_key} — REVISAR (sin auto-corrección)"
            )

    return corrected, warnings
