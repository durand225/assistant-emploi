"""Compte utilisateur, vérification email par lien, et frontières de propriété.

Règles de ce ticket (T02) :
- Un utilisateur possède ses ressources ; il ne peut y accéder aucun autre
  utilisateur (frontière de propriété). Le contrôle s'exerce au niveau des
  fonctions des ressources : chaque fonction de ressource accepte `owner_id` et ne
  renvoie que ses propres lignes. `check_owner()` est le garde-fous.
- La vérification email se fait par un lien unique, unidirectionnel et non
  réutilisable : un token utilisé ne peut plus valider un compte.
- La création d'utilisateur est idempotente par email : le même email donne le
  même identifiant (pas de double compte).

Couche d'interface en amont : `scripts/accounts.py` (register / link / verify /
status / test-isolation).
"""

from __future__ import annotations

import secrets
import sqlite3
from datetime import datetime, timezone
from uuid import uuid4

from .db import connect

EMAIL_RE = ...  # gardé placeholder, la validation s'appuie sur l'email "@" + ".", voir create_user


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def create_user(conn, email: str) -> dict:
    """Crée un compte (ou renvoie l'existant pour un email identique)."""
    email = (email or "").strip().lower()
    if not email or "@" not in email or "." not in email.split("@")[-1]:
        raise ValueError("Adresse email invalide.")

    uid = uuid4().hex
    try:
        conn.execute(
            "INSERT INTO users (id, email, created_at, updated_at) VALUES (?, ?, ?, ?)",
            (uid, email, _now(), _now()),
        )
        conn.commit()
        return {"id": uid, "email": email, "created": True}
    except sqlite3.IntegrityError:
        conn.rollback()

    row = conn.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()
    if row is not None:
        return {"id": row["id"], "email": email, "created": False}
    raise RuntimeError("Impossible de retrouver l'utilisateur créé.")


def get_user_by_id(conn, user_id: str) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()


def get_user_by_email(conn, email: str) -> sqlite3.Row | None:
    email = (email or "").strip().lower()
    if not email:
        return None
    return conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()


def issue_verification_token(conn, user_id: str) -> str:
    """Retourne le lien de vérification (token) de l'utilisateur.

    Idempotent : un token non utilisé retourne le même que pour l'appel précédent
    (pas de nouveaux tokens inutiles). Un token déjà utilisé ne se réutilise pas.
    """
    last_unused = conn.execute(
        "SELECT token FROM registration_tokens "
        "WHERE user_id = ? AND used_at IS NULL "
        "ORDER BY created_at DESC LIMIT 1",
        (user_id,),
    ).fetchone()
    if last_unused is not None:
        return last_unused["token"]

    token = secrets.token_urlsafe(32)
    uid = uuid4().hex
    conn.execute(
        "INSERT INTO registration_tokens (id, user_id, token, created_at) VALUES (?, ?, ?, ?)",
        (uid, user_id, token, _now()),
    )
    conn.commit()
    return token


def verify_email(conn, token: str) -> dict:
    """Valide un token ; marque le compte email vérifié. Retourne le résultat."""
    row = conn.execute(
        "SELECT user_id FROM registration_tokens WHERE token = ? AND used_at IS NULL",
        (token,),
    ).fetchone()
    if row is None:
        return {"verified": False, "reason": "token_invalide_ou_utilise"}

    user_id = row["user_id"]
    now = _now()
    conn.execute("UPDATE registration_tokens SET used_at = ? WHERE token = ?", (now, token))
    conn.execute(
        "UPDATE users SET email_verified_at = ?, updated_at = ? WHERE id = ?",
        (now, now, user_id),
    )
    conn.commit()
    return {"verified": True, "user_id": user_id}


def get_verification_status(conn, user_id: str) -> dict:
    user = get_user_by_id(conn, user_id)
    if user is None:
        return {"exists": False}
    return {
        "exists": True,
        "email_verified": user["email_verified_at"] is not None,
    }


def is_owner(user_id: str, owner_id: str) -> bool:
    """Vrai si l'appelant est le propriétaire de la ressource."""
    return user_id is not None and owner_id is not None and user_id == owner_id


def check_owner(user_id: str, owner_id: str) -> None:
    """Lève si l'appelant n'est pas le propriétaire (garde-fous des ressources)."""
    if not is_owner(user_id, owner_id):
        raise PermissionError("Accès interdit : pas le propriétaire de cette ressource.")
