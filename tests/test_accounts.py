"""Tests du ticket T02 (compte, vérification email, frontières de propriété).

Couverture :
- création d'utilisateur idempotente par email ;
- unicité et champ de validité des tokens de vérification (un seul propriétaire) ;
- consommation d'un token une seule fois ;
- séparation des comptes (A ne peut pas agir pour B) ;
- garde-fous de propriété is_owner / check_owner.
"""

import unittest

from assistantemploi.accounts import (
    check_owner,
    create_user,
    get_verification_status,
    issue_verification_token,
    is_owner,
    verify_email,
)
from assistantemploi.db import connect, migrate

EMAIL_A = "a@exemple.test"
EMAIL_B = "b@exemple.test"


class AccountsLayerTests(unittest.TestCase):
    def setUp(self):
        self.conn = connect(":memory:")
        migrate(self.conn)

    def tearDown(self):
        self.conn.close()

    # --- identité et idempotence ------------------------------------------------

    def test_create_user_with_email(self):
        row = create_user(self.conn, EMAIL_A)
        self.assertIsNotNone(row["id"])
        self.assertTrue(row["created"])

    def test_create_user_idempotent_same_email(self):
        r1 = create_user(self.conn, EMAIL_A)
        r2 = create_user(self.conn, EMAIL_A)
        self.assertEqual(r1["id"], r2["id"])
        self.assertTrue(r1["created"])
        self.assertFalse(r2["created"])

    def test_create_user_lowercase_stripped(self):
        r1 = create_user(self.conn, "  A@Exemple.Test ")
        r2 = create_user(self.conn, "a@exemple.test")
        self.assertEqual(r1["id"], r2["id"])

    def test_create_user_invalid_email_rejected(self):
        with self.assertRaises(ValueError):
            create_user(self.conn, "pas-un-email")

    # --- vérification email ----------------------------------------------------

    def test_verify_token_success(self):
        user = create_user(self.conn, EMAIL_A)
        token = issue_verification_token(self.conn, user["id"])
        self.assertTrue(token)
        res = verify_email(self.conn, token)
        self.assertTrue(res["verified"])
        self.assertEqual(res["user_id"], user["id"])
        self.assertTrue(get_verification_status(self.conn, user["id"])["email_verified"])

    def test_verify_token_single_use(self):
        user = create_user(self.conn, EMAIL_A)
        token = issue_verification_token(self.conn, user["id"])
        verify_email(self.conn, token)
        self.assertFalse(verify_email(self.conn, token)["verified"])

    def test_verify_unknown_token_rejected(self):
        user = create_user(self.conn, EMAIL_A)
        self.assertFalse(verify_email(self.conn, "inconnu")["verified"])

    def test_token_scoped_to_its_owner(self):
        a = create_user(self.conn, EMAIL_A)
        b = create_user(self.conn, EMAIL_B)
        token_a = issue_verification_token(self.conn, a["id"])
        token_b = issue_verification_token(self.conn, b["id"])
        # Un token ne valide que son propre propriétaire (il retourne son id).
        self.assertEqual(verify_email(self.conn, token_a)["user_id"], a["id"])
        self.assertEqual(verify_email(self.conn, token_b)["user_id"], b["id"])

    # --- frontières de propriété ----------------------------------------------

    def test_is_owner(self):
        self.assertTrue(is_owner(EMAIL_A, EMAIL_A))
        self.assertFalse(is_owner(EMAIL_A, EMAIL_B))
        self.assertFalse(is_owner(None, EMAIL_A))
        self.assertFalse(is_owner(EMAIL_A, None))

    def test_check_owner_raises_for_other_user(self):
        with self.assertRaises(PermissionError):
            check_owner(EMAIL_A, EMAIL_B)


class IsolationBoundaryDemo(unittest.TestCase):
    """Démonstration de la séparation des comptes, sortie côte utilisateur."""

    def setUp(self):
        self.conn = connect(":memory:")
        migrate(self.conn)

    def tearDown(self):
        self.conn.close()

    def test_accounts_cannot_act_for_each_other(self):
        from assistantemploi.accounts import create_user, is_owner, issue_verification_token, verify_email

        a = create_user(self.conn, EMAIL_A)
        b = create_user(self.conn, EMAIL_B)

        token_a = issue_verification_token(self.conn, a["id"])

        # Vérifier A avec son propre token.
        self.assertTrue(verify_email(self.conn, token_a)["verified"])

        # B ne peut pas vérifier le compte de A (token dédié à A, et B non vérifié).
        self.assertFalse(get_verification_status(self.conn, b["id"])["email_verified"])

        # frontières de propriété rejetées.
        self.assertTrue(is_owner(a["id"], a["id"]))
        self.assertFalse(is_owner(b["id"], a["id"]))
        with self.assertRaises(PermissionError):
            check_owner(b["id"], a["id"])


if __name__ == "__main__":
    unittest.main()
