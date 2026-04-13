"""Script de limpieza: deduplicar DB + limpiar carpetas mal nombradas por Gmail.

Backup creado en: data/tutelas_backup_20260324.db

Problemas a resolver:
1. 118 casos del CSV (IDs 1-118) duplican ~82 carpetas existentes (IDs 119-308)
2. 75 casos creados por Gmail monitor con carpetas mal nombradas
3. 56 carpetas fisicas con radicado largo + texto juridico como nombre
"""

import sqlite3
import os
import re
import shutil
from pathlib import Path

BASE_DIR = Path(r"/mnt/c/Users/wilso/Documents/GOBERNACION DE SANTANDER/TUTELAS 2026")
DB_PATH = BASE_DIR / "tutelas-app" / "data" / "tutelas.db"

conn = sqlite3.connect(str(DB_PATH))
conn.row_factory = sqlite3.Row
cur = conn.cursor()


# ============================================================
# UTILIDADES
# ============================================================

def normalize_radicado(text):
    """Quitar guiones, espacios, puntos para comparar radicados."""
    if not text:
        return None
    return re.sub(r"[\s\-\.]", "", text)


def extract_short_radicado(text):
    """Extraer radicado abreviado: 2026-NNNNN."""
    if not text:
        return None
    # Buscar patron año-numero en cualquier formato
    m = re.search(r"(20\d{2})[-\s.]?0*(\d{1,5})", str(text))
    if m:
        year = m.group(1)
        num = m.group(2).zfill(5)  # Normalizar a 5 digitos
        return f"{year}-{num}"
    return None


def extract_radicado_from_23digits(rad23):
    """De un radicado de 23 digitos, extraer el año y consecutivo.
    Formato: MMMMMCCCCYYY-AAAA-NNNNN-SS
    Los ultimos grupos suelen ser el año (2026) y el consecutivo.
    """
    if not rad23:
        return None
    clean = normalize_radicado(rad23)
    if not clean or len(clean) < 15:
        return None
    # Buscar 2026 seguido de digitos dentro del radicado
    m = re.search(r"(20\d{2})(\d{3,5})", clean)
    if m:
        year = m.group(1)
        num = m.group(2).lstrip("0") or "0"
        return f"{year}-{num.zfill(5)}"
    return None


def is_juridical_text(text):
    """Verificar si el texto es terminologia juridica, no un nombre de persona."""
    if not text:
        return True
    JURIDICAL = {
        "notificación", "notificacion", "auto", "avoca", "tutela", "sentencia",
        "fallo", "respuesta", "acción", "accion", "remite", "oficio", "remisión",
        "remision", "traslado", "contestación", "contestacion", "admisorio",
        "admite", "admision", "vinculación", "vinculacion", "requerimiento",
        "incidente", "desacato", "urgente", "segunda", "primera", "instancia",
        "impugnación", "impugnacion", "concede", "nombramiento", "docente",
        "colegio", "rad", "rdo", "control", "acciones", "adelantadas",
        "judiciales", "notificaciones", "escrito", "corre", "apertura",
        "previo", "pruebas", "decreta", "revise", "cuadro", "subsidio",
        "reposición", "reposicion", "inst", "envío", "envio",
    }
    words = set(re.findall(r"[a-záéíóúñ]+", text.lower()))
    # Si mas del 60% de las palabras son juridicas, no es nombre de persona
    if not words:
        return True
    juridical_count = sum(1 for w in words if w in JURIDICAL)
    return juridical_count / len(words) > 0.5


