"""Script para poblar el campo accionante en casos que no lo tienen.

Grupo 1: Extraer del folder_name (casos que ya tienen nombre en la carpeta)
Grupo 2: Leer PDFs (auto admisorio) para identificar accionante
Grupo 3: Corregir radicados claramente mal extraídos (ej: 2040-00089)

PRINCIPIOS:
- NO borrar un accionante existente si no se encontró uno mejor
- NO renombrar carpetas a menos que estemos seguros del nuevo nombre
- Accionantes institucionales son válidos (personeros, defensorias, sindicatos)
- Solo modo dry-run para Grupo 3 (radicados sospechosos) — no renombrar automáticamente
"""

import sqlite3
import re
import os
from pathlib import Path

BASE_DIR = Path(r"/mnt/c/Users/wilso/Documents/GOBERNACION DE SANTANDER/TUTELAS 2026")
DB_PATH = BASE_DIR / "tutelas-app" / "data" / "tutelas.db"

conn = sqlite3.connect(str(DB_PATH))
conn.row_factory = sqlite3.Row
cur = conn.cursor()

# Palabras que son PURAMENTE texto jurídico/procesal (no identifican a nadie)
PURE_JURIDICAL = {
    "remito", "oficio", "segunda", "instancia", "adelantar", "traslado",
    "contestación", "contestacion", "control", "acciones", "clasificar",
    "corre", "escrito", "notificación", "notificacion", "auto", "avoca",
    "tutela", "sentencia", "fallo", "respuesta", "acción", "accion",
    "admisorio", "admite", "admision", "requerimiento", "incidente",
    "nombramiento", "urgente", "vinculacion", "apertura", "previo",
    "pruebas", "decreta", "notifico", "remision", "contestacion",
    "las", "del", "por", "para", "los", "con", "que", "rad", "rdo",
    "sin", "emails", "sede",
}

# Palabras institucionales que SÍ identifican al accionante (personeros, etc.)
# Estas NO se rechazan
INSTITUTIONAL_OK = {
    "personero", "personera", "personería", "personeria",
    "comisaria", "comisaría", "defensor", "defensora", "defensoría",
    "sindicato", "alcaldía", "alcaldia", "municipio",
}


def is_pure_juridical(text):
    """True si el texto es SOLO jerga procesal sin identificar a nadie.
    False si contiene nombres de personas o instituciones que identifican al accionante.
    """
    if not text or len(text.strip()) < 3:
        return True
    words = re.findall(r"[a-záéíóúñ]+", text.lower())
    if not words:
        return True
    # Si contiene palabras institucionales, NO es puro jurídico
    if any(w in INSTITUTIONAL_OK for w in words):
        return False
    # Si TODAS las palabras son jurídicas o muy cortas, es puro jurídico
    non_jur = [w for w in words if w not in PURE_JURIDICAL and len(w) > 2]
    return len(non_jur) < 2


def extract_name_from_folder(folder_name):
    """Extraer nombre/identificación del accionante del folder_name.
    Acepta tanto nombres de personas como instituciones (personeros, sindicatos, etc.)
    """
    if not folder_name:
        return None
    # Quitar el radicado del inicio
    m = re.match(r"20\d{2}[-\s]?\d+(?:[-\s]\d+)*\s+(.+)", folder_name)
    if m:
        name = m.group(1).strip()
        # Limpiar saltos de línea
        name = re.sub(r"[\n\r]+", " ", name)
        name = re.sub(r"\s+", " ", name).strip()
        if not is_pure_juridical(name):
            return name.upper()
    return None


def extract_accionante_from_pdf(file_path):
    """Leer un PDF y buscar el nombre del accionante."""
    try:
        import pdfplumber
    except ImportError:
        print("  ERROR: pdfplumber no instalado")
        return None

    try:
        with pdfplumber.open(file_path) as pdf:
            text = ""
            for page in pdf.pages[:3]:
                page_text = page.extract_text() or ""
                text += page_text + "\n"

            if not text.strip():
                return None

            # Patron 1: "ACCIONANTE: NOMBRE" (el más confiable)
            match = re.search(
                r"(?i)accionante[:\s]+([A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑa-záéíóúñ\s]{5,80}?)(?:\n|,|\.|ACCIONAD|CONTRA|DEMANDAD)",
                text
            )
            if match:
                name = re.sub(r"\s+", " ", match.group(1).strip())
                if not is_pure_juridical(name):
                    return name.upper()

            # Patron 2: "interpuesta por [señor/señora] NOMBRE"
            match = re.search(
                r"(?i)(?:interpuesta|instaurada|presentada|promovida)\s+por\s+(?:el señor |la señora |el ciudadano |la ciudadana )?([A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑa-záéíóúñ\s]{5,80}?)(?:\n|,|\.|contra|en\s+contra|identificad)",
                text
            )
            if match:
                name = re.sub(r"\s+", " ", match.group(1).strip())
                if not is_pure_juridical(name):
                    return name.upper()

            # Patron 3: "DEMANDANTE: NOMBRE"
            match = re.search(
                r"(?i)demandante[:\s]+([A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑa-záéíóúñ\s]{5,80}?)(?:\n|,|\.|DEMANDAD|CONTRA)",
                text
            )
            if match:
                name = re.sub(r"\s+", " ", match.group(1).strip())
                if not is_pure_juridical(name):
                    return name.upper()

            # Patron 4: "señor/señora NOMBRE ... identificado(a)"
            match = re.search(
                r"(?i)(?:señora?|sr\.?a?)\s+([A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑa-záéíóúñ\s]{5,60}?)(?:,|\.|identificad|con\s+c[eé]dula|c\.?\s*c)",
                text
            )
            if match:
                name = re.sub(r"\s+", " ", match.group(1).strip())
                if not is_pure_juridical(name):
                    return name.upper()

            # Patron 5: Buscar en Ref/Referencia
            match = re.search(
                r"(?i)(?:ref(?:erencia)?\.?|asunto)[:\s]+.*?(?:accionante|interpuesta\s+por|señor|señora)[:\s]*([A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑa-záéíóúñ\s]{5,80}?)(?:\n|,|\.)",
                text
            )
            if match:
                name = re.sub(r"\s+", " ", match.group(1).strip())
                if not is_pure_juridical(name):
                    return name.upper()

    except Exception as e:
        print(f"  Error leyendo PDF {file_path}: {e}")

    return None


