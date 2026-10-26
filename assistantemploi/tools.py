"""Outils métier emploi.* — interface du serveur applicatif.

Rôle :
- Exposer les outils métiers autorisés à l'adaptateur Hermes via MCP ou serveur.
- Valider les paramètres côté serveur (jamais de confiance dans le navigateur).
- Retourner des résultats structurés (propriété, audit, tarif figé).

Règles applicables :
- CR01 : le serveur fixe le coût ; aucune valeur de crédit fournie par le navigateur.
- CR02 : une action métier possède une clé d'idempotence, au plus une consommation.
- CR03 : vérifier et réserver le solde dans une transaction atomique.
- CR04 : consommer uniquement après résultat validé et sauvegardé.
- CR05 : un échec libère la réservation ; jamais de refacturation aux retours.
- CR06 : un message déclenchant une autre action ne cumule pas CHAT avec cette action.
- CR07 : les clarifications nécessaires à l'action autorisée font partie de son prix.
- CR08 : lecture, téléchargement, édition manuelle restent gratuits.
- CR09 : la recharge ouvre un solde ; elle ne déclenche pas une ancienne action.
- CR10 : un devis fige tarif et périmètre.
- CR11 : une recherche sans offre n'est pas une panne.
- CR12 : tous les mouvements sont auditables.

Routes /action-quotes et /actions appartiennent à l'application, pas à l'API native Hermes.
Ces outils sont accessibles par MCP ou adaptateur serveur.
"""

from __future__ import annotations

import hashlib
import sqlite3
from datetime import datetime, timezone, timedelta
from typing import Any

from . import accounts, schemas, wallet
from .db import connect as db_connect

# Grille de crédits (CR01-CR12)
CREDITS = {
    "CHAT": 1,
    "IMPORT": 3,
    "SEARCH": 8,
    "ANALYZE": 3,
    "CV": 10,
    "REVISE": 3,
    "READ": 0,
    "EDIT": 0,
    "REPAIR": 0,
}

# Idempotency key format: <tool>:<owner>:<nonce>
def _make_idempotency_key(tool: str, owner_id: str, nonce: str = "") -> str:
    """Génère une clé d'idempotence unique pour une action."""
    raw = f"{tool}:{owner_id}:{nonce or uuid4_hex()}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _get_user_or_error(conn: sqlite3.Connection, user_id: str) -> dict[str, Any]:
    """Validate ownership: the user must exist and be accessible."""
    user = accounts.get_user_by_id(conn, user_id)
    if user is None:
        raise ValueError(schemas.make_error("USER_NOT_FOUND", message="compte inconnu"))
    return user


def _latest_profile(conn: sqlite3.Connection, user_id: str) -> sqlite3.Row | None:
    """Return the latest (or only) profile for a user, if any."""
    row = conn.execute(
        "SELECT p.*, pv.version "
        "FROM profiles p "
        "LEFT JOIN profile_versions pv ON pv.profile_id = p.id "
        "WHERE p.user_id = ? "
        "ORDER BY pv.version DESC LIMIT 1",
        (user_id,),
    ).fetchone()
    return row


def _wallet_id_or_error(conn: sqlite3.Connection, user_id: str) -> str:
    """Resolve the wallet id for a user; raise if none (or not owned)."""
    row = conn.execute("SELECT id FROM wallets WHERE user_id = ?", (user_id,)).fetchone()
    if row is None:
        raise ValueError(schemas.make_error("NOT_AUTHORIZED", message="portefeuille absent"))
    return row["id"]


def _check_balance(conn: sqlite3.Connection, user_id: str, needed: int) -> int:
    """Return the actual balance after confirming no reservation exceeded."""
    wallet_id = _wallet_id_or_error(conn, user_id)
    balance = wallet.credit_balance(conn, wallet_id)
    if balance < needed:
        raise ValueError(schemas.make_error("INSUFFICIENT_CREDITS"))
    return balance


