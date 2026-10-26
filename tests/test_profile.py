"""Tests du ticket T04 — profil canonique, faits provenance-traçables, versions.

Couverture :
- création d'un profil selon les champs du PRD ;
- validation des champs inconnus ;
- ajout / confirmation / suppression de faits avec provenance et statuts ;
- immutabilité et historisation des versions.
"""

import unittest

from assistantemploi.accounts import create_user  # noqa: F401
from assistantemploi.db import connect, migrate
from assistantemploi.profile import (
    FIELD_CHOICES,
    STATUS_CHOICES,
    add_fact,
    confirm_fact,
    create_profile,
    create_version,
    delete_fact,
    get_fact,
    get_latest_version,
    get_versions,
    update_fact,
)


class ProfileLayerTests(unittest.TestCase):
    def setUp(self):
        self.conn = connect(":memory:")
        migrate(self.conn)

    def tearDown(self):
        self.conn.close()

    def _user(self):
        return create_user(self.conn, "d@exemple.test")

    # --- profil -------------------------------------------------------------

    def test_create_profile(self):
        user = self._user()
        profil = create_profile(self.conn, user["id"], objective="Cherche emploi")
        self.assertEqual(profil["user_id"], user["id"])
        self.assertEqual(profil["objective"], "Cherche emploi")

    def test_fields_validation(self):
        user = self._user()
        with self.assertRaises(ValueError):
            create_profile(self.conn, user["id"], invente="chose")

    def test_fields_mapping(self):
        user = self._user()
        create_profile(
            self.conn, user["id"],
            objective="Développeur",
            country="CI",
            mobility="local",
        )
        p = self.conn.execute(
            "SELECT objective, country, mobility FROM profiles WHERE user_id = ?",
            (user["id"],),
        ).fetchone()
        self.assertEqual(p["objective"], "Développeur")
        self.assertEqual(p["country"], "CI")
        self.assertEqual(p["mobility"], "local")

    # --- faits ---------------------------------------------------------------

    def test_add_fact_with_provenance(self):
        user = self._user()
        profil = create_profile(self.conn, user["id"])
        fact = add_fact(
            self.conn, profil["id"], "experiences",
            "stage en dev sur 6 mois", "message_ecrit", "ref-message-1",
        )
        self.assertEqual(fact["source_type"], "message_ecrit")
        self.assertEqual(fact["status"], "extraite_a_confirmer")
        self.assertEqual(fact["field"], "experiences")

    def test_confirm_fact(self):
        user = self._user()
        profil = create_profile(self.conn, user["id"])
        fact = add_fact(self.conn, profil["id"], "skills",
                        "python, sql", "transcription_validee", "audio-1")
        confirmed = confirm_fact(self.conn, fact["id"], value="python, sql, fastapi")
        self.assertEqual(confirmed["status"], "confirmee")
        self.assertEqual(confirmed["value"], "python, sql, fastapi")

    def test_delete_fact(self):
        user = self._user()
        profil = create_profile(self.conn, user["id"])
        fact = add_fact(self.conn, profil["id"], "experiences",
                        "ancien stage", "import_pdf", "ancien.pdf")
        deleted = delete_fact(self.conn, fact["id"], value="supprimé par l'utilisateur")
        self.assertEqual(deleted["status"], "supprimee")
        self.assertEqual(deleted["value"], "supprimé par l'utilisateur")

    def test_fact_statuses_are_valid(self):
        user = self._user()
        profil = create_profile(self.conn, user["id"])
        fact = add_fact(self.conn, profil["id"], "studies",
                        "bac + 2 informatique", "import_pdf", "rapport.pdf")
        for statut in STATUS_CHOICES:
            with self.subTest(statut=statut):
                updated = update_fact(self.conn, fact["id"], status=statut)
                self.assertEqual(updated["status"], statut)

    # --- versions (immuables) ------------------------------------------------

    def test_create_version_snapshot(self):
        user = self._user()
        profil = create_profile(self.conn, user["id"], objective="Développeur")
        add_fact(self.conn, profil["id"], "skills", "python", "ecrit", "m1")
        version = create_version(self.conn, profil["id"])
        self.assertEqual(version["version"], 1)
        verif = get_latest_version(self.conn, profil["id"])
        self.assertEqual(verif["version"], 1)
        self.assertIn("objective", verif["fields_json"])
        self.assertIn("skills", verif["facts_json"])

    def test_versions_ordered_and_immutable(self):
        user = self._user()
        profil = create_profile(self.conn, user["id"])
        add_fact(self.conn, profil["id"], "experiences", "stage", "ecrit", "a")
        create_version(self.conn, profil["id"])
        add_fact(self.conn, profil["id"], "experiences", "poste", "ecrit", "b")
        create_version(self.conn, profil["id"])
        versions = get_versions(self.conn, profil["id"])
        self.assertEqual(len(versions), 2)
        self.assertEqual(versions[0]["version"], 2)  # le plus récent en premier
        # une version est une image figée : comparer la 1 et la 2
        self.assertNotEqual(versions[0]["facts_json"], versions[1]["facts_json"])


def _uid() -> str:
    import uuid
    return uuid.uuid4().hex


if __name__ == "__main__":
    unittest.main()
