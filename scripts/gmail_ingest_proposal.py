"""Dry-run de ingestión: propone case para cada correo NO ingestado valioso.

Usa la MISMA extracción + matcher de producción (resolve_radicado/extract_forest/
extract_accionante/match_to_case). NO escribe nada. Surfacea el grado de conflación
(cuántos cases comparten el rad corto) para que Wilson juzgue los ambiguos.

Salida: data/gmail_ingest_proposal.json + tabla por stdout.
"""
import sys, json, re
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.database.database import SessionLocal
from backend.database.models import Case
from backend.email import gmail_monitor as gm
from backend.email.gmail_monitor import (
    _get_gmail_service, _extract_body_complete, _find_attachment_parts,
    classify_email_type, resolve_radicado, extract_forest, extract_accionante,
    match_to_case, _normalize_typos, _normalize_rad_num,
)

VAL = json.load(open("data/gmail_no_ingestados.json"))

def is_valuable(e):
    s = e["subject"]; u = s.upper(); frm = (e.get("from") or "").upper()
    if s.startswith(("Alerta de seguridad", "Security alert")): return False
    if any(x in frm for x in ("CEREBRAS", "CLAUDE TEAM", "GOOGLE AI", "GOOGLEPLAY", "NO-REPLY@GOOGLE", "ACCOUNTS.GO")): return False
    if any(x in u for x in ("SOLICITUD ACCESO CUADRO", "INFORME TUTELAS DE", "IMPULSO DE HUMANO", "BIENVENIDA", "POWER MOVES", "EVERYDAY LIFE")): return False
    if "RESPUESTA" in u or "APOYO JUR" in frm: return True
    if any(k in u for k in ("NOTIFIC", "AUTO", "SENTENCIA", "FALLO", "TRASLADO", "ADMIS", "IMPUGNAC", "REQUERIMIENTO", "INCIDENTE", "DESACATO", "REPARTO", "CONCEDE", "NULIDAD", "DESISTIMIENTO", "OFICIO", "AVOCA", "VINCULAR")): return True
    return False

cands = [e for e in VAL if is_valuable(e)]
print(f"Valiosos a evaluar: {len(cands)} de {len(VAL)}\n")

db = SessionLocal()
service = _get_gmail_service()

def short_rad_conflation(rad_corto):
    """Cuántos cases comparten ese año:secuencia (grado de conflación)."""
    if not rad_corto: return []
    m = re.match(r"(20\d{2})[-]?0*(\d+)", rad_corto)
    if not m: return []
    target = f"{m.group(1)}:{m.group(2)}"
    rows = db.query(Case).filter(Case.folder_name.ilike(f"{m.group(1)}%")).all()
    return [c for c in rows if _normalize_rad_num(c.folder_name) == target]

out = []
for e in cands:
    rfcid = e["rfcid"]
    try:
        resp = service.users().messages().list(userId="me", q=f"rfc822msgid:{rfcid}").execute()
        msgs = resp.get("messages", [])
        if not msgs:
            out.append({**e, "match": None, "note": "NO_HALLADO_EN_GMAIL"}); continue
        gid = msgs[0]["id"]
        msg = service.users().messages().get(userId="me", id=gid, format="full").execute()
        hdrs = {h["name"]: h["value"] for h in msg.get("payload", {}).get("headers", [])}
        subject = _normalize_typos(hdrs.get("Subject", ""))
        sender = hdrs.get("From", "")
        body = _extract_body_complete(msg.get("payload", {}))
        atts = _find_attachment_parts(msg.get("payload", {}))
        att_names = [a["filename"] for a in atts]
        rd = resolve_radicado(subject, body)
        rd["forest"] = extract_forest(body, att_names)
        acc = extract_accionante(subject, body)
        from backend.email.rad_utils import reconcile as _rc
        rd["radicado_23"], rd["radicado_corto"] = _rc(rd.get("radicado_23", ""), rd.get("radicado_corto", ""))
        case = match_to_case(db, rd, acc)
        confl = short_rad_conflation(rd.get("radicado_corto", ""))
        out.append({
            "rfcid": rfcid, "gid": gid, "unread": e["unread"], "subject": subject[:70],
            "rad23": rd.get("radicado_23", ""), "rad_corto": rd.get("radicado_corto", ""),
            "forest": rd.get("forest", ""), "accionante": acc[:30], "n_att": len(att_names),
            "match_case_id": case.id if case else None,
            "match_accionante": (case.accionante or "")[:30] if case else None,
            "confl_short_rad": [c.id for c in confl],
        })
        tag = f"→c{case.id} ({(case.accionante or '')[:22]})" if case else "→ SIN MATCH"
        cfl = f" [conflación x{len(confl)}: {[c.id for c in confl]}]" if len(confl) > 1 else ""
        print(f"[{'U' if e['unread'] else 'L'}] {subject[:52]:52} rad23={'Y' if rd.get('radicado_23') else '-'} rc={rd.get('radicado_corto','') or '-':12} att={len(att_names)} {tag}{cfl}")
    except Exception as ex:
        out.append({**e, "match": None, "note": f"ERROR: {ex}"})
        print(f"  ERROR {rfcid[:30]}: {ex}")

json.dump(out, open("data/gmail_ingest_proposal.json", "w"), ensure_ascii=False, indent=1)
matched = [o for o in out if o.get("match_case_id")]
print(f"\n=== RESUMEN: {len(matched)}/{len(cands)} con match, {len(cands)-len(matched)} sin match ===")
db.close()
