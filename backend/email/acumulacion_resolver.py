"""Resolución de acumulaciones procesales con efectos en DB (v9.2).

Toma un caso "primario" (al que la ingesta acaba de adjuntar documentos) y, si
detecta una acumulación, deja el cuadro consistente:

  1. Garantiza un caso por cada radicado/accionante acumulado (CREA el hermano
     faltante con su accionante — esto es lo que el sistema viejo nunca hacía).
  2. Registra el vínculo RECTOR/ACUMULADO (el de consecutivo menor es RECTOR).
  3. Enruta cada sentencia/auto individual al caso de su accionante; los docs
     "conjuntos" (que mencionan ≥2 radicados, p.ej. la respuesta FOREST común)
     se quedan con el RECTOR.

Es idempotente y dry-runnable: `plan_acumulacion` no toca la DB; `apply_plan`
aplica. La ingesta llama `resolve_acumulacion(db, case, apply=True)`.

Las funciones de detección (puras) viven en `backend/email/acumulacion.py`.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy.orm import Session

from backend.database.models import AuditLog, Case, Document
from backend.email.acumulacion import (
    analyze_docs,
    harvest_rad_accionante_pairs,
    harvest_rads_corto,
    name_key,
)
from backend.email.rad_utils import derive_rad_corto_from_rad23, juzgado_code

logger = logging.getLogger(__name__)


@dataclass
class AcumItem:
    rad_corto: str                 # "2025-00047"
    rad23: str | None              # rad23 construido/encontrado
    accionante: str | None
    action: str                    # "EXISTS" | "CREATE"
    case_id: int | None            # poblado tras apply (o si ya existía)
    role: str                      # "RECTOR" | "ACUMULADO"


@dataclass
class DocRoute:
    doc_id: int
    filename: str
    from_case_id: int
    to_rad: str                    # rad_corto destino
    to_case_id: int | None


@dataclass
class AcumPlan:
    is_acumulacion: bool = False
    rector_rad: str | None = None
    fecha: str | None = None
    auto_doc_id: int | None = None
    items: list[AcumItem] = field(default_factory=list)
    doc_routes: list[DocRoute] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def _consec(rad_corto: str) -> int:
    m = re.match(r"20\d{2}-(\d{5})", rad_corto or "")
    return int(m.group(1)) if m else 99999


def _build_rad23(juz_code: str, rad_corto: str) -> str | None:
    """Construye rad23 = juzgado(12) + año(4) + seq(5) + '00' desde el rad_corto."""
    m = re.match(r"(20\d{2})-(\d{5})", rad_corto or "")
    if not (juz_code and len(juz_code) == 12 and m):
        return None
    return f"{juz_code}{m.group(1)}{m.group(2)}00"


def _find_case(db: Session, rad_corto: str, rad23: str | None,
               accionante: str | None, juz_code: str) -> Case | None:
    """Busca un caso existente para este radicado/accionante en el mismo juzgado.

    Prioridad: (1) rad23 exacto, (2) rad_corto + mismo juzgado, (3) nombre de
    accionante exacto (normalizado). Evita falsos positivos cross-juzgado.
    """
    if rad23:
        c = db.query(Case).filter(Case.radicado_23_digitos == rad23).first()
        if c:
            return c
    # rad_corto derivado del rad23 de cada caso, restringido al mismo juzgado
    if juz_code:
        candidatos = db.query(Case).filter(
            Case.radicado_23_digitos.like(f"{juz_code}%")
        ).all()
        for c in candidatos:
            if derive_rad_corto_from_rad23(c.radicado_23_digitos) == rad_corto:
                return c
    # por nombre de accionante (último recurso)
    if accionante:
        nk = name_key(accionante)
        for c in db.query(Case).filter(Case.accionante.isnot(None)).all():
            if name_key(c.accionante) == nk:
                return c
    return None


def _gather_docs(db: Session, case_id: int) -> list[dict]:
    docs = db.query(Document).filter(Document.case_id == case_id).all()
    return [{"id": d.id, "filename": d.filename or "",
             "text": d.extracted_text or ""} for d in docs]


def plan_acumulacion(db: Session, primary_case: Case) -> AcumPlan:
    """Analiza los docs del caso primario y devuelve un plan SIN tocar la DB."""
    plan = AcumPlan()
    docs = _gather_docs(db, primary_case.id)
    ev = analyze_docs(docs)
    if not ev.is_acumulacion:
        return plan

    juz_code = juzgado_code(primary_case.radicado_23_digitos)
    if not juz_code:
        plan.notes.append(
            "Acumulación detectada pero el caso primario no tiene rad23 con "
            "juzgado identificable — no se puede construir rad23 de los hermanos."
        )
        return plan

    members = ev.members()
    plan.is_acumulacion = True
    plan.fecha = primary_case.acumulacion_fecha
    plan.auto_doc_id = ev.evidence_doc_ids[0] if ev.evidence_doc_ids else None

    rector_rad = min(members, key=_consec)
    plan.rector_rad = rector_rad

    for rad in members:
        rad23 = _build_rad23(juz_code, rad)
        accionante = ev.pairs.get(rad)
        existing = _find_case(db, rad, rad23, accionante, juz_code)
        role = "RECTOR" if rad == rector_rad else "ACUMULADO"
        plan.items.append(AcumItem(
            rad_corto=rad,
            rad23=rad23 or (existing.radicado_23_digitos if existing else None),
            accionante=accionante or (existing.accionante if existing else None),
            action="EXISTS" if existing else "CREATE",
            case_id=existing.id if existing else None,
            role=role,
        ))

    # Enrutamiento por-doc: un doc que mapea a EXACTAMENTE un radicado (sentencia
    # o auto individual) va al caso de ese radicado; los conjuntos se quedan.
    rad_to_item = {it.rad_corto: it for it in plan.items}
    for d in docs:
        pairs = harvest_rad_accionante_pairs(d["text"])
        rads_in_doc = {r for r, _ in pairs}
        # complementar con rads del filename/texto si no hubo pares
        if not rads_in_doc:
            rads_in_doc = set(harvest_rads_corto(d["filename"]))
        if len(rads_in_doc) != 1:
            continue  # conjunto o sin rad claro → se queda con el rector
        only = next(iter(rads_in_doc))
        it = rad_to_item.get(only)
        if not it or it.role == "RECTOR":
            continue  # ya está donde debe (rector)
        plan.doc_routes.append(DocRoute(
            doc_id=d["id"], filename=d["filename"],
            from_case_id=primary_case.id, to_rad=only, to_case_id=it.case_id,
        ))
    return plan


def _create_sibling(db: Session, item: AcumItem, primary_case: Case,
                    create_folder: bool = False) -> Case:
    """Crea el caso hermano faltante.

    Si create_folder=True le da carpeta física propia (para que no quede vacía y
    pueda recibir su sentencia individual). Si False es una fila 'sombra' y los
    documentos quedan en la carpeta del RECTOR.
    """
    folder_name = re.sub(r'[<>:"/\\|?*]', "",
                         f"{item.rad_corto} {item.accionante or '[PENDIENTE REVISION]'}").strip()[:80]
    folder_path = None
    if create_folder:
        try:
            from backend.config import BASE_DIR
            fp = Path(BASE_DIR) / folder_name
            fp.mkdir(parents=True, exist_ok=True)
            folder_path = str(fp)
        except Exception as e:  # noqa: BLE001
            logger.warning("No se pudo crear carpeta del hermano %s: %s", folder_name, e)
    case = Case(
        folder_name=folder_name,
        folder_path=folder_path,
        accionante=item.accionante,
        radicado_23_digitos=item.rad23,
        juzgado=primary_case.juzgado,
        ciudad=primary_case.ciudad,
        estado="ACTIVO",
        tipo_actuacion="TUTELA",
        origen="TUTELA",
        processing_status="PENDIENTE",
        observaciones=(
            f"[ACUMULACIÓN] Caso creado automáticamente al detectar acumulación "
            f"con el RECTOR #{primary_case.id}. Los documentos residen en la carpeta "
            f"del rector (expediente conjunto)."
        ),
    )
    db.add(case)
    db.flush()
    db.add(AuditLog(
        case_id=case.id, action="CREAR", source="acumulacion_resolver",
        new_value=f"Hermano de acumulación creado (rad {item.rad_corto}, "
                  f"accionante {item.accionante or '?'})",
    ))
    return case


def apply_plan(db: Session, plan: AcumPlan, primary_case: Case,
               move_files: bool = False) -> dict:
    """Aplica el plan: crea hermanos, vincula RECTOR/ACUMULADO, enruta docs."""
    summary = {"created": [], "linked": [], "routed": []}
    if not plan.is_acumulacion:
        return summary

    # 1) Garantizar caso por radicado + resolver rector_id
    # Guard anti-fantasma: NO crear un hermano ACUMULADO si ningún doc se rutea a su
    # rad (miembro enumerado sin señal documental propia → caso vacío como el c503).
    # El RECTOR siempre se materializa (lleva los docs conjunto). Ver
    # feedback_acumulacion_bucket_sucio.
    routed_rads = {r.to_rad for r in plan.doc_routes}
    rector_id = None
    for it in plan.items:
        if it.action == "CREATE" and it.case_id is None:
            if it.role != "RECTOR" and it.rad_corto not in routed_rads:
                summary.setdefault("skipped", []).append(
                    {"rad": it.rad_corto, "accionante": it.accionante,
                     "motivo": "sin docs ruteados (evita hermano vacío)"})
                logger.info(
                    "Acumulación: NO creo hermano %s (%s) — ningún doc se rutea a él",
                    it.rad_corto, it.accionante,
                )
                continue
            c = _create_sibling(db, it, primary_case, create_folder=move_files)
            it.case_id = c.id
            summary["created"].append({"case_id": c.id, "rad": it.rad_corto,
                                       "accionante": it.accionante})
        if it.role == "RECTOR":
            rector_id = it.case_id

    # 2) Registrar vínculos (idempotente) + backfill de huecos seguros
    for it in plan.items:
        if it.case_id is None:
            continue  # hermano saltado por el guard anti-fantasma (sin docs)
        c = db.get(Case, it.case_id)
        if not c:
            continue
        # Backfill solo de campos VACÍOS (nunca pisa datos curados)
        if not c.radicado_23_digitos and it.rad23:
            c.radicado_23_digitos = it.rad23
        if not c.accionante and it.accionante:
            c.accionante = it.accionante
        new_acum = None if it.role == "RECTOR" else rector_id
        if (c.tipo_acumulacion == it.role and c.acumulado_a_case_id == new_acum):
            continue
        c.tipo_acumulacion = it.role
        c.acumulado_a_case_id = new_acum
        if plan.auto_doc_id:
            c.acumulacion_auto_doc_id = plan.auto_doc_id
        if plan.fecha:
            c.acumulacion_fecha = plan.fecha
        summary["linked"].append({"case_id": c.id, "role": it.role,
                                   "acumulado_a": new_acum})

    # 3) Enrutar docs individuales a su hermano
    for r in plan.doc_routes:
        if not r.to_case_id:
            # el item destino pudo crearse recién; re-resolver
            it = next((x for x in plan.items if x.rad_corto == r.to_rad), None)
            r.to_case_id = it.case_id if it else None
        if not r.to_case_id:
            continue
        doc = db.get(Document, r.doc_id)
        if not doc or doc.case_id == r.to_case_id:
            continue
        old = doc.case_id
        doc.case_id = r.to_case_id
        if move_files:
            _move_doc_file(db, doc, r.to_case_id)
        db.add(AuditLog(
            case_id=r.to_case_id, action="REASIGNAR_DOC", source="acumulacion_resolver",
            old_value=f"case {old}", new_value=f"doc {doc.id} '{r.filename}' → case {r.to_case_id}",
        ))
        summary["routed"].append({"doc_id": doc.id, "from": old, "to": r.to_case_id,
                                  "filename": r.filename})

    # 4) Nota "[ACUMULACIÓN CONJUNTA]" en observaciones de cada miembro (idempotente)
    member_ids = {it.case_id for it in plan.items if it.case_id}
    for cid in member_ids:
        c = db.get(Case, cid)
        if c is not None:
            apply_acumulacion_note(db, c)

    db.commit()
    return summary


_NOTE_MARKER = "[ACUMULACIÓN CONJUNTA]"


def build_acumulacion_note(db: Session, case: Case) -> str:
    """Construye la línea estándar de observaciones que declara la acumulación.

    Lista todos los miembros (rector + acumulados) con su accionante. Se basa en
    los campos tipo_acumulacion/acumulado_a_case_id, así que funciona se invoque
    desde el rector o desde un hijo.
    """
    rector_id = (case.acumulado_a_case_id
                 if case.tipo_acumulacion == "ACUMULADO" and case.acumulado_a_case_id
                 else case.id)
    rector = db.get(Case, rector_id) or case
    miembros = [rector] + (
        db.query(Case)
        .filter(Case.acumulado_a_case_id == rector_id)
        .order_by(Case.id)
        .all()
    )
    partes = []
    for m in miembros:
        rc = derive_rad_corto_from_rad23(m.radicado_23_digitos) or (
            (m.folder_name or "").split(" ")[0])
        tag = " (RECTOR)" if m.id == rector_id else ""
        partes.append(f"{rc} {(m.accionante or '?')}{tag} [#{m.id}]")
    return (f"{_NOTE_MARKER} Este expediente está acumulado (trámite conjunto) con: "
            + " · ".join(partes) + ".")


def apply_acumulacion_note(db: Session, case: Case) -> bool:
    """Pone/actualiza la nota de acumulación al inicio de observaciones, sin pisar
    el resto del texto. Idempotente (reemplaza la línea marcada si ya existe).
    Devuelve True si cambió algo."""
    if case.tipo_acumulacion not in ("RECTOR", "ACUMULADO"):
        return False
    note = build_acumulacion_note(db, case)
    obs = case.observaciones or ""
    # quitar cualquier línea previa con el marcador
    lines = [ln for ln in obs.splitlines() if not ln.lstrip().startswith(_NOTE_MARKER)]
    rest = "\n".join(lines).strip()
    new_obs = (note + ("\n\n" + rest if rest else "")).strip()
    if new_obs != obs:
        case.observaciones = new_obs
        return True
    return False


def _move_doc_file(db: Session, doc: Document, to_case_id: int) -> None:
    """Mueve el archivo físico a la carpeta del caso destino (si tiene carpeta)."""
    import shutil
    from pathlib import Path
    to_case = db.get(Case, to_case_id)
    if not (to_case and to_case.folder_path and doc.file_path):
        return
    src = Path(doc.file_path)
    if not src.exists():
        return
    dst_dir = Path(to_case.folder_path)
    dst_dir.mkdir(parents=True, exist_ok=True)
    dst = dst_dir / src.name
    if dst.resolve() == src.resolve():
        return
    try:
        shutil.move(str(src), str(dst))
        doc.file_path = str(dst)
    except Exception as e:
        logger.warning("No se pudo mover %s → %s: %s", src, dst, e)


def resolve_acumulacion(db: Session, primary_case: Case, apply: bool = False,
                        move_files: bool = False) -> AcumPlan:
    """Punto de entrada para la ingesta. Devuelve el plan; aplica si apply=True."""
    plan = plan_acumulacion(db, primary_case)
    if apply and plan.is_acumulacion:
        plan._summary = apply_plan(db, plan, primary_case, move_files=move_files)  # type: ignore[attr-defined]
    return plan
