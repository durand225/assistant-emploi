"""Paiement GeniusPay, réconciliation de crédits et gestion du portefeuille — T10.

Rôle :
- Intégrer le flux de paiement GeniusPay (checkout, confirmation, lapidation).
- Créer un lot de credits à la confirmation.
- Gérer la réconciliation (paiement répété, ancien notification).
- Garantir que l'utilisateur ne perde pas de crédit si le paiement est rejeté.
- Contrôler l'accès : seuls le serveur et le portail publié font autorité.

Règles appliquées (PRD) :
- Un paiement confirmé crédite un lot unique, jamais deux fois.
- Un paiement non confirmé reste en attente, sans crédit.
- Une ancienne notification n'appauvit pas une commande déjà confirmée.
- Le remboursement est un événement distinct et audité.
- Hermes (candidat) ne voit jamais les secrets marchand.
"""

from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Optional

from . import accounts
from . import wallet as wmod
from . import schemas as s


# ---------------------------------------------------------------------------
# Événements de paiement (commun à backend et service)
# ---------------------------------------------------------------------------

class PaymentEvent:
    """Événement de paiement à destination du service de réconciliation."""

    EVENT_TYPES = ("checkout_started", "checkout_confirmed", "payment_approved",
                   "payment_rejected", "refunded", "reconciled")

    def __init__(
        self,
        *,
        event_type: str,
        user_id: str,
        pack: str,
        amount_cents: int,
        transaction_id: str | None = None,
        status: str = "pending",
        note: str = "",
    ):
        if event_type not in self.EVENT_TYPES:
            raise ValueError(f"type d'événement inconnu : {event_type}")
        self.event_type = event_type
        self.user_id = user_id
        self.pack = pack
        self.amount_cents = amount_cents
        self.transaction_id = transaction_id
        self.status = status
        self.note = note
        self.created_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    def to_dict(self) -> dict:
        return {
            "event_type": self.event_type,
            "user_id": self.user_id,
            "pack": self.pack,
            "amount_cents": self.amount_cents,
            "transaction_id": self.transaction_id,
            "status": self.status,
            "note": self.note,
            "created_at": self.created_at,
        }


# ---------------------------------------------------------------------------
# Gestion du portefeuille et des lots
# ---------------------------------------------------------------------------

class WalletManager:
    """Gère le portefeuille, les lots et la réconciliation des crédits."""

    def __init__(self, conn: sqlite3.Connection, user_id: str):
        self.conn = conn
        self.user_id = user_id

    def ensure_wallet(self) -> sqlite3.Row:
        """Crée un portefeuille si l'utilisateur en n'en a pas."""
        wh = wmod.get_wallet_by_user(self.conn, self.user_id)
        if wh is None:
            wh = wmod.create_wallet(self.conn, self.user_id)
        return wh

    def credit_balance(self, amount: int, description: str, lot_id: str) -> None:
        """Ajoute des crédits au portefeuille via un lot et un journaux."""
        wh = self.ensure_wallet()
        # Créer un lot (si absent) et inscrire le compteur du journal
        wmod.create_credit_lot(self.conn, wh["id"], lot_id, "purchase", amount)
        # Inscrire le débit/crédit dans le journal
        from .wallet import _uid
        conn = self.conn
        conn.execute(
            "INSERT INTO ledger_entries (id, wallet_id, amount, lot_id, description) "
            "VALUES (?, ?, ?, ?, ?)",
            (_uid(), wh["id"], amount, lot_id, description),
        )
        conn.commit()

    def reserve_credits(self, amount: int, key: str, description: str) -> Optional[str]:
        """Réserve des crédits pour une action. Retourne l'ID de réservation."""
        wh = self.ensure_wallet()
        if wmod.get_balance(self.conn, wh["id"]) < amount:
            return None
        return wmod.reserve_credits(self.conn, wh["id"], amount, key, description)

    def release_reservation(self, reservation_id: str) -> None:
        """Libère une réservation après échec ou annulation."""
        wmod.release_reservation(self.conn, reservation_id)

    def consume_reservation(self, reservation_id: str) -> None:
        """Consomme une réservation après validation du résultat."""
        wmod.consume_reservation(self.conn, reservation_id)

    def grant_welcome(self) -> bool:
        """Accorde le bonus de bienvenue (15 crédits) une seule fois après vérification."""
        # Vérifier que le compte est vérifié
        status = accounts.get_verification_status(self.conn, self.user_id)
        if not status.get("email_verified", False):
            return False

        wh = self.ensure_wallet()
        # Vérifier que le solde est à 0 (bonus unique)
        if wmod.credit_balance(self.conn, wh["id"]) > 0:
            return False

        # Créer un lot de bienvenue unique
        lot_id = f"welcome_{self.user_id}_{uuid.uuid4().hex[:8]}"
        wmod.create_credit_lot(self.conn, wh["id"], lot_id, "welcome", 15)
        # Inscrire le crédit dans le journal
        from .wallet import _uid
        self.conn.execute(
            "INSERT INTO ledger_entries (id, wallet_id, amount, lot_id, description) "
            "VALUES (?, ?, ?, ?, ?)",
            (_uid(), wh["id"], 15, lot_id, "bonus de bienvenue T03"),
        )
        self.conn.commit()
        return True

    def get_balance(self) -> int:
        wh = self.ensure_wallet()
        return wmod.credit_balance(self.conn, wh["id"])

    def get_ledger(self) -> list[dict]:
        wh = self.ensure_wallet()
        rows = wmod.get_ledger(self.conn, wh["id"])
        return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Intégration GeniusPay (checkout, confirmation, lapidation)