def safe_rename_folder(case_id, old_path, new_name):
    """Renombrar carpeta de forma segura, actualizando DB y paths de documentos."""
    old_path = Path(old_path)
    new_path = BASE_DIR / new_name

    if new_path.exists():
        return False, f"destino ya existe: {new_name[:50]}"
    if not old_path.exists():
        return False, "carpeta origen no existe"

    try:
        old_path.rename(new_path)
    except Exception as e:
        return False, f"error: {e}"

    cur.execute(
        "UPDATE cases SET folder_name = ?, folder_path = ? WHERE id = ?",
        (new_name, str(new_path), case_id)
    )
    # Actualizar paths de documentos
    docs = cur.execute("SELECT id, file_path FROM documents WHERE case_id = ?", (case_id,)).fetchall()
    for doc in docs:
        old_fp = doc["file_path"]
        if old_fp and str(old_path) in old_fp:
            new_fp = old_fp.replace(str(old_path), str(new_path))
            cur.execute("UPDATE documents SET file_path = ? WHERE id = ?", (new_fp, doc["id"]))

    return True, "OK"


# ============================================================
# GRUPO 1: Extraer accionante del folder_name
# ============================================================
print("=" * 70)
print("GRUPO 1: Extraer accionante del folder_name")
print("=" * 70)

cases_sin_acc = cur.execute('''
    SELECT id, folder_name, folder_path, accionante
    FROM cases
    WHERE folder_path IS NOT NULL AND folder_path != ''
    AND (accionante IS NULL OR accionante = '' OR accionante = 'None')
''').fetchall()

grupo1_fixed = 0
grupo2_pending = []

for c in cases_sin_acc:
    c = dict(c)
    name = extract_name_from_folder(c["folder_name"])
    if name:
        cur.execute("UPDATE cases SET accionante = ? WHERE id = ?", (name, c["id"]))
        grupo1_fixed += 1
        print(f"  ID {c['id']:3d}: '{c['folder_name'][:50]}' -> accionante='{name}'")
    else:
        grupo2_pending.append(c)

# Identificar casos con accionante puramente jurídico (NO borrar, solo marcar para Grupo 2)
cases_con_acc = cur.execute('''
    SELECT id, folder_name, folder_path, accionante
    FROM cases
    WHERE folder_path IS NOT NULL AND folder_path != ''
    AND accionante IS NOT NULL AND accionante != '' AND accionante != 'None'
''').fetchall()

juridicos_para_grupo2 = []
for c in cases_con_acc:
    c = dict(c)
    if is_pure_juridical(c["accionante"]):
        juridicos_para_grupo2.append(c)

conn.commit()
print(f"\nGrupo 1: {grupo1_fixed} accionantes extraidos del folder_name")
print(f"Pendientes para Grupo 2: {len(grupo2_pending)} sin accionante + {len(juridicos_para_grupo2)} con texto jurídico")


# ============================================================
# GRUPO 2: Leer PDFs para extraer accionante
# ============================================================
print("\n" + "=" * 70)
print("GRUPO 2: Leer PDFs para extraer accionante")
print("=" * 70)

# Combinar: sin accionante + con texto jurídico
all_pending = grupo2_pending + juridicos_para_grupo2
grupo2_fixed = 0
grupo2_failed = []