def merge_case_data(target_id, source_id):
    """Fusionar datos del source al target (solo campos vacios del target)."""
    target = dict(cur.execute("SELECT * FROM cases WHERE id = ?", (target_id,)).fetchone())
    source = dict(cur.execute("SELECT * FROM cases WHERE id = ?", (source_id,)).fetchone())

    campos_28 = [
        "radicado_23_digitos", "radicado_forest", "abogado_responsable", "accionante",
        "accionados", "vinculados", "derecho_vulnerado", "juzgado", "ciudad",
        "fecha_ingreso", "asunto", "pretensiones", "oficina_responsable", "estado",
        "fecha_respuesta", "sentido_fallo_1st", "fecha_fallo_1st", "impugnacion",
        "quien_impugno", "forest_impugnacion", "juzgado_2nd", "sentido_fallo_2nd",
        "fecha_fallo_2nd", "incidente", "fecha_apertura_incidente",
        "responsable_desacato", "decision_incidente", "observaciones",
    ]

    updates = []
    for campo in campos_28:
        target_val = target.get(campo)
        source_val = source.get(campo)
        # Si target vacio y source tiene dato, copiar
        if (not target_val or target_val in ("None", "")) and source_val and source_val not in ("None", ""):
            updates.append((campo, source_val))

    if updates:
        set_clause = ", ".join(f"{c} = ?" for c, _ in updates)
        values = [v for _, v in updates] + [target_id]
        cur.execute(f"UPDATE cases SET {set_clause} WHERE id = ?", values)

    return len(updates)


def reassign_children(old_case_id, new_case_id):
    """Reasignar documentos, emails, extractions y audit_logs de un caso a otro."""
    cur.execute("UPDATE documents SET case_id = ? WHERE case_id = ?", (new_case_id, old_case_id))
    cur.execute("UPDATE emails SET case_id = ? WHERE case_id = ?", (new_case_id, old_case_id))
    cur.execute("UPDATE extractions SET case_id = ? WHERE case_id = ?", (new_case_id, old_case_id))
    cur.execute("UPDATE audit_log SET case_id = ? WHERE case_id = ?", (new_case_id, old_case_id))


def delete_case(case_id):
    """Eliminar un caso y sus registros huerfanos."""
    cur.execute("DELETE FROM documents WHERE case_id = ?", (case_id,))
    cur.execute("DELETE FROM extractions WHERE case_id = ?", (case_id,))
    cur.execute("DELETE FROM audit_log WHERE case_id = ?", (case_id,))
    cur.execute("DELETE FROM emails WHERE case_id = ?", (case_id,))
    cur.execute("DELETE FROM cases WHERE id = ?", (case_id,))


# ============================================================
# PASO 1: Fusionar CSV (1-118) con carpetas existentes (119-308)
# ============================================================
print("=" * 70)
print("PASO 1: Fusionar casos CSV con carpetas existentes")
print("=" * 70)

csv_cases = cur.execute("SELECT * FROM cases WHERE id <= 118").fetchall()
folder_cases = cur.execute("SELECT * FROM cases WHERE id >= 119 AND id < 309").fetchall()

# Construir indice de carpetas por radicado abreviado y por accionante
folder_by_short_rad = {}
folder_by_accionante = {}
for fc in folder_cases:
    fc = dict(fc)
    short_rad = extract_short_radicado(fc["folder_name"])
    if short_rad:
        if short_rad not in folder_by_short_rad:
            folder_by_short_rad[short_rad] = []
        folder_by_short_rad[short_rad].append(fc)

    # Extraer nombre del folder
    parts = re.split(r"\d[\s\-]*", fc["folder_name"] or "", maxsplit=1)
    name = parts[-1].strip().upper() if len(parts) > 1 else ""
    if name and len(name) >= 5:
        folder_by_accionante[name[:25]] = fc

merged = 0
csv_only = 0  # CSV sin carpeta correspondiente
csv_deleted = 0