def get_context(conn: sqlite3.Connection, user_id: str) -> dict[str, Any]:
    """Get context for the user (no side effects)."""
    _get_user_or_error(conn, user_id)
    user = accounts.get_user_by_id(conn, user_id)
    profile = None
    profile_row = _latest_profile(conn, user_id)
    if profile_row is not None:
        profile = {
            "id": profile_row["id"],
            "version": profile_row["version"],
            "objective": profile_row["objective"],
            "country": profile_row["country"],
            "city": profile_row["city"],
        }
    wallet_id = _wallet_id_or_error(conn, user_id)
    balance = wallet.credit_balance(conn, wallet_id)
    return {
        "user_id": user_id,
        "account_status": "verified" if user["email_verified_at"] else "unverified",
        "profile_version": profile["version"] if profile else None,
        "balance": balance,
        "has_active_actions": False,  # computed in delivery
    }


def get_quote(conn: sqlite3.Connection, user_id: str, action_code: str, inputs_hash: str) -> dict[str, Any]:
    """Compute a quote (tariff version from our config source) and persist it."""
    _get_user_or_error(conn, user_id)
    if action_code not in CREDITS:
        raise ValueError(schemas.make_error("NOT_AUTHORIZED", message="action inconnue"))
    needed = CREDITS[action_code]
    wallet_id = _wallet_id_or_error(conn, user_id)
    available = wallet.credit_balance(conn, wallet_id)
    if available < needed:
        raise ValueError(schemas.make_error("INSUFFICIENT_CREDITS"))
    # Quote expires in 15 minutes from now (TTL = 15 min).
    now = datetime.now(timezone.utc)
    expires_at = (now + timedelta(minutes=15)).strftime("%Y-%m-%dT%H:%M:%SZ")
    quote_id = uuid4_hex()
    cmd = (
        "INSERT INTO action_quotes (quote_id, action_code, credits, available_balance, "
        "inputs_hash, tariff_version, expires_at) VALUES (?, ?, ?, ?, ?, ?, ?)"
    )
    conn.execute(cmd, (quote_id, action_code, needed, available, inputs_hash, 1, expires_at))
    conn.commit()
    return {
        "quote_id": quote_id,
        "action_code": action_code,
        "credits": needed,
        "available_balance": available,
        "inputs_hash": inputs_hash,
        "tariff_version": 1,
        "expires_at": expires_at,
    }


def authorize_action(conn: sqlite3.Connection, quote_id: str, idempotency_key: str, owner_id: str) -> dict[str, Any]:
    """Authorize and reserve credits (atomic reservation)."""
    _get_user_or_error(conn, owner_id)
    # Validate quote is still valid.
    quote = _load_quote(conn, quote_id)
    if quote is None:
        raise ValueError(schemas.make_error("QUOTE_EXPIRED"))
    action_code = quote["action_code"]
    needed = quote["credits"]
    available = _check_balance(conn, owner_id, needed)
    # Create reservation atomically.
    wallet_id = _wallet_id_or_error(conn, owner_id)
    reservation = wallet.reserve_credits(conn, wallet_id, needed, idempotency_key)
    if not reservation["ok"]:
        raise ValueError(schemas.make_error("INSUFFICIENT_CREDITS"))
    # Create the action row (state: reserved) for later cancel/delivery.
    # reservation_id is the unique key that ties the action to its reservation.
    action_id = uuid4_hex()
    reservation_id = reservation["reservation_id"]
    now = schemas.now_iso()
    conn.execute(
        "INSERT INTO actions (id, reservation_id, quote_id, idempotency_key, owner_id, "
        "action_code, state, credits_reserved, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, 'reserved', ?, ?)",
        (action_id, reservation_id, quote_id, idempotency_key, owner_id, action_code, needed, now),
    )
    conn.commit()
    return {
        "reservation_id": reservation["reservation_id"],
        "action_id": action_id,
        "status": "reserved",
        "credits_reserved": needed,
    }


def cancel_action(conn: sqlite3.Connection, action_id: str, owner_id: str) -> dict[str, Any]:
    """Cancel an action and release reservation."""
    _get_user_or_error(conn, owner_id)
    action = _load_action(conn, action_id)
    if action is None:
        raise ValueError(schemas.make_error("TASK_NOT_FOUND"))
    if action.get("owner_id") != owner_id:
        raise ValueError(schemas.make_error("NOT_AUTHORIZED"))
    # Release the underlying reservation (the one tied to this action).
    reservation_id = action.get("reservation_id")
    if not reservation_id:
        raise ValueError(schemas.make_error("TASK_NOT_FOUND"))
    released = wallet.release_reservation(conn, reservation_id)
    if released.get("ok"):
        conn.execute(
            "UPDATE actions SET state = 'cancelled' WHERE id = ?", (action_id,)
        )
        conn.commit()
    return {
        "action_id": action_id,
        "status": "cancelled",
        "credits_released": None,
    }


