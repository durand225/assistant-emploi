"""Portefeuille de crédits — Ticket T03.

Règles :
- Un portefeuille par utilisateur ; un bonus de bienvenue (15 cr) unique par
  nouveau compte vérifié, jamais converti en argent.
- Le solde est la somme du journal (immuable). Les réservations sont des mises de
  côté atomiques avant un appel coûteux : elles ne se consomment que si le
  résultat est validé et sauvegardé.
- Réservation bornée, état terminal unique, clé d'idempotence par action.
- Aucun secret, aucun module externe : stdlib uniquement.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from uuid import uuid4

WELCOME_AMOUNT = 15

# Packs proposés pour le pilot (crédits / prix indicatif en FCFA). À activer une
# fois mesuré le coût de l'action (cf. PRD §27).
PACKS = {
    "essentiel": {"credits": 40, "price_fcma": 2000},
    "recherche_active": {"credits": 110, "price_fcma": 5000},
    "projet_emploi": {"credits": 240, "price_fcma": 10000},
}

STATUS_ACTIVE = "active"
STATUS_RELEASED = "released"
STATUS_CONSUMED = "consumed"

RESERVATION_STATUS = (STATUS_ACTIVE, STATUS_RELEASED, STATUS_CONSUMED)


class WalletError(Exception):
    """Erreur métier portefeuille (solde, état, idée)."""


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _uid() -> str:
    return uuid4().hex


# --------------------------------------------------------------------------- #
#  Portefeuille
# --------------------------------------------------------------------------- #
def create_wallet(conn: sqlite3.Connection, user_id: str) -> sqlite3.Row:
    """Crée le portefeuille d'un utilisateur (ou le retourne s'il existe déjà)."""
    wallet = get_wallet_by_user(conn, user_id)
    if wallet is not None:
        return wallet
    uid = _uid()
    conn.execute(
        "INSERT INTO wallets (id, user_id, created_at, updated_at) VALUES (?, ?, ?, ?)",
        (uid, user_id, _now(), _now()),
    )
    conn.commit()
    return get_wallet_by_user(conn, user_id)


def get_wallet_by_user(conn: sqlite3.Connection, user_id: str) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM wallets WHERE user_id = ?", (user_id,)).fetchone()


def get_wallet_by_id(conn: sqlite3.Connection, wallet_id: str) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM wallets WHERE id = ?", (wallet_id,)).fetchone()


def credit_balance(conn: sqlite3.Connection, wallet_id: str) -> int:
    """Solde total inscrit dans le journal (source de vérité)."""
    row = conn.execute(
        "SELECT COALESCE(SUM(amount), 0) AS s FROM ledger_entries WHERE wallet_id = ?",
        (wallet_id,),
    ).fetchone()
    return int(row["s"])


def available_balance(conn: sqlite3.Connection, wallet_id: str) -> int:
    """Crédits disponibles = total moins les réservations en cours."""
    row = conn.execute(
        "SELECT COALESCE(SUM(amount), 0) AS s FROM reservations "
        "WHERE wallet_id = ? AND status = ?",
        (wallet_id, STATUS_ACTIVE),
    ).fetchone()
    active = int(row["s"])
    return credit_balance(conn, wallet_id) - active


# --------------------------------------------------------------------------- #
#  Bonus de bienvenue (unique, +15)
# --------------------------------------------------------------------------- #
def grant_welcome(conn: sqlite3.Connection, user_id: str) -> dict:
    """Octroi unique de 15 crédits pour un compte vérifié, jamais refait.

    Crée le portefeuille si absent, puis :
    - ne fait rien si l'utilisateur n'est pas vérifié ;
    - ne fait rien si le bonus est déjà octroyé.
    """
    user = conn.execute(
        "SELECT email_verified_at FROM users WHERE id = ?", (user_id,)
    ).fetchone()
    if user is None or user["email_verified_at"] is None:
        return {"granted": False, "reason": "compte_non_verifie"}

    wallet = get_wallet_by_user(conn, user_id)
    if wallet is None:
        create_wallet(conn, user_id)
        wallet = get_wallet_by_user(conn, user_id)

    if wallet is None or wallet["welcome_granted"]:
        return {"granted": False, "reason": "deja_octroie" if wallet else "utilisateur_inconnu"}

    conn.execute(
        "UPDATE wallets SET welcome_granted = 1, updated_at = ? WHERE id = ?",
        (_now(), wallet["id"]),
    )
    lot_id = _uid()
    conn.execute(
        "INSERT INTO credit_lots (id, wallet_id, kind, amount) VALUES (?, ?, 'welcome', ?)",
        (lot_id, wallet["id"], WELCOME_AMOUNT),
    )
    conn.execute(
        "INSERT INTO ledger_entries (id, wallet_id, amount, lot_id, description) "
        "VALUES (?, ?, ?, ?, 'bonus de bienvenue T03')",
        (_uid(), wallet["id"], WELCOME_AMOUNT, lot_id),
    )
    conn.commit()
    return {"granted": True, "amount": WELCOME_AMOUNT}


# --------------------------------------------------------------------------- #
#  Réservations (atomiques, idempotentes)
# --------------------------------------------------------------------------- #
def reserve_credits(
    conn: sqlite3.Connection, wallet_id: str, amount: int, key: str
) -> dict:
    """Réserve `amount` crédits de façon atomique.

    Retourne la réservation `active` si le solde disponible suffit, ou
    `INSUFFICIENT_CREDITS`. Un `key` répété retourne la même réservation sans
    débit supplémentaire.
    """
    if amount <= 0:
        return {"ok": False, "reason": "montant_invalide"}

    conn.execute("BEGIN IMMEDIATE")
    try:
        available = available_balance(conn, wallet_id)
        if available < amount:
            conn.execute("ROLLBACK")
            return {"ok": False, "reason": "INSUFFICIENT_CREDITS"}

        existing = conn.execute(
            "SELECT id FROM reservations "
            "WHERE wallet_id = ? AND key = ? AND status = ?",
            (wallet_id, key, STATUS_ACTIVE),
        ).fetchone()
        if existing is not None:
            conn.execute("COMMIT")
            return {"ok": True, "reservation_id": existing["id"], "duplicate": True}

        rid = _uid()
        conn.execute(
            "INSERT INTO reservations (id, wallet_id, amount, key, status, created_at) "
            "VALUES (?, ?, ?, ?, 'active', ?)",
            (rid, wallet_id, amount, key, _now()),
        )
        conn.commit()
        return {"ok": True, "reservation_id": rid, "amount": amount}
    except Exception:
        conn.execute("ROLLBACK")
        raise


def release_reservation(conn: sqlite3.Connection, reservation_id: str) -> dict:
    """Libère une réservation en échec (sans débit, car la réservation n'a pas été
    consommée)."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        cur = conn.execute(
            "UPDATE reservations SET status = ? WHERE id = ? AND status = ?",
            (STATUS_RELEASED, reservation_id, STATUS_ACTIVE),
        )
        if cur.rowcount == 0:
            conn.execute("ROLLBACK")
            return {"ok": False, "reason": "deja_livre"}
        conn.commit()
        return {"ok": True}
    except Exception:
        conn.execute("ROLLBACK")
        raise