for cc in csv_cases:
    cc = dict(cc)
    cc_rad23 = cc.get("radicado_23_digitos")
    cc_accionante = (cc.get("accionante") or "").upper()

    # Intentar match por radicado abreviado
    short_rad = extract_short_radicado(cc_rad23)
    if not short_rad:
        short_rad = extract_radicado_from_23digits(cc_rad23)

    target_fc = None

    if short_rad and short_rad in folder_by_short_rad:
        candidates = folder_by_short_rad[short_rad]
        if len(candidates) == 1:
            target_fc = candidates[0]
        else:
            # Multiples carpetas con mismo radicado (ej: 2026-00012 de distintos municipios)
            # Intentar desambiguar por accionante
            for c in candidates:
                fn = (c["folder_name"] or "").upper()
                if cc_accionante[:15] and cc_accionante[:15] in fn:
                    target_fc = c
                    break
            if not target_fc:
                target_fc = candidates[0]  # Tomar la primera si no hay match

    # Fallback: match por accionante
    if not target_fc and cc_accionante:
        key = cc_accionante[:25]
        if key in folder_by_accionante:
            target_fc = folder_by_accionante[key]

    if target_fc:
        # Fusionar: copiar datos del CSV al caso de carpeta
        fields_merged = merge_case_data(target_fc["id"], cc["id"])
        # Reasignar hijos del CSV al caso carpeta
        reassign_children(cc["id"], target_fc["id"])
        # Eliminar caso CSV duplicado
        delete_case(cc["id"])
        merged += 1
        if fields_merged > 0:
            print(f"  Fusionado CSV #{cc['id']} -> Carpeta #{target_fc['id']} ({target_fc['folder_name'][:50]}) [{fields_merged} campos]")
    else:
        csv_only += 1

conn.commit()
print(f"\nResultado Paso 1: {merged} fusionados, {csv_only} CSV sin carpeta correspondiente")


# ============================================================
# PASO 2: Limpiar casos Gmail (IDs >= 309)
# ============================================================
print("\n" + "=" * 70)
print("PASO 2: Limpiar casos creados por Gmail monitor")
print("=" * 70)

# Recargar carpetas existentes (ahora con datos fusionados del CSV)
folder_cases = cur.execute(
    "SELECT * FROM cases WHERE folder_path IS NOT NULL AND folder_path != '' AND id < 309"
).fetchall()

# Reconstruir indice
folder_by_short_rad = {}
for fc in folder_cases:
    fc = dict(fc)
    short_rad = extract_short_radicado(fc["folder_name"])
    if short_rad:
        if short_rad not in folder_by_short_rad:
            folder_by_short_rad[short_rad] = []
        folder_by_short_rad[short_rad].append(fc)

gmail_cases = cur.execute("SELECT * FROM cases WHERE id >= 309 ORDER BY id").fetchall()

gmail_merged = 0
gmail_fixed = 0
gmail_deleted = 0

# Agrupar Gmail por radicado para detectar duplicados entre si
gmail_by_rad = {}
for gc in gmail_cases:
    gc = dict(gc)
    short_rad = extract_short_radicado(gc["folder_name"])
    if not short_rad:
        short_rad = extract_radicado_from_23digits(gc["folder_name"])
    if short_rad:
        if short_rad not in gmail_by_rad:
            gmail_by_rad[short_rad] = []
        gmail_by_rad[short_rad].append(gc)