# ---------------------------------------------------------------------------

class GeniusPayService:
    """Service d'intégration GeniusPay (simulation pour MVP).

    En production, ce service appelle l'API GeniusPay via un réseau privé
    et utilise les secrets du serveur uniquement.
    """

    ORDER_TIMEOUT_SECONDS = 300  # 5 minutes pour le paiement
    MAX_RETRY = 3

    def __init__(self, conn: sqlite3.Connection, user_id: str):
        self.conn = conn
        self.user_id = user_id
        self.wallet = WalletManager(conn, user_id)

    def checkout(self, pack: str, amount_cents: int) -> dict:
        """Démarre un checkout GeniusPay."""
        if not isinstance(pack, str) or pack.strip() == "" or amount_cents <= 0:
            return {"status": "error", "message": "Paiement invalide"}

        # Vérifier les permissions sur l'utilisateur
        status = accounts.get_verification_status(self.conn, self.user_id)
        if not status.get("email_verified", False):
            return {"status": "error", "message": "Compte non vérifié"}

        # Créer la commande de paiement
        cmd_id = uuid.uuid4().hex
        from .wallet import create_payment_pending
        create_payment_pending(
            self.conn, self.wallet.ensure_wallet()["id"], pack, amount_cents, cmd_id
        )

        return {
            "status": "ok",
            "command_id": cmd_id,
            "pack": pack,
            "amount_cents": amount_cents,
            "state": "en_attente",
            "timeout_seconds": self.ORDER_TIMEOUT_SECONDS,
        }

    def confirm_payment(self, command_id: str) -> dict:
        """Confirmation d'un paiement via GeniusPay.

        Utilisé par le backend après notification de GeniusPay.
        Idempotent : un paiement déjà confirmé ne crée pas de lot en double.
        """
        row = wmod.get_payment_pending(self.conn, command_id)
        if row is None:
            return {"status": "error", "message": "Commande introuvable"}

        if row["status"] != "en_attente":
            # Déjà traité (verified) => retour ok sans nouveau lot
            if row["status"] == "verified":
                return {"status": "ok", "message": "Déjà traité", "lot_id": row.get("lot_id")}
            return {"status": "ok", "message": "Déjà traité"}

        # Valider le montant et l'environnement
        if not self._validate_payment(row):
            return {"status": "rejected", "message": "Signature ou montant invalide"}

        # Créer le lot de crédits et débiter le portefeuille (via WalletManager)
        lot_id = f"pay_{self.user_id}_{uuid.uuid4().hex}"
        wh = self.wallet.ensure_wallet()
        self.wallet.credit_balance(
            row["amount_cents"], f"Paiement GeniusPay - pack {row['pack']}", lot_id
        )

        # Mettre à jour le statut
        wmod.update_payment_pending(self.conn, command_id, "verified", "")

        return {"status": "ok", "message": "Paiement confirmé", "lot_id": lot_id}

    def _validate_payment(self, row: sqlite3.Row) -> bool:
        """Valide signature, montant, environnement. Pas de secret en dur."""
        # Vérification de l'environnement (sandbox vs production)
        # Ici: pas de secret en dur, les variables d'environnement le définissent.
        env = wmod.get_payment_env(self.conn) or "production"
        if env == "sandbox":
            # Pas d'effet sur la production
            return True

        # Vérification de la signature depuis le champ note (simulation)
        # sqlite3.Row n'a pas de .get() : on utilise row["note"]
        signature = row["note"] if "note" in row.keys() else row["note"] or ""
        if not signature or len(signature) < 8:
            return False

        # Vérification du montant (doit être positif et > 0)
        if row["amount_cents"] <= 0:
            return False

        return True

    def reconcile(self, command_id: str) -> dict:
        """Réconciliation d'un paiement (réessai, ancienne notification)."""
        row = wmod.get_payment_pending(self.conn, command_id)
        if row is None:
            return {"status": "error", "message": "Commande introuvable"}

        if row["status"] == "verified":
            # Déjà confirmé, pas de nouveau lot
            return {"status": "ok", "message": "Déjà confirmé"}

        # Réessayer la confirmation
        result = self.confirm_payment(command_id)
        return result

    def is_payment_verified(self, command_id: str) -> bool:
        row = wmod.get_payment_pending(self.conn, command_id)
        return row is not None and row["status"] == "verified"


