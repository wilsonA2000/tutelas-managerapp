"""KB en memoria de casos para lookup O(1) desde el monitor Gmail (v5.4.4).

Problema que resuelve:
    `match_to_case` del monitor hace 7 queries SQL por cada email que llega.
    Con 500 emails in:unread, son 3500 queries. Además el matching es secuencial:
    el primer `.first()` que coincida gana, sin verificar alternativas.

Solución:
    Construir al startup 4 diccionarios en memoria:
        - by_rad23[digitos_21] → case_id (rad-21 = despacho+año+consec, sin cuadernillo)
        - by_rad_corto["AAAA-NNNNN"] → case_id
        - by_forest → case_id
        - by_cc_hash[sha256(cc)] → case_id (vía pii_mappings)

    Cada email hace lookup O(1) en los 4 dicts y el matcher decide por score.

Invalidación:
    refresh_one(case_id) al crear/mergear casos. Thread-safe con RLock.
    build() al startup (main.py lifespan).
    Stamp file `data/case_cache.stamp` con timestamp — si DB se modifica
    externamente (CLI, script), próximo boot reconstruye cache.

Bug histórico (corregido 2026-05-15): la versión anterior usaba `[:20]` como
key, colapsando rads consecutivos que diferían en el último dígito del consec
(p.ej. 2026-00011 y 2026-00012 quedaban en el mismo bucket). El monitor de
Gmail trataba ambos cases como uno solo → conflación de paquetes. Ver
`scripts/move_misplaced_doc.py` para limpiar el daño histórico que generó.
"""

from __future__ import annotations

import hashlib
import logging
import re
import threading
from pathlib import Path
from typing import TYPE_CHECKING

from backend.email.rad_utils import (
    derive_rad_corto_from_rad23,
    juzgado_code,
    normalize_rad23,
)

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


logger = logging.getLogger("tutelas.case_cache")

_CC_REGEX = re.compile(r"\b\d{6,10}\b")


def hash_cc(cc: str) -> str:
    """SHA256 de cédula normalizada (solo dígitos). Permite lookup sin guardar PII en claro."""
    digits = re.sub(r"\D", "", cc or "")
    if not digits:
        return ""
    return hashlib.sha256(digits.encode()).hexdigest()


