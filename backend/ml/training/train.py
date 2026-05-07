"""Training sklearn para 4 targets:
  - dependencia (L2, 17 clases)
  - tipo (TUTELA / DESACATO)
  - tema_normalized (25 clases)
  - abogado_full (17 clases activos, ignora INACTIVO_*)

Diseño:
  - Train: filas Excel histórico (`historical_cases`) — 4,369 casos
  - Train-test split: estratificado por año (2023-24 train, 2025-26 test)
  - Cross-val k=5 dentro del train
  - Pipeline: ColumnTransformer (TF-IDF para texto + passthrough para num) + LogReg
  - Persistencia: joblib en backend/ml/artifacts/<target>.joblib

Uso:
    python -m backend.ml.training.train --target dependencia
    python -m backend.ml.training.train --target tema_normalized
    python -m backend.ml.training.train --all
"""

from __future__ import annotations
import argparse
import json
import logging
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import classification_report, confusion_matrix
from sklearn.model_selection import StratifiedKFold, cross_val_score, train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import FunctionTransformer
from sqlalchemy import text

from backend.database.database import SessionLocal


logger = logging.getLogger("tutelas.ml.train")

ARTIFACTS = Path(__file__).resolve().parent.parent / "artifacts"
ARTIFACTS.mkdir(parents=True, exist_ok=True)


# ============================================================
# Cargar dataset
# ============================================================

def load_dataset(target: str) -> pd.DataFrame:
    """Carga `historical_cases` y filtra filas con label válido para el target."""
    db = SessionLocal()
    try:
        df = pd.read_sql(text("""
            SELECT id, fecha, source_sheet, tipo, tema_normalized,
                   dependencia_normalized, abogado_full, abogado_activo,
                   tema_raw, observaciones, observaciones_henser,
                   correo_juzgado, accionante
            FROM historical_cases
        """), db.bind)
    finally:
        db.close()

    # Filtrar filas con label válido
    if target == "dependencia":
        # L2 (17 clases) — sufre desbalance fuerte
        df = df[df["dependencia_normalized"].notna() & (df["dependencia_normalized"] != "SIN_ASIGNAR")]
        df["label"] = df["dependencia_normalized"]
    elif target == "direccion":
        # v8.0: L1 (5 clases) — mejor para datos desbalanceados
        from backend.ml.data.sed_org import get_l1
        df = df[df["dependencia_normalized"].notna() & (df["dependencia_normalized"] != "SIN_ASIGNAR")]
        df["label"] = df["dependencia_normalized"].apply(get_l1)
    elif target == "tipo":
        df = df[df["tipo"].notna()]
        df["label"] = df["tipo"]
    elif target == "tema_normalized":
        df = df[df["tema_normalized"].notna() & (df["tema_normalized"] != "OTRO")]
        df["label"] = df["tema_normalized"]
    elif target == "abogado":
        df = df[(df["abogado_activo"] == 1) & df["abogado_full"].notna()]
        df["label"] = df["abogado_full"]
    else:
        raise ValueError(f"Target desconocido: {target}")

    # Año del sheet (para split temporal)
    df["year"] = df["source_sheet"].str.extract(r"(\d{4})").astype(int)

    # Texto concatenado para TF-IDF
    df["text"] = (
        df["tema_raw"].fillna("") + " "
        + df["observaciones"].fillna("") + " "
        + df["observaciones_henser"].fillna("") + " "
        + df["correo_juzgado"].fillna("")
    ).str.lower()

    return df[["id", "year", "text", "tipo", "label"]].dropna(subset=["label"])


# ============================================================
# Pipeline
# ============================================================

def build_pipeline(target: str) -> Pipeline:
    """Pipeline TF-IDF + LogReg con regularización L2 fuerte (datos pequeños)."""
    text_vec = TfidfVectorizer(
        max_features=2000,
        ngram_range=(1, 2),
        min_df=3,
        max_df=0.95,
        strip_accents="unicode",
        lowercase=True,
    )

    # Para tipo (binario) y abogado (17 clases) usar LR simple.
    # Para dependencia y tema (más clases) usar class_weight=balanced.
    # NOTA: sklearn 1.7+ removed multi_class param (multinomial es default ahora).
    if target in ("dependencia", "tema_normalized", "direccion"):
        clf = LogisticRegression(
            max_iter=2000, C=0.5, class_weight="balanced", n_jobs=-1,
        )
    else:
        clf = LogisticRegression(max_iter=2000, C=1.0, n_jobs=-1)

    return Pipeline([("vec", text_vec), ("clf", clf)])


# ============================================================
# Entrenar y evaluar
# ============================================================

