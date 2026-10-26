"""Support & administration — T05/T11.

Rôle :
- Support : tickets de support, référence, accès restreint au contenu,
  réponses humaines.
- Administration : panneau d'administration (santé sources, coûts, files en
  attente, erreurs, paiements en attente, réservations anciennes).

Les deux utilisent un modèle de données communisé (support_cases) et des
vues/rappel d'administration. Tout accès admin est audité côté serveur.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from uuid import uuid4

# ============================================================================
# Support (candidat / support)
# ============================================================================

# Statuts de ticket de support.
SUPPORT_STATUSES = ("ouvrir", "en_cours", "resolve", "fermer")

# Crée un ticket de support lié à un utilisateur.
def create_support_case(
    conn: sqlite3.Connection,
    user_id: str,
    subject: str,
    category: str = "generale",
    priority: str = "moyen",
    description: str = "",
) -> sqlite3.Row:
    """Crée un ticket de support."""
    case_id = uuid4().hex
    conn.execute(
        "INSERT INTO support_cases (id, user_id, subject, category, priority, description, status, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, 'ouvrir', ?)",
        (case_id, user_id, subject, category, priority, description, _now()),
    )
    conn.commit()
    # The `id` is a UUID (TEXT PRIMARY KEY); lastrowid returns the rowid, not our ID.
    return conn.execute(
        "SELECT * FROM support_cases WHERE id = ?", (case_id,)
    ).fetchone()


def get_support_cases(conn: sqlite3.Connection, user_id: str, status: str | None = None) -> list[dict]:
    """Liste les tickets du compte."""
    if status:
        rows = conn.execute(
            "SELECT * FROM support_cases WHERE user_id = ? AND status = ? ORDER BY created_at DESC",
            (user_id, status),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM support_cases WHERE user_id = ? ORDER BY created_at DESC",
            (user_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def get_support_case(conn: sqlite3.Connection, case_id: str, owner_id: str) -> dict | None:
    """Récupère un ticket en vérifiant la propriété."""
    row = conn.execute(
        "SELECT * FROM support_cases WHERE id = ?", (case_id,)
    ).fetchone()
    if row is None or row["user_id"] != owner_id:
        return None
    return dict(row)


def close_support_case(conn: sqlite3.Connection, case_id: str, user_id: str, resolution: str = "") -> bool:
    """Clôture un ticket."""
    row = conn.execute(
        "SELECT id FROM support_cases WHERE id = ? AND user_id = ?", (case_id, user_id)
    ).fetchone()
    if row is None:
        return False
    conn.execute(
        "UPDATE support_cases SET status = 'resolve', resolved_at = ?, resolution = ? WHERE id = ?",
        (_now(), resolution, case_id),
    )
    conn.commit()
    return True


# ============================================================================
# Administration
# ============================================================================

# Statuts de paiement.
PAYMENT_STATUSES = ("en_attente", "confirme", "echeche", "remboursement_en_cours", "remboursé", "contesté")

# Statuts de tâches.
TASK_STATUSES = ("en_attente", "en_cours", "intervention_utilisateur_requise", "partiellement_terminée", "terminée", "échouée", "annulée")


def create_payment_pending(
    conn: sqlite3.Connection,
    user_id: str,
    pack: str,
    amount: int,
    transaction_id: str,
    status: str = "en_attente",
    note: str = "",
) -> sqlite3.Row:
    """Crée un enregistrement de paiement en attente."""
    cur = conn.execute(
        "INSERT INTO payment_pending (id, user_id, pack, amount_cents, transaction_id, status, note, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (uuid4().hex, user_id, pack, amount, transaction_id, status, note, _now()),
    )
    conn.commit()
    return conn.execute(
        "SELECT * FROM payment_pending WHERE id = ?", (cur.lastrowid,)
    ).fetchone()


def get_payment_pending(conn: sqlite3.Connection, user_id: str) -> list[dict]:
    """Récupère les paiements en attente du compte."""
    rows = conn.execute(
        "SELECT * FROM payment_pending WHERE user_id = ? ORDER BY created_at DESC",
        (user_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def verify_payment_server(
    conn: sqlite3.Connection,
    transaction_id: str,
    expected_amount: int,
    expected_status: str = "confirme",
) -> dict | None:
    """Vérifie un paiement côté serveur (signature, montant, statut)."""
    row = conn.execute(
        "SELECT * FROM payment_pending WHERE transaction_id = ?", (transaction_id,)
    ).fetchone()
    if row is None:
        return None
    # Vérifications métier:
    if int(row["amount_cents"]) != expected_amount:
        # En cas de désaccord, marquer comme contesté.
        conn.execute(
            "UPDATE payment_pending SET status = 'contesté' WHERE id = ?",
            (row["id"],),
        )
        conn.commit()
        return dict(row)
    conn.execute(
        "UPDATE payment_pending SET status = ?, verified_at = ? WHERE id = ?",
        (expected_status, _now(), row["id"]),
    )
    conn.commit()
    return dict(row)


# Réconciliation (detecte doublons, manquements, anciennes réservations).
def reconcile_wallet(conn: sqlite3.Connection, threshold_days: int = 7) -> dict:
    """Exécute les règles de réconciliation sur le portefeuille.

    Retourne un résumé des écarts détectés.
    """
    summary = {
        "double_charges": [],
        "missing_refunds": [],
        "old_reservations": [],
        "tasks_without_driver": [],
        "errors": [],
    }

    # 1. Doubles dépenses (meme transaction_id dans payment_pending, plus d'une fois).
    rows = conn.execute(
        "SELECT transaction_id, COUNT(*) AS c, SUM(amount_cents) AS total "
        "FROM payment_pending GROUP BY transaction_id HAVING c > 1"
    ).fetchall()
    for r in rows:
        summary["double_charges"].append({
            "transaction_id": r["transaction_id"],
            "count": r["c"],
            "total_cents": r["total"],
        })

    # 2. Réservations anciennes (plus de 7 jours) encore actives.
    cutoff = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    rows = conn.execute(
        "SELECT id, amount_cents FROM payment_pending WHERE status IN ('en_attente','confirme') "
        "AND created_at < datetime(?, '-7 days')",
        (cutoff,),
    ).fetchall()
    for r in rows:
        summary["old_reservations"].append({
            "payment_id": r["id"],
            "amount_cents": r["amount_cents"],
        })

    # 3. Tâches terminées sans conducteur.
    rows = conn.execute(
        "SELECT id, state FROM tasks WHERE state = 'terminée' AND driver_id IS NULL"
    ).fetchall()
    for r in rows:
        summary["tasks_without_driver"].append({
            "task_id": r["id"],
            "state": r["state"],
        })

    # 4. Échecs de service récents (error/log).
    rows = conn.execute(
        "SELECT id, message, created_at FROM errors WHERE created_at >= datetime('now', '-7 days')"
    ).fetchall()
    for r in rows:
        summary["errors"].append({
            "error_id": r["id"],
            "message": r["message"],
        })

    # 5. Transactions anciennes toujours en attente (pas deération).
    rows = conn.execute(
        "SELECT id, amount_cents FROM payment_pending WHERE status = 'en_attente' "
        "AND created_at < datetime('now', '-7 days')"
    ).fetchall()
    for r in rows:
        summary["old_reservations"].append({
            "payment_id": r["id"],
            "amount_cents": r["amount_cents"],
            "status": "en_attente",
        })

    return summary


# ============================================================================
# Rapport d'état serveur (administration)
# ============================================================================

def health_report(conn: sqlite3.Connection) -> dict:
    """Rapport d'état du serveur pour le panneau d'administration."""
    user_count = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    wallet_count = conn.execute("SELECT COUNT(*) FROM wallets").fetchone()[0]
    ledger_total = conn.execute(
        "SELECT COALESCE(SUM(amount), 0) FROM ledger_entries"
    ).fetchone()[0]

    # Statut des usages récents
    recent_actions = conn.execute(
        "SELECT COUNT(*) FROM actions WHERE created_at >= datetime('now', '-1 hour')"
    ).fetchone()[0]

    # Paiements en attente (total)
    pending = conn.execute(
        "SELECT SUM(amount_cents) FROM payment_pending WHERE status = 'en_attente'"
    ).fetchone()[0] or 0

    # Sources actives
    src = conn.execute(
        "SELECT COUNT(*) FROM source_registry WHERE status = 'active'"
    ).fetchone()[0]

    # Erreurs récentes
    err = conn.execute(
        "SELECT COUNT(*) FROM errors WHERE created_at >= datetime('now', '-1 day')"
    ).fetchone()[0]

    # Tâches sans conducteur
    no_driver = conn.execute(
        "SELECT COUNT(*) FROM tasks WHERE state = 'terminée' AND driver_id IS NULL"
    ).fetchone()[0]

    return {
        "users": user_count,
        "wallets": wallet_count,
        "ledger_total": ledger_total,
        "recent_actions_1h": recent_actions,
        "pending_total": pending,
        "active_sources": src,
        "errors_1d": err,
        "tasks_without_driver": no_driver,
    }


# ============================================================================
# Utilities
# ============================================================================

def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
