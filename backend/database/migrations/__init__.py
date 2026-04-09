"""Migraciones de schema para la DB SQLite.

Cada migracion es idempotente: puede correrse multiples veces sin efecto
secundario. Usan PRAGMA table_info para detectar si el cambio ya se aplico.
"""