for c in all_pending:
    folder_path = Path(c["folder_path"])
    if not folder_path.exists():
        grupo2_failed.append((c, "carpeta no existe"))
        continue

    # Buscar PDFs
    pdfs = sorted(folder_path.glob("*.pdf")) + sorted(folder_path.glob("*.PDF"))
    if not pdfs:
        grupo2_failed.append((c, "sin PDFs"))
        continue

    # Priorizar auto admisorio
    priority_pdfs = []
    other_pdfs = []
    for pdf in pdfs:
        name_lower = pdf.name.lower()
        if any(kw in name_lower for kw in ["auto", "admite", "admisorio", "avoca", "escrito"]):
            priority_pdfs.append(pdf)
        else:
            other_pdfs.append(pdf)

    ordered_pdfs = priority_pdfs + other_pdfs

    accionante = None
    for pdf in ordered_pdfs[:5]:
        accionante = extract_accionante_from_pdf(str(pdf))
        if accionante:
            break

    if accionante:
        old_acc = c.get("accionante") or ""
        cur.execute("UPDATE cases SET accionante = ? WHERE id = ?", (accionante, c["id"]))
        grupo2_fixed += 1

        # Renombrar carpeta SOLO si el folder_name actual no tiene nombre real
        old_name = c["folder_name"]
        current_folder_name_part = extract_name_from_folder(old_name)

        if not current_folder_name_part:
            # El folder_name actual no tiene nombre real -> renombrar
            m = re.match(r"(20\d{2}[-\s]?\d+(?:[-\s]\d+)?)", old_name or "")
            if m:
                rad_part = m.group(1).strip()
                # Normalizar solo si es formato simple
                rm = re.match(r"(20\d{2})[-\s]?0*(\d+)$", rad_part)
                if rm:
                    rad_part = f"{rm.group(1)}-{rm.group(2).zfill(5)}"

                new_name = f"{rad_part} {accionante}"
                new_name = re.sub(r'[<>:"/\\|?*\n\r]', '', new_name)
                new_name = re.sub(r"\s+", " ", new_name).strip()

                if new_name != old_name:
                    ok, msg = safe_rename_folder(c["id"], c["folder_path"], new_name)
                    if ok:
                        print(f"  ID {c['id']:3d}: PDF -> '{accionante[:30]}' | Renombrada -> {new_name[:55]}")
                    else:
                        print(f"  ID {c['id']:3d}: PDF -> '{accionante[:30]}' | No renombrada: {msg}")
                else:
                    print(f"  ID {c['id']:3d}: PDF -> '{accionante[:30]}'")
            else:
                print(f"  ID {c['id']:3d}: PDF -> '{accionante[:30]}'")
        else:
            # Ya tiene nombre en carpeta, solo actualizar accionante en DB
            if old_acc and not is_pure_juridical(old_acc):
                print(f"  ID {c['id']:3d}: PDF -> '{accionante[:30]}' (reemplaza '{old_acc[:20]}')")
            else:
                print(f"  ID {c['id']:3d}: PDF -> '{accionante[:30]}'")
    else:
        grupo2_failed.append((c, "no se encontró accionante en PDFs"))

conn.commit()
print(f"\nGrupo 2: {grupo2_fixed} accionantes extraidos de PDFs")
print(f"No resueltos: {len(grupo2_failed)}")

if grupo2_failed:
    print("\nCasos sin resolver (requieren revisión manual):")
    for c, reason in grupo2_failed:
        acc = c.get("accionante") or "NULL"
        print(f"  ID {c['id']:3d}: {c['folder_name'][:55]} | acc='{acc[:20]}' | {reason}")


# ============================================================
# GRUPO 3: Identificar radicados sospechosos (SOLO REPORTE, NO RENOMBRAR)
# ============================================================
print("\n" + "=" * 70)
print("GRUPO 3: Radicados sospechosos (solo reporte)")
print("=" * 70)

all_cases = cur.execute('''
    SELECT id, folder_name, folder_path, accionante
    FROM cases WHERE folder_path IS NOT NULL AND folder_path != ''
''').fetchall()

sospechosos = []
for c in all_cases:
    c = dict(c)
    m = re.match(r"(20\d{2})-(\d+)", c["folder_name"] or "")
    if not m:
        continue
    year = int(m.group(1))
    num = int(m.group(2))
    if year == 2040 or num > 30000:
        sospechosos.append(c)

if sospechosos:
    print(f"Encontrados {len(sospechosos)} radicados sospechosos:")
    for c in sospechosos:
        print(f"  ID {c['id']:3d}: {c['folder_name'][:55]} | acc='{(c['accionante'] or 'NULL')[:25]}'")
    print("\nEstos requieren revisión manual — no se renombraron automáticamente.")
else:
    print("No se encontraron radicados sospechosos.")


# ============================================================
# ESTADISTICAS FINALES
# ============================================================
print("\n" + "=" * 70)
print("ESTADISTICAS FINALES")
print("=" * 70)

total = cur.execute("SELECT COUNT(*) FROM cases").fetchone()[0]
con_acc = cur.execute("SELECT COUNT(*) FROM cases WHERE accionante IS NOT NULL AND accionante != '' AND accionante != 'None'").fetchone()[0]
sin_acc = total - con_acc
con_folder = cur.execute("SELECT COUNT(*) FROM cases WHERE folder_path IS NOT NULL AND folder_path != ''").fetchone()[0]

print(f"  Total casos: {total}")
print(f"  Con accionante: {con_acc} ({con_acc*100//total}%)")
print(f"  Sin accionante: {sin_acc}")
print(f"  Con carpeta: {con_folder}")

conn.close()
print("\nScript completado.")