def train_target(target: str, save: bool = True) -> dict:
    df = load_dataset(target)
    n = len(df)
    n_classes = df["label"].nunique()
    logger.info("[%s] dataset n=%d, clases=%d", target, n, n_classes)

    if n < 50:
        logger.warning("[%s] dataset muy pequeño (%d) — saltando", target, n)
        return {"target": target, "skipped": True, "reason": "n<50"}

    if n_classes < 2:
        logger.warning("[%s] solo %d clase — saltando", target, n_classes)
        return {"target": target, "skipped": True, "reason": "solo 1 clase"}

    # Filtrar clases con muy pocas muestras (<3) para evitar errores en CV
    counts = df["label"].value_counts()
    valid_classes = counts[counts >= 5].index
    df = df[df["label"].isin(valid_classes)]
    logger.info("[%s] tras filtrar clases<5: n=%d, clases=%d",
                target, len(df), df["label"].nunique())

    # Split temporal: 2023-2024 train, 2025-2026 test (excepto si pocas filas en años recientes)
    train_mask = df["year"] <= 2024
    if train_mask.sum() < 100 or (~train_mask).sum() < 20:
        # Fallback: split estratificado normal 80/20
        X = df["text"]
        y = df["label"]
        X_train, X_test, y_train, y_test = train_test_split(
            X, y, test_size=0.2, stratify=y, random_state=42,
        )
        split_strategy = "stratified_random"
    else:
        X_train = df.loc[train_mask, "text"]
        y_train = df.loc[train_mask, "label"]
        X_test = df.loc[~train_mask, "text"]
        y_test = df.loc[~train_mask, "label"]
        split_strategy = "temporal_2023-24_vs_2025-26"

    # Pipeline
    pipe = build_pipeline(target)

    # Cross-val k=5 dentro del train
    try:
        skf = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)
        cv_scores = cross_val_score(pipe, X_train, y_train, cv=skf,
                                     scoring="f1_macro", n_jobs=-1)
        cv_mean = float(np.mean(cv_scores))
        cv_std = float(np.std(cv_scores))
    except Exception as e:
        logger.warning("[%s] CV falló: %s — entrenando sin CV", target, e)
        cv_mean = cv_std = None

    # Fit + predict en test
    pipe.fit(X_train, y_train)
    y_pred = pipe.predict(X_test)

    # Métricas
    report = classification_report(y_test, y_pred, output_dict=True, zero_division=0)
    macro_f1 = report["macro avg"]["f1-score"]
    accuracy = report["accuracy"]

    # Confusion matrix top-5 clases
    top_classes = df["label"].value_counts().head(8).index.tolist()
    cm_subset_idx = [i for i, c in enumerate(pipe.classes_) if c in top_classes]
    cm = None
    try:
        cm = confusion_matrix(y_test, y_pred, labels=pipe.classes_)
    except Exception:
        pass

    result = {
        "target": target,
        "n_train": int(train_mask.sum()) if split_strategy.startswith("temporal") else len(X_train),
        "n_test": int((~train_mask).sum()) if split_strategy.startswith("temporal") else len(X_test),
        "n_classes": df["label"].nunique(),
        "split_strategy": split_strategy,
        "cv_macro_f1_mean": cv_mean,
        "cv_macro_f1_std": cv_std,
        "test_accuracy": accuracy,
        "test_macro_f1": macro_f1,
        "classes": pipe.classes_.tolist(),
    }

    # v8.0: gate por target; en inferencia se filtra por confidence ≥0.75.
    GATES = {
        "tema_normalized": 0.70,
        "direccion": 0.40,    # L1 — bajo por drift temporal, usar threshold alto
        "dependencia": 0.30,  # L2 — solo si el modelo está MUY seguro
        "tipo": 0.50,
    }
    gate = GATES.get(target, 0.5)
    if save and macro_f1 >= gate:
        path = ARTIFACTS / f"{target}.joblib"
        joblib.dump(pipe, path)
        result["saved"] = str(path)
        logger.info("[%s] guardado (macro-F1=%.3f >= gate %.2f)", target, macro_f1, gate)
    else:
        result["saved"] = None
        logger.info("[%s] NO guardado (macro-F1=%.3f < gate %.2f)", target, macro_f1, gate)

    print(f"\n=== {target} ===")
    print(f"  n_train={result['n_train']}  n_test={result['n_test']}  n_classes={result['n_classes']}")
    print(f"  split: {split_strategy}")
    if cv_mean is not None:
        print(f"  CV macro-F1: {cv_mean:.3f} ± {cv_std:.3f}")
    print(f"  TEST accuracy: {accuracy:.3f}")
    print(f"  TEST macro-F1: {macro_f1:.3f}")
    print(f"  Saved: {result['saved']}")

    return result


# ============================================================
# CLI
# ============================================================

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--target",
                        choices=["dependencia", "direccion", "tipo", "tema_normalized", "abogado", "all"],
                        default="all")
    parser.add_argument("--no-save", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    # v8.0: abogado removido (texto no predice asignación administrativa).
    # Targets útiles: tipo, direccion (L1), dependencia (L2), tema_normalized.
    targets = ["tipo", "direccion", "dependencia", "tema_normalized"] if args.target == "all" else [args.target]
    results = {}
    for t in targets:
        try:
            results[t] = train_target(t, save=not args.no_save)
        except Exception as e:
            logger.error("[%s] error: %s", t, e)
            results[t] = {"target": t, "error": str(e)}

    # Resumen final
    print("\n" + "=" * 60)
    print("RESUMEN ENTRENAMIENTO")
    print("=" * 60)
    for t, r in results.items():
        status = "✓ saved" if r.get("saved") else ("✗ skipped" if r.get("skipped") else "⚠ low metric")
        f1 = r.get("test_macro_f1", "N/A")
        print(f"  {status:<12}  {t:<20}  macro-F1={f1}")

    summary_path = ARTIFACTS / "training_summary.json"
    with open(summary_path, "w") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\nReporte: {summary_path}")


if __name__ == "__main__":
    main()