for short_rad, gmail_group in gmail_by_rad.items():
    # Verificar si ya existe carpeta original para este radicado
    existing_folder = folder_by_short_rad.get(short_rad)

    if existing_folder:
        # CASO A: Ya existe carpeta original -> fusionar Gmail a ella y mover archivos
        target = existing_folder[0]
        for gc in gmail_group:
            # Mover archivos fisicos de la carpeta Gmail a la carpeta original
            gmail_folder = Path(gc["folder_path"]) if gc["folder_path"] else None
            target_folder = Path(target["folder_path"])

            if gmail_folder and gmail_folder.exists() and target_folder.exists():
                for f in gmail_folder.iterdir():
                    if f.is_file():
                        dest = target_folder / f.name
                        counter = 1
                        while dest.exists():
                            dest = target_folder / f"{f.stem}_{counter}{f.suffix}"
                            counter += 1
                        shutil.move(str(f), str(dest))
                        # Actualizar path en documents
                        cur.execute(
                            "UPDATE documents SET file_path = ? WHERE case_id = ? AND filename = ?",
                            (str(dest), gc["id"], f.name)
                        )

                # Eliminar carpeta Gmail si quedo vacia
                try:
                    if gmail_folder.exists() and not any(gmail_folder.iterdir()):
                        gmail_folder.rmdir()
                        print(f"  Eliminada carpeta vacia: {gmail_folder.name}")
                except Exception:
                    pass

            # Fusionar datos y reasignar hijos
            merge_case_data(target["id"], gc["id"])
            reassign_children(gc["id"], target["id"])
            delete_case(gc["id"])
            gmail_merged += 1
            print(f"  Gmail #{gc['id']} -> Carpeta #{target['id']} ({target['folder_name'][:50]})")

    else:
        # CASO B: No existe carpeta original -> quedarse con UNO, eliminar duplicados
        # Elegir el mejor: preferir el que tiene accionante real
        best = None
        for gc in gmail_group:
            acc = gc.get("accionante") or ""
            if not is_juridical_text(acc) and len(acc) >= 5:
                best = gc
                break
        if not best:
            best = gmail_group[0]

        # Fusionar duplicados al mejor
        for gc in gmail_group:
            if gc["id"] == best["id"]:
                continue

            # Mover archivos
            gmail_folder = Path(gc["folder_path"]) if gc["folder_path"] else None
            best_folder = Path(best["folder_path"]) if best["folder_path"] else None

            if gmail_folder and gmail_folder.exists() and best_folder and best_folder.exists():
                for f in gmail_folder.iterdir():
                    if f.is_file():
                        dest = best_folder / f.name
                        counter = 1
                        while dest.exists():
                            dest = best_folder / f"{f.stem}_{counter}{f.suffix}"
                            counter += 1
                        shutil.move(str(f), str(dest))

                try:
                    if gmail_folder.exists() and not any(gmail_folder.iterdir()):
                        gmail_folder.rmdir()
                        print(f"  Eliminada carpeta duplicada: {gmail_folder.name}")
                except Exception:
                    pass

            merge_case_data(best["id"], gc["id"])
            reassign_children(gc["id"], best["id"])
            delete_case(gc["id"])
            gmail_deleted += 1

conn.commit()
print(f"\nResultado Paso 2: {gmail_merged} fusionados a carpeta existente, {gmail_deleted} duplicados eliminados")


# ============================================================
# PASO 3: Renombrar carpetas Gmail sobrevivientes con nombre correcto
# ============================================================
print("\n" + "=" * 70)
print("PASO 3: Renombrar carpetas mal nombradas")
print("=" * 70)

# Recargar casos Gmail que sobrevivieron
surviving_gmail = cur.execute(
    "SELECT * FROM cases WHERE id >= 309 AND folder_path IS NOT NULL AND folder_path != ''"
).fetchall()

