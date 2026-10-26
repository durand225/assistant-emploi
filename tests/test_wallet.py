"""Tests du ticket T03 — portefeuille, lots, journal, réservations, bonus bienvenue.

Les fonctions du portefeuille s'appuient sur l'identifiant de portefeuille
(wallet_id). Un utilisateur possède au plus un portefeuille, donc on récupère
l'identifiant via `create_wallet()` ou `get_wallet_by_user()` avant de réserver.
"""

import sqlite3
import unittest

from assistantemploi.accounts import create_user, issue_verification_token, verify_email
from assistantemploi.db import connect, migrate
from assistantemploi.wallet import (
    WELCOME_AMOUNT,
    available_balance,
    create_wallet,
    consume_reservation,
    credit_balance,
    get_wallet_by_user,
    grant_welcome,
    release_reservation,
    reserve_credits,
)

EMAIL = "c@exemple.test"


class WalletLayerTests(unittest.TestCase):
    def setUp(self):
        self.conn = connect(":memory:")
        migrate(self.conn)

    def tearDown(self):
        self.conn.close()

    def _register_and_verify(self):
        user = create_user(self.conn, EMAIL)
        token = issue_verification_token(self.conn, user["id"])
        self.assertTrue(verify_email(self.conn, token)["verified"])
        return user

    # --- Portefeuille -------------------------------------------------------

    def test_wallet_created_with_zero_balance(self):
        user = create_user(self.conn, EMAIL)
        wallet = create_wallet(self.conn, user["id"])
        self.assertTrue(wallet["id"])
        self.assertEqual(credit_balance(self.conn, wallet["id"]), 0)
        self.assertEqual(available_balance(self.conn, wallet["id"]), 0)

    def test_create_wallet_idempotent_per_user(self):
        user = create_user(self.conn, EMAIL)
        w1 = create_wallet(self.conn, user["id"])
        w2 = create_wallet(self.conn, user["id"])
        self.assertEqual(w1["id"], w2["id"])

    # --- Bonus de bienvenue --------------------------------------------------

    def test_grant_welcome_unverified_is_noop(self):
        user = create_user(self.conn, EMAIL)
        wallet = create_wallet(self.conn, user["id"])
        res = grant_welcome(self.conn, user["id"])
        self.assertFalse(res["granted"])
        self.assertEqual(credit_balance(self.conn, wallet["id"]), 0)

    def test_grant_welcome_verified_is_15_once(self):
        user = self._register_and_verify()
        wallet = create_wallet(self.conn, user["id"])
        res = grant_welcome(self.conn, user["id"])
        self.assertTrue(res["granted"])
        self.assertEqual(credit_balance(self.conn, wallet["id"]), WELCOME_AMOUNT)
        self.assertEqual(get_wallet_by_user(self.conn, user["id"])["welcome_granted"], 1)

    def test_grant_welcome_idempotent(self):
        user = self._register_and_verify()
        wallet = create_wallet(self.conn, user["id"])
        first = grant_welcome(self.conn, user["id"])
        self.assertTrue(first["granted"])
        second = grant_welcome(self.conn, user["id"])
        self.assertFalse(second["granted"])
        self.assertEqual(credit_balance(self.conn, wallet["id"]), WELCOME_AMOUNT)

    # --- Réservations -------------------------------------------------------

    def test_reserve_insufficient_is_rejected(self):
        user = self._register_and_verify()
        wallet = create_wallet(self.conn, user["id"])
        grant_welcome(self.conn, user["id"])
        res = reserve_credits(self.conn, wallet["id"], 50, "K1")
        self.assertFalse(res["ok"])
        self.assertEqual(res["reason"], "INSUFFICIENT_CREDITS")
        self.assertEqual(credit_balance(self.conn, wallet["id"]), WELCOME_AMOUNT)

    def test_reserve_sufficient_and_key_idempotent(self):
        user = self._register_and_verify()
        wallet = create_wallet(self.conn, user["id"])
        grant_welcome(self.conn, user["id"])
        first = reserve_credits(self.conn, wallet["id"], 5, "K1")
        self.assertTrue(first["ok"])
        dup = reserve_credits(self.conn, wallet["id"], 5, "K1")
        self.assertTrue(dup["ok"])
        self.assertTrue(dup["duplicate"])
        self.assertEqual(dup["reservation_id"], first["reservation_id"])
        self.assertEqual(available_balance(self.conn, wallet["id"]), WELCOME_AMOUNT - 5)

    def test_reserve_multiple_keys(self):
        user = self._register_and_verify()
        wallet = create_wallet(self.conn, user["id"])
        grant_welcome(self.conn, user["id"])
        r1 = reserve_credits(self.conn, wallet["id"], 5, "K1")
        r2 = reserve_credits(self.conn, wallet["id"], 4, "K2")
        self.assertTrue(r1["ok"])
        self.assertTrue(r2["ok"])
        self.assertEqual(available_balance(self.conn, wallet["id"]), WELCOME_AMOUNT - 9)

    def test_release_releases_hold(self):
        user = self._register_and_verify()
        wallet = create_wallet(self.conn, user["id"])
        grant_welcome(self.conn, user["id"])
        rid = reserve_credits(self.conn, wallet["id"], 7, "K1")["reservation_id"]
        self.assertTrue(release_reservation(self.conn, rid)["ok"])
        self.assertEqual(available_balance(self.conn, wallet["id"]), WELCOME_AMOUNT)

    def test_consume_debits_ledger(self):
        user = self._register_and_verify()
        wallet = create_wallet(self.conn, user["id"])
        grant_welcome(self.conn, user["id"])
        rid = reserve_credits(self.conn, wallet["id"], 8, "K1")["reservation_id"]
        self.assertTrue(consume_reservation(self.conn, rid)["ok"])
        self.assertEqual(credit_balance(self.conn, wallet["id"]), WELCOME_AMOUNT - 8)

    def test_consume_idempotent(self):
        user = self._register_and_verify()
        wallet = create_wallet(self.conn, user["id"])
        grant_welcome(self.conn, user["id"])
        amount = 6
        rid = reserve_credits(self.conn, wallet["id"], amount, "K1")["reservation_id"]
        self.assertTrue(consume_reservation(self.conn, rid)["ok"])
        res2 = consume_reservation(self.conn, rid)
        self.assertFalse(res2["ok"])


if __name__ == "__main__":
    unittest.main()
