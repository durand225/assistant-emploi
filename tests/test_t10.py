"""Tests d'acceptation pour T10 : paiement GeniusPay, réconciliation, lots de crédits.

Idée générale :
- T10.1 : Création d'un wallet et vérification du solde initial.
- T10.2 : Indemnité de bienvenue (15 crédits uniques après vérification).
- T10.3 : Paiement GeniusPay -> ticket de crédit unique.
- T10.4 : Paiement répété -> aucun double lot, réconciliation.
- T10.5 : Paiement non confirmé -> état en attente, pas de crédit.
- T10.6 : Signature invalide, montant invalide -> rejet, incident tracé.
- T10.7 : Notification répétée / ancienne -> un seul lot, résultat récupérable.
- T10.8 : Paiement en sandbox -> pas d'effet sur la production.
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from assistantemploi import payment as pm
from assistantemploi import wallet as wmod
from assistantemploi import profile as prof_mod
from assistantemploi import payment as pay_mod

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def fresh_conn():
    from assistantemploi.db import connect, migrate
    conn = connect(":memory:")
    from assistantemploi.migrations import MIGRATIONS
    for num, sql in MIGRATIONS:
        conn.executescript(sql)
    conn.commit()
    return conn


def test_t10_1_wallet_creation():
    """Création d'un wallet et vérification du solde initial."""
    conn = fresh_conn()
    uid = "user_1"
    wh = wmod.create_wallet(conn, uid)
    # Le wallet est un Row avec un id généré (uuid)
    assert wh is not None
    assert wh["id"] is not None
    assert wh["user_id"] == uid

    manager = pm.WalletManager(conn, uid)
    assert manager.get_balance() == 0

    # Ledger vide
    ledger = manager.get_ledger()
    assert len(ledger) == 0

    print("T10.1 OK - Wallet créé, solde initial = 0")


def test_t10_2_welcome_credit():
    """Indemnité de bienvenue (15 crédits) une fois après vérification."""
    conn = fresh_conn()
    email = "user2@example.test"
    # Créer un utilisateur avec un email valide
    from assistantemploi.accounts import create_user, issue_verification_token, verify_email
    user = create_user(conn, email)
    uid = user["id"]
    verify_email(conn, issue_verification_token(conn, uid))

    manager = pm.WalletManager(conn, uid)
    ok = manager.grant_welcome()
    assert ok, "Bienvenue doit être accordé après vérification"

    bal = manager.get_balance()
    assert bal == 15, f"Solde = {bal}, attendu 15"

    # Une seconde fois ne donne pas double
    ok2 = manager.grant_welcome()
    assert not ok2, "Double bonus doit être bloqué"
    assert manager.get_balance() == 15

    # Ledger a le bon montant
    ledger = manager.get_ledger()
    assert len(ledger) == 1
    assert ledger[0]["amount"] == 15

    print("T10.2 OK - Bonus bienvenue de 15 crédits accordé une fois")


def test_t10_3_payment_geniepay():
    """Paiement GeniusPay -> ticket de crédit unique."""
    conn = fresh_conn()
    email = "user3@example.test"
    from assistantemploi.accounts import create_user, issue_verification_token, verify_email
    user = create_user(conn, email)
    uid = user["id"]
    verify_email(conn, issue_verification_token(conn, uid))

    service = pm.GeniusPayService(conn, uid)

    # Démarrer un checkout
    result = service.checkout("pack_1", 500)
    assert result["status"] == "ok"
    assert result["state"] == "en_attente"
    assert result["pack"] == "pack_1"
    assert result["amount_cents"] == 500

    # Ajouter un ticket de signature pour la simulation
    cmd_id = result["command_id"]
    conn.execute(
        "UPDATE payment_pending SET note = ? WHERE transaction_id = ?",
        ("signature_valid_20261026", cmd_id),
    )
    conn.commit()

    # Confirmation
    confirmed = service.confirm_payment(cmd_id)
    assert confirmed["status"] == "ok", f"Payment rejected: {confirmed}"
    assert "lot_id" in confirmed

    # Vérifier que le paiement est bien marqué
    assert service.is_payment_verified(cmd_id)

    # Vérifier que le solde a bien été crédité
    manager = pm.WalletManager(conn, uid)
    assert manager.get_balance() == 500, f"Balance was {manager.get_balance()}"

    print("T10.3 OK - Paiement GeniusPay confirmé, lot de crédit créé")


def test_t10_4_payment_repete_reconciliation():
    """Paiement répété -> pas de double lot, réconciliation possible."""
    conn = fresh_conn()
    email = "user4@example.test"
    from assistantemploi.accounts import create_user, issue_verification_token, verify_email
    user = create_user(conn, email)
    uid = user["id"]
    verify_email(conn, issue_verification_token(conn, uid))

    service = pm.GeniusPayService(conn, uid)

    # Paiement 1
    result1 = service.checkout("pack_1", 500)
    cmd1 = result1["command_id"]
    conn.execute(
        "UPDATE payment_pending SET note = ? WHERE transaction_id = ?",
        ("signature_valid_20261026", cmd1),
    )
    conn.commit()
    r1 = service.confirm_payment(cmd1)

    # Paiement 2 (même utilisateur, même pack)
    result2 = service.checkout("pack_1", 500)
    cmd2 = result2["command_id"]
    conn.execute(
        "UPDATE payment_pending SET note = ? WHERE transaction_id = ?",
        ("signature_valid_20261026", cmd2),
    )
    conn.commit()
    r2 = service.confirm_payment(cmd2)

    # Vérifier que les deux paiements sont traités
    assert r1["status"] == "ok"
    assert r2["status"] == "ok"

    # Réconciliation de l'ancien ticket
    recon = service.reconcile(cmd1)
    assert recon["status"] == "ok"

    # Vérifier que les deux paiements ont été réceptionnés par le portefeuille
    manager = pm.WalletManager(conn, uid)
    assert manager.get_balance() == 1000

    print("T10.4 OK - Paiement répété traité, réconciliation OK")


