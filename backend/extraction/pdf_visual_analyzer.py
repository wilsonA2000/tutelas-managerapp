"""Analizador visual de PDFs — detección determinista de imágenes, sellos y watermarks.

Sin IA: solo fitz (PyMuPDF) para inventario visual + pHash perceptual para fingerprint
+ heurística de forma/posición para clasificar. Aporta señales de confiabilidad
institucional al regex/forensic del pipeline.

Señales que produce:
- imagenes_count: cuántas imágenes embebidas tiene el PDF
- logos_institucionales: fingerprints que se repiten en headers (probable membrete)
- sellos_posibles: imágenes pequeñas cuadradas/circulares en esquinas o tras firmas
- watermarks: texto rotado/transparente o imágenes grandes de bajo contraste
- anotaciones: stamps, highlights, firmas digitales registradas como annotations
- texto_rotado: fragmentos con rotación ≠ 0 (suelen ser sellos de radicación)
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger("tutelas.pdf_visual")


@dataclass
class VisualFinding:
    """Un hallazgo visual en una página."""
    kind: str                         # logo | sello | watermark | firma | stamp | texto_rotado
    page: int
    bbox: tuple[float, float, float, float] = (0, 0, 0, 0)
    phash: str = ""                   # fingerprint perceptual (hex)
    width: float = 0.0
    height: float = 0.0
    rotation: float = 0.0
    extra: dict = field(default_factory=dict)


@dataclass
class PDFVisualReport:
    """Resumen visual de un PDF."""
    filename: str
    page_count: int = 0
    images_count: int = 0
    annotations_count: int = 0
    findings: list[VisualFinding] = field(default_factory=list)
    institutional_score: float = 0.0  # 0-1: probabilidad de doc institucional/oficial
    repeated_logos: list[str] = field(default_factory=list)   # phashes que aparecen en ≥2 páginas
    rotated_text_snippets: list[str] = field(default_factory=list)  # p.ej. sellos de radicación


@dataclass
class VisualSignature:
    """v6.0 Capa 0: signature canónica y compacta de la percepción física del doc.

    Se deriva del PDFVisualReport pero está pensada para persistirse en DB
    y ser consultada por capas superiores (Bayesian assignment, live consolidator).
    """
    has_official_logo: bool = False      # logo repetido en ≥2 páginas (membrete)
    has_radicador_stamp: bool = False    # texto rotado compatible con sello radicación
    has_juzgado_seal: bool = False       # findings tipo 'sello'
    has_signature: bool = False          # findings tipo 'firma' o annotation 'sig'
    has_watermark: bool = False
    institutional_score: float = 0.0
    repeated_logo_phashes: list[str] = field(default_factory=list)
    rotated_snippets: list[str] = field(default_factory=list)
    images_count: int = 0
    annotations_count: int = 0
    page_count: int = 0

    def to_dict(self) -> dict:
        return {
            "has_official_logo": self.has_official_logo,
            "has_radicador_stamp": self.has_radicador_stamp,
            "has_juzgado_seal": self.has_juzgado_seal,
            "has_signature": self.has_signature,
            "has_watermark": self.has_watermark,
            "institutional_score": round(self.institutional_score, 3),
            "repeated_logo_phashes": self.repeated_logo_phashes[:10],
            "rotated_snippets": [s[:200] for s in self.rotated_snippets[:10]],
            "images_count": self.images_count,
            "annotations_count": self.annotations_count,
            "page_count": self.page_count,
        }

    @classmethod
    def from_report(cls, report: "PDFVisualReport") -> "VisualSignature":
        kinds = {f.kind for f in report.findings}
        rotated_keywords = ("radicad", "juzgado", "tribunal", "recibid", "fecha")
        has_radicador = any(
            any(kw in snip.lower() for kw in rotated_keywords)
            for snip in report.rotated_text_snippets
        )
        return cls(
            has_official_logo=bool(report.repeated_logos),
            has_radicador_stamp=has_radicador or any(f.kind == "texto_rotado" for f in report.findings),
            has_juzgado_seal="sello" in kinds,
            has_signature=("firma" in kinds) or ("stamp" in kinds),
            has_watermark="watermark" in kinds,
            institutional_score=report.institutional_score,
            repeated_logo_phashes=list(report.repeated_logos),
            rotated_snippets=list(report.rotated_text_snippets),
            images_count=report.images_count,
            annotations_count=report.annotations_count,
            page_count=report.page_count,
        )


def _phash_bytes(img_bytes: bytes, hash_size: int = 8) -> str:
    """pHash simple sobre bytes: reduce a 8x8 gris y compara con mediana.

    No usa imagehash (dependencia extra). Implementación mínima determinista.
    """
    try:
        from PIL import Image
        import io
        im = Image.open(io.BytesIO(img_bytes)).convert("L").resize(
            (hash_size, hash_size), Image.Resampling.LANCZOS
        )
        pixels = list(im.getdata())
        avg = sum(pixels) / len(pixels)
        bits = "".join("1" if p >= avg else "0" for p in pixels)
        return f"{int(bits, 2):0{hash_size*hash_size//4}x}"
    except Exception:
        return hashlib.md5(img_bytes[:4096]).hexdigest()[:16]


def _classify_image(width: float, height: float, page_width: float, page_height: float,
                    bbox: tuple, page: int) -> str:
    """Heurística determinista: clasifica una imagen según tamaño y posición."""
    x0, y0, x1, y1 = bbox
    rel_w = width / page_width if page_width else 0
    rel_h = height / page_height if page_height else 0
    area_ratio = rel_w * rel_h
    aspect = width / height if height else 1
    top_page = y1 < page_height * 0.25
    bottom_page = y0 > page_height * 0.65

    # Watermark: imagen grande (>50% de la página) y aspecto aproximadamente cuadrado o diagonal
    if area_ratio > 0.4 and 0.5 <= aspect <= 2.0:
        return "watermark"
    # Logo institucional: esquina superior, pequeño-mediano
    if top_page and area_ratio < 0.08 and 0.5 <= aspect <= 2.5:
        return "logo"
    # Sello: cuadrado o circular, pequeño, cerca del final del doc o después de firma
    if 0.8 <= aspect <= 1.25 and area_ratio < 0.06 and (bottom_page or page > 1):
        return "sello"
    # Firma manuscrita: alargada horizontal, pequeña, parte baja
    if aspect > 2.0 and area_ratio < 0.1 and bottom_page:
        return "firma"
    return "imagen"


def _detect_rotated_text(page) -> list[tuple[str, float, tuple]]:
    """Detecta bloques de texto con rotación ≠ 0. Típico de sellos de radicación."""
    rotated = []
    try:
        pdict = page.get_text("dict")
        for block in pdict.get("blocks", []):
            if block.get("type") != 0:
                continue
            for line in block.get("lines", []):
                dir_vec = line.get("dir", (1, 0))
                # Si dir no es ~(1,0), el texto está rotado
                if abs(dir_vec[1]) > 0.3 or dir_vec[0] < 0.9:
                    import math
                    angle = math.degrees(math.atan2(dir_vec[1], dir_vec[0]))
                    text = " ".join(s.get("text", "") for s in line.get("spans", []))
                    if text.strip() and abs(angle) > 5:
                        rotated.append((text.strip(), angle, line.get("bbox", (0, 0, 0, 0))))
    except Exception:
        pass
    return rotated


def analyze_pdf_visual(file_path: str) -> PDFVisualReport:
    """Analiza un PDF y devuelve reporte visual determinista.

    Tolerante a fallos: si no puede abrir o analizar, retorna reporte vacío.
    """
    path = Path(file_path)
    report = PDFVisualReport(filename=path.name)

    try:
        import fitz
    except ImportError:
        return report

    try:
        doc = fitz.open(str(path))
    except Exception as e:
        logger.debug("Visual analyzer no pudo abrir %s: %s", path.name, e)
        return report

    report.page_count = len(doc)
    phash_counter: dict[str, int] = {}

    try:
        for page_num in range(len(doc)):
            page = doc[page_num]
            page_rect = page.rect
            pw, ph = page_rect.width, page_rect.height

            # Anotaciones (stamps, highlights, firmas digitales)
            try:
                for annot in page.annots() or []:
                    report.annotations_count += 1
                    info = annot.info or {}
                    atype = (annot.type[1] if annot.type else "").lower()
                    # v5.5: solo sumamos al report si tiene metadata útil
                    if atype in ("stamp", "freetext", "sig"):
                        report.findings.append(VisualFinding(
                            kind="stamp" if atype == "stamp" else "firma",
                            page=page_num + 1,
                            bbox=tuple(annot.rect),
                            extra={"annot_type": atype, "title": info.get("title", "")[:80]},
                        ))
            except Exception:
                pass

            # Imágenes embebidas
            try:
                for img in page.get_images(full=True):
                    xref = img[0]
                    report.images_count += 1
                    try:
                        img_rects = page.get_image_rects(xref)
                    except Exception:
                        img_rects = []
                    if not img_rects:
                        continue
                    rect = img_rects[0]
                    w, h = rect.width, rect.height
                    if w < 10 or h < 10:
                        continue  # miniaturas sin valor
                    # pHash del contenido
                    try:
                        img_data = doc.extract_image(xref)
                        img_bytes = img_data.get("image", b"") if img_data else b""
                    except Exception:
                        img_bytes = b""
                    phash = _phash_bytes(img_bytes) if img_bytes else ""
                    if phash:
                        phash_counter[phash] = phash_counter.get(phash, 0) + 1
                    kind = _classify_image(w, h, pw, ph, tuple(rect), page_num + 1)
                    report.findings.append(VisualFinding(
                        kind=kind,
                        page=page_num + 1,
                        bbox=tuple(rect),
                        phash=phash,
                        width=w, height=h,
                    ))
            except Exception as e:
                logger.debug("get_images falló en %s p%d: %s", path.name, page_num, e)

            # Texto rotado (sellos de radicación)
            for text, angle, bbox in _detect_rotated_text(page):
                report.findings.append(VisualFinding(
                    kind="texto_rotado", page=page_num + 1,
                    bbox=bbox, rotation=angle,
                    extra={"text": text[:200]},
                ))
                report.rotated_text_snippets.append(text)
    finally:
        doc.close()

    # Logos institucionales: phashes que aparecen en 2+ páginas (header repetido)
    report.repeated_logos = [p for p, n in phash_counter.items() if n >= 2]

    # Score institucional heurístico determinista
    score = 0.0
    if report.repeated_logos:
        score += 0.35  # logo/membrete repetido
    if any(f.kind == "sello" for f in report.findings):
        score += 0.25
    if any(f.kind == "firma" or f.kind == "stamp" for f in report.findings):
        score += 0.15
    if report.rotated_text_snippets:
        score += 0.15  # sello de radicación rotado
    if report.annotations_count > 0:
        score += 0.10
    report.institutional_score = min(score, 1.0)

    return report


def report_to_zone_metadata(report: PDFVisualReport) -> dict:
    """Convierte el reporte visual en metadata compacta para zona IR."""
    return {
        "pages": report.page_count,
        "images": report.images_count,
        "annotations": report.annotations_count,
        "repeated_logos": len(report.repeated_logos),
        "sellos": sum(1 for f in report.findings if f.kind == "sello"),
        "firmas": sum(1 for f in report.findings if f.kind in ("firma", "stamp")),
        "watermarks": sum(1 for f in report.findings if f.kind == "watermark"),
        "texto_rotado": sum(1 for f in report.findings if f.kind == "texto_rotado"),
        "institutional_score": round(report.institutional_score, 2),
        "rotated_snippets": [s[:120] for s in report.rotated_text_snippets[:5]],
    }