class CaseLookupCache:
    """Diccionarios en memoria para lookup O(1) de casos.

    Usage:
        cache = CaseLookupCache()
        cache.build(db)
        case_id = cache.by_rad23.get("54001410500220261002100")
    """

    def __init__(self):
        self.by_rad23: dict[str, int] = {}
        self.by_rad_corto: dict[str, int] = {}
        # TODOS los casos que comparten un rad_corto (no globalmente único: cada
        # juzgado lleva su propia secuencia AAAA-NNNNN). Permite detectar ambigüedad
        # y desambiguar por municipio antes de asignar. Ver matcher.score_case_match.
        self.by_rad_corto_all: dict[str, set[int]] = {}
        # juzgado_code (primeros 12 díg del rad23 = depto+muni+entidad+espec+subesp)
        # por caso. Discrimina municipio (68001 Bucaramanga vs 68500 Oiba vs 68092 Betulia).
        self.juzgado12: dict[int, str] = {}
        self.by_forest: dict[str, int] = {}
        self.by_cc_hash: dict[str, int] = {}
        self._lock = threading.RLock()
        self._built = False

    # ─────────────────────────────────────────────────────────
    # Build / refresh
    # ─────────────────────────────────────────────────────────

    def build(self, db: "Session") -> dict:
        """Reconstruye todos los dicts desde la DB. Llamar al startup."""
        from backend.database.models import Case  # import lazy

        with self._lock:
            self.by_rad23.clear()
            self.by_rad_corto.clear()
            self.by_rad_corto_all.clear()
            self.juzgado12.clear()
            self.by_forest.clear()
            self.by_cc_hash.clear()  # (vestigial) la capa PII se retiró — este dict queda vacío

            cases = db.query(Case).filter(
                Case.processing_status != "DUPLICATE_MERGED"
            ).all()

            for c in cases:
                self._index_case_no_lock(c)

            self._built = True
            stats = {
                "cases_indexed": len(cases),
                "rad23": len(self.by_rad23),
                "rad_corto": len(self.by_rad_corto),
                "forest": len(self.by_forest),
                "cc_hash": len(self.by_cc_hash),
            }
            logger.info("CaseLookupCache built: %s", stats)
            _write_stamp()
            return stats

    def refresh_one(self, db: "Session", case_id: int) -> None:
        """Re-indexa un caso (llamar después de create/merge)."""
        from backend.database.models import Case

        case = db.query(Case).filter(Case.id == case_id).first()
        if not case:
            # Caso fue eliminado — quitar entradas stale
            self._evict_case_no_lock(case_id)
            return

        with self._lock:
            self._evict_case_no_lock(case_id)
            if case.processing_status != "DUPLICATE_MERGED":
                self._index_case_no_lock(case)

    def _index_case_no_lock(self, c) -> None:
        """Añade un caso a todos los dicts relevantes (debe ser llamado bajo lock)."""
        # rad23: key = primeros 21 dígitos normalizados (rad-21 = despacho+año+consec,
        # sin los 2 del cuadernillo). El cuadernillo (00 / 01 / 02…) distingue piezas
        # del mismo expediente, no expedientes distintos — colapsarlas al mismo bucket
        # es lo deseado. Usar `[:20]` era un bug histórico que colapsaba consecutivos
        # contiguos (00011 ↔ 00012).
        # juzgado_code (municipio+despacho) para desambiguar rad_corto compartido
        jc = juzgado_code(c.radicado_23_digitos) if c.radicado_23_digitos else ""
        if jc:
            self.juzgado12[c.id] = jc

        if c.radicado_23_digitos:
            norm = normalize_rad23(c.radicado_23_digitos)
            if len(norm) >= 21:
                self.by_rad23[norm[:21]] = c.id
                # rad_corto derivado del rad23 (fuente autoritativa)
                derived = derive_rad_corto_from_rad23(c.radicado_23_digitos)
                if derived:
                    self.by_rad_corto[derived] = c.id
                    self.by_rad_corto_all.setdefault(derived, set()).add(c.id)

        # rad_corto del folder_name (si difiere del derivado, se añade también)
        if c.folder_name:
            m = re.match(r"(20\d{2})-0*(\d{1,6})", c.folder_name)
            if m:
                folder_corto = f"{m.group(1)}-{m.group(2).zfill(5)}"
                # No sobrescribir si ya hay uno derivado del rad23
                self.by_rad_corto.setdefault(folder_corto, c.id)
                self.by_rad_corto_all.setdefault(folder_corto, set()).add(c.id)

        # forest
        if c.radicado_forest:
            self.by_forest[c.radicado_forest] = c.id

    def _evict_case_no_lock(self, case_id: int) -> None:
        """Remueve todas las entradas que apuntan a este case_id."""
        for d in (self.by_rad23, self.by_rad_corto, self.by_forest, self.by_cc_hash):
            stale_keys = [k for k, v in d.items() if v == case_id]
            for k in stale_keys:
                d.pop(k, None)
        # by_rad_corto_all: quitar el case_id de cada set; borrar la clave si queda vacía
        empty = []
        for k, ids in self.by_rad_corto_all.items():
            ids.discard(case_id)
            if not ids:
                empty.append(k)
        for k in empty:
            self.by_rad_corto_all.pop(k, None)
        self.juzgado12.pop(case_id, None)

    # ─────────────────────────────────────────────────────────
    # Lookup
    # ─────────────────────────────────────────────────────────

    def lookup_by_rad23(self, rad23: str | None) -> int | None:
        """Lookup por rad-21 (despacho+año+consec). Requiere ≥21 dígitos.

        Si el rad llega más corto (truncado en email), no se busca aquí —
        el caller debe usar lookup_by_rad_corto o cascada de matchers.
        """
        if not rad23:
            return None
        norm = normalize_rad23(rad23)
        if len(norm) < 21:
            return None
        return self.by_rad23.get(norm[:21])

    def lookup_by_rad_corto(self, rad_corto: str | None) -> int | None:
        if not rad_corto:
            return None
        return self.by_rad_corto.get(rad_corto)

    def rad_corto_candidates(self, rad_corto: str | None) -> set[int]:
        """TODOS los casos que comparten este rad_corto (puede haber varios de
        municipios distintos: el rad_corto NO es globalmente único)."""
        if not rad_corto:
            return set()
        return set(self.by_rad_corto_all.get(rad_corto, set()))

    def juzgado_of(self, case_id: int) -> str:
        """juzgado_code (primeros 12 díg del rad23) del caso, o '' si no se conoce."""
        return self.juzgado12.get(case_id, "")

    def lookup_by_forest(self, forest: str | None) -> int | None:
        if not forest:
            return None
        return self.by_forest.get(forest)

    def lookup_by_cc(self, cc: str | None) -> int | None:
        if not cc:
            return None
        return self.by_cc_hash.get(hash_cc(cc))

    def lookup_all(
        self,
        rad23: str | None = None,
        rad_corto: str | None = None,
        forest: str | None = None,
        cc: str | None = None,
    ) -> dict[str, int]:
        """Lookup simultáneo en los 4 dicts. Retorna dict de hits."""
        hits = {}
        if r := self.lookup_by_rad23(rad23):
            hits["rad23"] = r
        if r := self.lookup_by_rad_corto(rad_corto):
            hits["rad_corto"] = r
        if r := self.lookup_by_forest(forest):
            hits["forest"] = r
        if r := self.lookup_by_cc(cc):
            hits["cc"] = r
        return hits

    @property
    def is_built(self) -> bool:
        return self._built

    def size(self) -> dict[str, int]:
        return {
            "rad23": len(self.by_rad23),
            "rad_corto": len(self.by_rad_corto),
            "forest": len(self.by_forest),
            "cc_hash": len(self.by_cc_hash),
        }


# ─────────────────────────────────────────────────────────
# Singleton global
# ─────────────────────────────────────────────────────────

_CACHE_INSTANCE: CaseLookupCache | None = None


def get_cache() -> CaseLookupCache:
    """Acceso al singleton. Construido perezosamente si no existe."""
    global _CACHE_INSTANCE
    if _CACHE_INSTANCE is None:
        _CACHE_INSTANCE = CaseLookupCache()
    return _CACHE_INSTANCE


# ─────────────────────────────────────────────────────────
# Stamp file
# ─────────────────────────────────────────────────────────

def _stamp_path() -> Path:
    from backend.core.settings import settings
    return settings.app_dir / "data" / "case_cache.stamp"


def _write_stamp() -> None:
    import time
    try:
        _stamp_path().write_text(str(int(time.time())))
    except Exception:
        pass