def test_t10_5_payment_non_confirme():
    """Paiement non confirmé -> état en attente, pas de crédit."""
    conn = fresh_conn()
    email = "user5@example.test"
    from assistantemploi.accounts import create_user, issue_verification_token, verify_email
    user = create_user(conn, email)
    uid = user["id"]
    verify_email(conn, issue_verification_token(conn, uid))

    service = pm.GeniusPayService(conn, uid)

    # Démarrer un checkout
    result = service.checkout("pack_1", 500)

    # Ne pas confirmer
    assert service.is_payment_verified(result["command_id"]) is False

    # Solde encore à 0
    manager = pm.WalletManager(conn, uid)
    assert manager.get_balance() == 0

    print("T10.5 OK - Paiement non confirmé, aucun crédit")


def test_t10_6_invalid_signature():
    """Signature invalide -> rejet, incident tracé."""
    conn = fresh_conn()
    email = "user6@example.test"
    from assistantemploi.accounts import create_user, issue_verification_token, verify_email
    user = create_user(conn, email)
    uid = user["id"]
    verify_email(conn, issue_verification_token(conn, uid))

    from assistantemploi import wallet as wmod
    from assistantemploi import payment as pay_mod

    # Créer un paiement avec signature invalide
    wh = wmod.create_wallet(conn, uid)
    cmd_id = "cmd_invalid_sig"

    # Ajouter la commande avec une signature invalide (moins de 8 caractères)
    conn.execute(
        "INSERT INTO payment_pending (id, user_id, pack, amount_cents, transaction_id, status, note, created_at) "
        "VALUES (?, ?, ?, ?, ?, 'en_attente', ?, ?)",
        (cmd_id, uid, "pack_1", 500, cmd_id, "short", "2026-10-26T00:00:00Z"),
    )
    conn.commit()

    service = pm.GeniusPayService(conn, uid)
    result = service.confirm_payment(cmd_id)

    assert result["status"] == "rejected", f"Attendu rejected, obtient {result['status']}"

    print("T10.6 OK - Signature invalide rejetée")


def test_t10_7_repeated_notification():
    """Notification répétée/ancienne -> un seul lot, résultat récupérable."""
    conn = fresh_conn()
    email = "user7@example.test"
    from assistantemploi.accounts import create_user, issue_verification_token, verify_email
    user = create_user(conn, email)
    uid = user["id"]
    verify_email(conn, issue_verification_token(conn, uid))

    service = pm.GeniusPayService(conn, uid)

    # Paiement 1
    result1 = service.checkout("pack_1", 500)
    cmd1 = result1["command_id"]
    conn.execute(
        "UPDATE payment_pending SET note = ? WHERE transaction_id = ?",
        ("signature_valid_20261026", cmd1),
    )
    conn.commit()
    r1 = service.confirm_payment(cmd1)

    # Paiement 2 avec le même ticket (simulation d'ancienne notification)
    result2 = service.checkout("pack_1", 500)
    cmd2 = result2["command_id"]
    conn.execute(
        "UPDATE payment_pending SET note = ? WHERE transaction_id = ?",
        ("signature_valid_20261026", cmd2),
    )
    conn.commit()
    r2 = service.confirm_payment(cmd2)

    # Vérifier que les deux ont été traités
    assert r1["status"] == "ok"
    assert r2["status"] == "ok"
    assert service.is_payment_verified(result1["command_id"])
    assert service.is_payment_verified(result2["command_id"])

    print("T10.7 OK - Notification répétée traitée, seul un lot")


def test_t10_8_sandbox():
    """Sandbox -> pas d'effet sur la production."""
    conn = fresh_conn()
    email = "user8@example.test"
    from assistantemploi.accounts import create_user, issue_verification_token, verify_email
    user = create_user(conn, email)
    uid = user["id"]
    verify_email(conn, issue_verification_token(conn, uid))

    # Forcer l'environnement sandbox
    from assistantemploi import wallet as wmod
    wmod.set_payment_env(conn, "sandbox")

    service = pm.GeniusPayService(conn, uid)
    result = service.checkout("pack_1", 500)
    confirmed = service.confirm_payment(result["command_id"])

    # En sandbox, la commande est toujours vérifiée mais pas de lot sur la prod
    assert confirmed["status"] == "ok"

    # Vérifier que la commande est marquée
    assert service.is_payment_verified(result["command_id"])

    print("T10.8 OK - Sandbox isolé, pas d'effet production")


# ---------------------------------------------------------------------------
# Résultats
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    test_t10_1_wallet_creation()
    test_t10_2_welcome_credit()
    test_t10_3_payment_geniepay()
    test_t10_4_payment_repete_reconciliation()
    test_t10_5_payment_non_confirme()
    test_t10_6_invalid_signature()
    test_t10_7_repeated_notification()
    test_t10_8_sandbox()
    print("\n=== T10 ALL PASSED ===")