def get_balance(conn: sqlite3.Connection, user_id: str) -> dict[str, Any]:
    """Read-only balance check (no debit)."""
    _get_user_or_error(conn, user_id)
    wallet_id = _wallet_id_or_error(conn, user_id)
    available = wallet.credit_balance(conn, wallet_id)
    reserved = _active_reservation_count(conn, user_id)
    return {
        "user_id": user_id,
        "available_balance": available,
        "reserved_balance": reserved,
        "pending_actions": reserved,  # simplified
    }


def grant_welcome(conn: sqlite3.Connection, user_id: str) -> dict[str, Any]:
    """Grant unique welcome bonus (15 credits) once per verified account."""
    user = _get_user_or_error(conn, user_id)
    if not user["email_verified_at"]:
        raise ValueError(schemas.make_error("PROFILE_INCOMPLETE"))
    result = wallet.grant_welcome(conn, user_id)
    wallet_id = _wallet_id_or_error(conn, user_id)
    balance_after = wallet.credit_balance(conn, wallet_id)
    return {
        "user_id": user_id,
        "granted": result["granted"],
        "welcome_lot_id": None,
        "balance_after": balance_after,
    }


# ---------------------------------------------------------------------------
# Internal helpers (count / resolve active reservations)
# ---------------------------------------------------------------------------

def _active_reservation_count(conn: sqlite3.Connection, user_id: str) -> int:
    """Count currently active (non-released) reservations for a user's wallet."""
    wallet_id = _wallet_id_or_error(conn, user_id)
    cur = conn.execute(
        "SELECT COUNT(*) AS c FROM reservations WHERE wallet_id = ? AND status = 'active'",
        (wallet_id,),
    )
    return int(cur.fetchone()["c"])


# ---------------------------------------------------------------------------
# Internal helpers (loaders for quote / action)
# ---------------------------------------------------------------------------

def _load_quote(conn: sqlite3.Connection, quote_id: str) -> dict[str, Any] | None:
    """Load quote from the given connection; return None if not found or expired."""
    try:
        row = conn.execute(
            "SELECT * FROM action_quotes WHERE quote_id = ?", (quote_id,)
        ).fetchone()
        if row is None:
            return None
        # Simplified expiry check (15 min TTL).
        import datetime
        expires = row["expires_at"]
        if datetime.datetime.fromisoformat(expires.replace("Z", "+00:00")) < datetime.datetime.now(datetime.timezone.utc):
            return None
        return dict(row)
    finally:
        pass  # connection is managed by caller


def _load_action(conn: sqlite3.Connection, action_id: str) -> dict[str, Any] | None:
    """Load action from the given connection; return None if not found."""
    try:
        row = conn.execute(
            "SELECT * FROM actions WHERE id = ?", (action_id,)
        ).fetchone()
        return dict(row) if row else None
    finally:
        pass


EMPLO_TOOLS = {
    "emploi.get_context": {
        "description": "Récupère les informations contextuelles de l'utilisateur",
        "params": ["user_id"],
        "handler": "get_context",
    },
    "emploi.get_quote": {
        "description": "Calcule un devis pour une action avec prix figé",
        "params": ["user_id", "action_code", "inputs_hash"],
        "handler": "get_quote",
    },
    "emploi.authorize_action": {
        "description": "Autorise et réserve une action (débit atomique)",
        "params": ["quote_id", "idempotency_key", "owner_id"],
        "handler": "authorize_action",
    },
    "emploi.cancel_action": {
        "description": "Annule une action en attente/cours",
        "params": ["action_id", "owner_id"],
        "handler": "cancel_action",
    },
    "emploi.get_balance": {
        "description": "Lecture du solde de crédits (lecture seule)",
        "params": ["user_id"],
        "handler": "get_balance",
    },
    "emploi.grant_welcome": {
        "description": "Octroie le bonus unique de 15 crédits à un compte vérifié",
        "params": ["user_id"],
        "handler": "grant_welcome",
    },
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def uuid4_hex() -> str:
    """Return a random hex string (UUID v4)."""
    import uuid
    return uuid.uuid4().hex


if __name__ == "__main__":
    import sys
    print("emploi.* tools interface loaded")
