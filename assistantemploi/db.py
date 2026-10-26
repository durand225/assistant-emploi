"""Accès à la base de données SQLite et exécution des migrations.

Règles :
- Un seul processus ne peut ouvrir la base en même temps (journal_mode=WAL + busy timeout).
- La base est créée relativement au CWD (pour rester portable) — c'est pourquoi
  `init_db.py` s'exécute de la racine du projet.
- Les migrations sont versionnées et exécutées une seule fois (table `_migrations`).
- `executescript` valide implicitement : on utilise une transaction explicite autour
  de chaque migration pour ne jamais partiellement appliquer.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from .config import get

_SCHEME_SQLITE = "sqlite:///"
_ABS_SQLITE = "sqlite:////"


def database_path() -> Path | None:
    """Convertit DATABASE_URL en chemin local. `None` = base en mémoire."""
    raw = get("DATABASE_URL", "sqlite:///data/assistant-emploi.db")
    if raw == "sqlite:///:memory:":
        return None
    if raw.startswith(_SCHEME_SQLITE):
        return Path(raw[len(_SCHEME_SQLITE):])
    if raw.startswith(_ABS_SQLITE):
        return Path(raw[len(_ABS_SQLITE):])
    raise ValueError(f"URL de base de données non supportée : {raw!r}")


def connect(path: Path | None = None) -> sqlite3.Connection:
    if path is None:
        conn = sqlite3.connect(":memory:")
    else:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(p)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def get_migrations() -> list[tuple[int, str]]:
    from .migrations import MIGRATIONS  # évite une dépendance circulaire cachée

    ordered = sorted(MIGRATIONS, key=lambda item: item[0])
    return [(version, sql) for version, sql in ordered]


def migrate(conn: sqlite3.Connection) -> int:
    """Exécute les migrations non encore appliquées. Retourne le nombre appliqué."""
    # Table de suivi des versions — créée d'abord pour que la migration 1 puisse
    # s'insérer dedans de façon idempotente.
    conn.execute(
        "CREATE TABLE IF NOT EXISTS _migrations ("
        "version INTEGER PRIMARY KEY, "
        "applied_at TEXT NOT NULL DEFAULT (datetime('now')))"
    )
    applied = set(
        row[0]
        for row in conn.execute("SELECT version FROM _migrations").fetchall()
    )
    total = 0
    for version, sql in get_migrations():
        if version in applied:
            continue
        conn.execute("BEGIN")
        try:
            conn.executescript(sql)
            conn.execute("INSERT INTO _migrations (version) VALUES (?)", (version,))
            conn.commit()
            total += 1
        except Exception:
            conn.rollback()
            raise
    return total