def consume_reservation(conn: sqlite3.Connection, reservation_id: str) -> dict:
    """Consomme une réservation validée : débit du journal et état 'consumed'.

    Utilisé uniquement quand le résultat est sûr d'être livré.
    """
    conn.execute("BEGIN IMMEDIATE")
    try:
        res = conn.execute(
            "SELECT amount, wallet_id, status FROM reservations WHERE id = ?",
            (reservation_id,),
        ).fetchone()
        if res is None or res["status"] != STATUS_ACTIVE:
            conn.execute("ROLLBACK")
            return {"ok": False, "reason": "reservation_invalide"}

        amount = int(res["amount"])
        conn.execute(
            "INSERT INTO ledger_entries (id, wallet_id, amount, description) "
            "VALUES (?, ?, ?, 'consommation réservation T03')",
            (_uid(), res["wallet_id"], -amount),
        )
        conn.execute(
            "UPDATE reservations SET status = ? WHERE id = ?",
            (STATUS_CONSUMED, reservation_id),
        )
        conn.commit()
        return {"ok": True, "amount": amount}
    except Exception:
        conn.execute("ROLLBACK")
        raise


def release_all_active(conn: sqlite3.Connection, wallet_id: str) -> int:
    """Libère toutes les réservations actives d'un portefeuille (nettoyage)."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        cur = conn.execute(
            "UPDATE reservations SET status = ? WHERE wallet_id = ? AND status = ?",
            (STATUS_RELEASED, wallet_id, STATUS_ACTIVE),
        )
        released = cur.rowcount
        conn.commit()
        return released
    except Exception:
        conn.execute("ROLLBACK")
        raise


# --------------------------------------------------------------------------- #
#  Paiements / réconciliation
# --------------------------------------------------------------------------- #
def create_payment_pending(
    conn: sqlite3.Connection, wallet_id: str, pack: str, amount_cents: int, transaction_id: str
) -> sqlite3.Row:
    """Crée une commande de paiement en attente."""
    uid = _uid()
    conn.execute(
        "INSERT INTO payment_pending (id, user_id, pack, amount_cents, transaction_id, status, created_at) "
        "VALUES (?, ?, ?, ?, ?, 'en_attente', ?)",
        (uid, wallet_id, pack, amount_cents, transaction_id, _now()),
    )
    conn.commit()
    return get_payment_pending(conn, uid)


def get_payment_pending(conn: sqlite3.Connection, transaction_id: str) -> sqlite3.Row | None:
    """Récupère une commande de paiement par transaction_id."""
    return conn.execute(
        "SELECT * FROM payment_pending WHERE transaction_id = ?", (transaction_id,)
    ).fetchone()


def update_payment_pending(
    conn: sqlite3.Connection, transaction_id: str, status: str, note: str = ""
) -> sqlite3.Row | None:
    """Met à jour le statut d'une commande de paiement."""
    conn.execute(
        "UPDATE payment_pending SET status = ?, note = ?, verified_at = ? WHERE transaction_id = ?",
        (status, note, _now(), transaction_id),
    )
    conn.commit()
    return get_payment_pending(conn, transaction_id)