renamed = 0
for gc in surviving_gmail:
    gc = dict(gc)
    old_folder = Path(gc["folder_path"])
    old_name = gc["folder_name"]

    # Extraer radicado abreviado
    short_rad = extract_short_radicado(old_name)
    if not short_rad:
        short_rad = extract_radicado_from_23digits(old_name)
    if not short_rad:
        print(f"  SKIP (sin radicado): {old_name[:60]}")
        continue

    # Obtener accionante real
    accionante = gc.get("accionante") or ""

    # Limpiar accionante: quitar basura
    accionante = accionante.replace("\n", " ").replace("\r", " ").strip()
    accionante = re.sub(r"\s+", " ", accionante)
    # Quitar "ACCIONADOS", "ACCIONANDO", "EN" suelto al final
    accionante = re.sub(r"\s*(ACCIONAD[OA]S?|ACCIONANDO|EN)\s*$", "", accionante, flags=re.IGNORECASE).strip()

    if is_juridical_text(accionante):
        accionante = ""  # No usar texto juridico como nombre

    # Nuevo nombre de carpeta
    new_name = f"{short_rad} {accionante}".strip() if accionante else short_rad
    # Limpiar caracteres invalidos para nombre de carpeta
    new_name = re.sub(r'[<>:"/\\|?*]', '', new_name)

    if new_name == old_name:
        continue

    new_folder = BASE_DIR / new_name

    # Si la nueva carpeta ya existe, mover archivos ahi
    if new_folder.exists() and new_folder != old_folder:
        if old_folder.exists():
            for f in old_folder.iterdir():
                if f.is_file():
                    dest = new_folder / f.name
                    counter = 1
                    while dest.exists():
                        dest = new_folder / f"{f.stem}_{counter}{f.suffix}"
                        counter += 1
                    shutil.move(str(f), str(dest))
            try:
                if not any(old_folder.iterdir()):
                    old_folder.rmdir()
            except Exception:
                pass

        # Buscar el caso dueño de new_folder y fusionar
        target = cur.execute("SELECT id FROM cases WHERE folder_path = ?", (str(new_folder),)).fetchone()
        if target:
            merge_case_data(target["id"], gc["id"])
            reassign_children(gc["id"], target["id"])
            delete_case(gc["id"])
            print(f"  Fusionado a existente: {old_name[:40]} -> {new_name[:40]}")
            renamed += 1
            continue

    # Renombrar carpeta fisica
    if old_folder.exists() and not new_folder.exists():
        try:
            old_folder.rename(new_folder)
        except Exception as e:
            print(f"  ERROR renombrando {old_name[:40]}: {e}")
            continue

    # Actualizar DB
    cur.execute(
        "UPDATE cases SET folder_name = ?, folder_path = ?, accionante = ? WHERE id = ?",
        (new_name, str(new_folder), accionante if accionante else gc.get("accionante"), gc["id"])
    )

    # Actualizar paths de documentos
    docs = cur.execute("SELECT id, file_path FROM documents WHERE case_id = ?", (gc["id"],)).fetchall()
    for doc in docs:
        old_path = doc["file_path"]
        if old_path and str(old_folder) in old_path:
            new_path = old_path.replace(str(old_folder), str(new_folder))
            cur.execute("UPDATE documents SET file_path = ? WHERE id = ?", (new_path, doc["id"]))

    print(f"  Renombrada: {old_name[:45]} -> {new_name[:45]}")
    renamed += 1

conn.commit()
print(f"\nResultado Paso 3: {renamed} carpetas renombradas/fusionadas")


# ============================================================
# PASO 4: Limpiar accionantes falsos en TODA la DB
# ============================================================
print("\n" + "=" * 70)
print("PASO 4: Limpiar accionantes falsos (texto juridico)")
print("=" * 70)

falsos = cur.execute("""
    SELECT id, accionante, folder_name FROM cases
    WHERE accionante IS NOT NULL AND accionante != '' AND accionante != 'None'
""").fetchall()

cleaned = 0
for row in falsos:
    row = dict(row)
    acc = row["accionante"]
    if is_juridical_text(acc):
        cur.execute("UPDATE cases SET accionante = NULL WHERE id = ?", (row["id"],))
        cleaned += 1
        print(f"  Limpiado ID #{row['id']}: '{acc[:50]}' -> NULL")

conn.commit()
print(f"\nResultado Paso 4: {cleaned} accionantes falsos limpiados")


# ============================================================
# ESTADISTICAS FINALES
# ============================================================
print("\n" + "=" * 70)
print("ESTADISTICAS FINALES")
print("=" * 70)

total = cur.execute("SELECT COUNT(*) FROM cases").fetchone()[0]
con_folder = cur.execute("SELECT COUNT(*) FROM cases WHERE folder_path IS NOT NULL AND folder_path != ''").fetchone()[0]
sin_folder = cur.execute("SELECT COUNT(*) FROM cases WHERE folder_path IS NULL OR folder_path = ''").fetchone()[0]
con_accionante = cur.execute("SELECT COUNT(*) FROM cases WHERE accionante IS NOT NULL AND accionante != '' AND accionante != 'None'").fetchone()[0]
docs = cur.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
emails = cur.execute("SELECT COUNT(*) FROM emails").fetchone()[0]

print(f"  Total casos: {total}")
print(f"  Con carpeta local: {con_folder}")
print(f"  Sin carpeta (solo CSV): {sin_folder}")
print(f"  Con accionante real: {con_accionante}")
print(f"  Documentos: {docs}")
print(f"  Emails: {emails}")

conn.close()
print("\nLimpieza completada.")
