"""Profil canonique — Ticket T04.

Règles du ticket (PRD M04) :
- Un profil par utilisateur, versionné et immuable par construction.
- Chaque fait (expérience, compétence, formation, ...) porte sa source (import,
  écriture manuelle, transcription validée) et un statut :
  extraite_a_confirmer, confirmee, contradictoire, supprimee.
- L'utilisateur corrige les faits; l'ancien classement devient obsolète et peut être
  recalculé sans nouvelle collecte.
- Une version capture l'ensemble du profil et de ses faits à un instant T; elle est
  conservée indéfiniment et ne peut pas être remplacée.

Couche de service CLI : scripts/profile.py.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from uuid import uuid4

FIELD_CHOICES = (
    "objective",
    "country",
    "city",
    "mobility",
    "contract_type",
    "studies",
    "experiences",
    "projects",
    "skills",
    "languages",
    "salary_preference",
)

STATUS_CHOICES = (
    "extraite_a_confirmer",
    "confirmee",
    "contradictoire",
    "supprimee",
)

FIELD_LABELS = {
    "objective": "Objectif professionnel",
    "country": "Pays",
    "city": "Ville",
    "mobility": "Mobilité",
    "contract_type": "Type de contrat",
    "studies": "Formation",
    "experiences": "Expériences",
    "projects": "Projets",
    "skills": "Compétences",
    "languages": "Langues",
    "salary_preference": "Préférence salariale",
}


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _uid() -> str:
    return uuid4().hex


# --------------------------------------------------------------------------- #
#  Profil
# --------------------------------------------------------------------------- #
def create_profile(conn: sqlite3.Connection, user_id: str, **fields) -> sqlite3.Row:
    """Crée un profil pour un utilisateur (un seul par compte)."""
    for key in fields:
        if key not in FIELD_CHOICES:
            raise ValueError(f"champ inconnu : {key!r} (choix autorisés : {FIELD_CHOICES})")
    uid = _uid()
    now = _now()
    conn.execute(
        "INSERT INTO profiles (id, user_id, objective, country, city, mobility, "
        "contract_type, studies, experiences, projects, skills, languages, "
        "salary_preference, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            uid, user_id,
            fields.get("objective"),
            fields.get("country"),
            fields.get("city"),
            fields.get("mobility"),
            fields.get("contract_type"),
            fields.get("studies"),
            fields.get("experiences"),
            fields.get("projects"),
            fields.get("skills"),
            fields.get("languages"),
            fields.get("salary_preference"),
            now,
            now,
        ),
    )
    conn.commit()
    return get_profile_by_user(conn, user_id)


def get_profile_by_user(conn: sqlite3.Connection, user_id: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM profiles WHERE user_id = ?", (user_id,)
    ).fetchone()


def get_profile_by_id(conn: sqlite3.Connection, profile_id: str) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM profiles WHERE id = ?", (profile_id,)).fetchone()


# --------------------------------------------------------------------------- #
#  Faits (provenance + statut)
# --------------------------------------------------------------------------- #
def add_fact(conn: sqlite3.Connection, profile_id: str, field: str,
             fact_text: str, source_type: str, source_ref: str | None = None) -> sqlite3.Row:
    """Ajoute un fait au profil avec sa source et son statut initial."""
    if field not in FIELD_CHOICES:
        raise ValueError(f"champ inconnu : {field!r}")
    uid = _uid()
    conn.execute(
        "INSERT INTO profile_facts (id, profile_id, field, fact_text, source_type, source_ref, "
        "status, value, created_at) VALUES (?, ?, ?, ?, ?, ?, 'extraite_a_confirmer', ?, ?)",
        (uid, profile_id, field, fact_text, source_type, source_ref, fact_text, _now()),
    )
    conn.commit()
    return get_fact(conn, uid)


def get_fact(conn: sqlite3.Connection, fact_id: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM profile_facts WHERE id = ?", (fact_id,)
    ).fetchone()


def update_fact(conn: sqlite3.Connection, fact_id: str, value: str | None = None,
                status: str | None = None) -> sqlite3.Row:
    """Mise à jour d'un fait (valeur et/ou statut). Seul le propriétaire peut le faire."""
    stmt = "UPDATE profile_facts SET "
    params = []
    if value is not None:
        stmt += "value = ?, "
        params.append(value)
    if status is not None:
        if status not in STATUS_CHOICES:
            raise ValueError(f"statut inconnu : {status!r}")
        stmt += "status = ?, "
        params.append(status)
    stmt = stmt.rstrip(", ") + " WHERE id = ?"
    params.append(fact_id)
    conn.execute(stmt, tuple(params))
    conn.commit()
    return get_fact(conn, fact_id)


def confirm_fact(conn: sqlite3.Connection, fact_id: str, value: str | None = None) -> sqlite3.Row:
    """Marque un fait comme confirmé (valeur saisie par le candidat)."""
    return update_fact(conn, fact_id, value=value, status="confirmee")


def delete_fact(conn: sqlite3.Connection, fact_id: str, value: str | None = None) -> sqlite3.Row:
    """Marque un fait comme supprimé (hors exploitation, sans effacer la trace)."""
    return update_fact(conn, fact_id, value=value, status="supprimee")


# --------------------------------------------------------------------------- #
#  Versions (immuables)
# --------------------------------------------------------------------------- #
def create_version(conn: sqlite3.Connection, profile_id: str) -> sqlite3.Row:
    """Capture instantanément le profil et l'état de ses faits; la version est immuable."""
    profile = get_profile_by_id(conn, profile_id)
    if profile is None:
        raise LookupError("profil inconnu")
    facts = conn.execute(
        "SELECT id, field, fact_text, source_type, source_ref, status, value FROM "
        "profile_facts WHERE profile_id = ? ORDER BY id", (profile_id,)
    ).fetchall()
    fields_json = json.dumps({k: profile[k] for k in FIELD_CHOICES if profile[k]})
    facts_json = json.dumps([
        {"id": r["id"], "field": r["field"], "status": r["status"], "value": r["value"]}
        for r in facts
    ])
    now = _now()
    # Numérotation de la version (0 si aucune version existante).
    max_version = conn.execute(
        "SELECT COALESCE(MAX(version), 0) FROM profile_versions WHERE profile_id = ?",
        (profile_id,),
    ).fetchone()[0]
    next_version = max_version + 1
    conn.execute(
        "INSERT INTO profile_versions (id, profile_id, version, fields_json, facts_json, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (_uid(), profile_id, next_version, fields_json, facts_json, now),
    )
    conn.commit()
    return get_version(conn, profile_id, next_version)


def get_versions(conn: sqlite3.Connection, profile_id: str) -> list[dict]:
    rows = conn.execute(
        "SELECT id, version, fields_json, facts_json, created_at FROM profile_versions "
        "WHERE profile_id = ? ORDER BY version DESC", (profile_id,)
    ).fetchall()
    return [dict(r) for r in rows]


def get_latest_version(conn: sqlite3.Connection, profile_id: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT id, version, fields_json, facts_json, created_at FROM profile_versions "
        "WHERE profile_id = ? ORDER BY version DESC LIMIT 1",
        (profile_id,),
    ).fetchone()


def get_version(conn: sqlite3.Connection, profile_id: str, version: int) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM profile_versions WHERE profile_id = ? AND version = ?",
        (profile_id, version),
    ).fetchone()