def create_credit_lot(
    conn: sqlite3.Connection, wallet_id: str, lot_id: str, kind: str, amount: int
) -> sqlite3.Row:
    """Crée un lot de crédits (welcome ou purchase)."""
    conn.execute(
        "INSERT INTO credit_lots (id, wallet_id, kind, amount) VALUES (?, ?, ?, ?)",
        (lot_id, wallet_id, kind, amount),
    )
    conn.commit()
    return get_latest_credit_lot(conn, wallet_id, lot_id)


def get_latest_credit_lot(conn: sqlite3.Connection, wallet_id: str, lot_id: str) -> sqlite3.Row | None:
    """Récupère un lot de crédits précis d'un portefeuille."""
    return conn.execute(
        "SELECT * FROM credit_lots WHERE id = ? AND wallet_id = ?", (lot_id, wallet_id)
    ).fetchone()


def get_ledger(conn: sqlite3.Connection, wallet_id: str) -> list[sqlite3.Row]:
    """Retourne l'historique complet des mouvements comptables du portefeuille."""
    return conn.execute(
        """
        SELECT id, wallet_id, amount, lot_id, description, key, created_at
        FROM ledger_entries
        WHERE wallet_id = ?
        ORDER BY created_at DESC
        """,
        (wallet_id,),
    ).fetchall()


def set_payment_env(conn: sqlite3.Connection, env: str) -> None:
    """Définit l'environnement de paiement (production/sandbox)."""
    conn.execute(
        "INSERT INTO _payment_env (env) VALUES (?) ON CONFLICT DO UPDATE SET env = excluded.env",
        (env,),
    )
    conn.commit()


def get_payment_env(conn: sqlite3.Connection) -> str | None:
    """Récupère l'environnement de paiement (production/sandbox)."""
    ctx = conn.execute(
        "SELECT env FROM _payment_env ORDER BY id DESC LIMIT 1"
    ).fetchone()
    return ctx[0] if ctx else "production"


def set_payment_env(conn: sqlite3.Connection, env: str) -> None:
    """Définit l'environnement de paiement (production/sandbox)."""
    conn.execute(
        "INSERT INTO _payment_env (env) VALUES (?) ON CONFLICT DO UPDATE SET env = excluded.env",
        (env,),
    )
    conn.commit()


def get_payment_env(conn: sqlite3.Connection) -> str | None:
    """Récupère l'environnement de paiement (production/sandbox)."""
    ctx = conn.execute(
        "SELECT env FROM _payment_env ORDER BY id DESC LIMIT 1"
    ).fetchone()
    return ctx[0] if ctx else "production"