# ---------------------------------------------------------------------------
# Événements de réconciliation et de remboursement
# ---------------------------------------------------------------------------

class ReconciliationService:
    """Gère la réconciliation et le remboursement (audités)."""

    def __init__(self, conn: sqlite3.Connection, user_id: str):
        self.conn = conn
        self.user_id = user_id

    def reconcile_order(self, order_id: str, reason: str = "") -> dict:
        """Réconcilie une commande (nouveau paiement, ancienne notification)."""
        # Récupérer la commande de paiement
        row = wmod.get_payment_pending(self.conn, order_id)
        if row is None:
            return {"status": "error", "message": "Commande introuvable"}

        # Vérifier que ce n'est pas déjà réconcilié
        if row["status"] == "verified":
            return {"status": "ok", "message": "Déjà réconcilié"}

        # Réconciliation: on crée un nouvel événement
        from . import source_registry as sreg
        evt = PaymentEvent(
            event_type="reconciled",
            user_id=self.user_id,
            pack=row["pack"],
            amount_cents=row["amount_cents"],
            transaction_id=order_id,
            status="reconciled",
            note=reason,
        )
        self._log_event(evt)
        return {"status": "ok", "message": "Réconciliation effectuée"}

    def process_refund(self, command_id: str, amount_cents: int) -> dict:
        """Traite un remboursement (événement distinct)."""
        row = wmod.get_payment_pending(self.conn, command_id)
        if row is None:
            return {"status": "error", "message": "Commande introuvable"}

        if amount_cents > row["amount_cents"]:
            return {"status": "error", "message": "Montant de remboursement invalide"}

        # Créer l'event de remboursement
        from . import source_registry as sreg
        evt = PaymentEvent(
            event_type="refunded",
            user_id=self.user_id,
            pack=row["pack"],
            amount_cents=amount_cents,
            transaction_id=command_id,
            status="refunded",
            note="Remboursement demandé",
        )
        self._log_event(evt)
        return {"status": "ok", "message": "Remboursement traité"}

    def _log_event(self, evt: PaymentEvent) -> None:
        """Log l'événement de paiement (simulé pour MVP)."""
        pass


# ---------------------------------------------------------------------------
# Vérifications complémentaires
# ---------------------------------------------------------------------------

def validate_payment_request(pack: str, amount_cents: int) -> bool:
    """Vérifie qu'une requête de paiement est valide."""
    if not pack or not isinstance(pack, str) or pack.strip() == "":
        return False
    if not isinstance(amount_cents, int) or amount_cents <= 0:
        return False
    return True
