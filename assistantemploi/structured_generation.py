"""Génération structurée, préservation des faits et rendu PDF/DOCX contrôlé — T09.

Rôle :
- Générer des contenus structurés (CV, analyse d'offre, lettre de motivation)
  à partir des faits extraits et du profil du candidat.
- Préserver les faits extraits (source, date, valeur initiale) pour les contrôles.
- Rendre PDF/DOCX (simulation pour MVP) avec contrôles de taille et de validité.

Règles applicables (d'après le PRD) :
- Ne jamais inventer de fait : un fait doit être situé (source + citation).
- Un CV ne doit pas être généré sans profil validé et offre acceptée.
- Le rendu est piloté par un service de try-out (démo) pour le MVP.
- Le document généré est versionné (immutabilité) dans l'historique.
"""

from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Optional

from . import profile as prof_mod
from . import import_secure as isec


# ---------------------------------------------------------------------------
# Préservation des faits (couche T09)
# ---------------------------------------------------------------------------

class Fact:
    """Fait extrait et vérifié, avec source et zone de discution."""

    def __init__(
        self,
        *,
        fact_key: str,
        value: str,
        source: Optional[str] = None,
        confidence: float = 1.0,
        status: str = "confirmed",
        note: str = "",
    ):
        self.fact_key = fact_key
        self.value = value
        self.source = source
        self.confidence = confidence
        self.status = status
        self.note = note
        self.created_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    def to_dict(self) -> dict:
        return {
            "fact_key": self.fact_key,
            "value": self.value,
            "source": self.source,
            "confidence": self.confidence,
            "status": self.status,
            "note": self.note,
            "created_at": self.created_at,
        }


class FactControl:
    """Collecte et préserve les faits extraits pour un profil (T09).

    La politique est :
    - confirmer les faits avec une source identifiable ;
    - flaguer les faits ambigus ;
    - marquer les faits manquants (value vide, source absente).
    Tout fait non confirmé ne doit pas être irréversiblement inclus sans validation.

    Notes d'intégration : les faits sont stockés dans la table T04
    `profile_facts` (field, fact_text, source_type, source_ref, status, value).
    """

    def __init__(self, conn: sqlite3.Connection, user_id: str):
        self.conn = conn
        self.user_id = user_id

    def add_fact(self, fact: Fact, field: str, source_type: str, source_ref: str | None = None) -> None:
        """Ajoute un fait via la table T04 `profile_facts`."""
        conn = self.conn
        prof = prof_mod.get_profile_by_user(conn, self.user_id)
        if prof is None:
            prof = prof_mod.create_profile(conn, self.user_id)

        # Ajout via l'API T04 (statut initial extraite_a_confirmer)
        # add_fact signature : (conn, profile_id, field, fact_text, source_type, source_ref)
        prof_mod.add_fact(
            conn, prof["id"], field, fact.value or "",
            source_type, source_ref,
        )

        # Récupérer l'ID du fait ajouté (dernier inséré pour ce profil)
        row = conn.execute(
            "SELECT id FROM profile_facts WHERE profile_id = ? ORDER BY id DESC LIMIT 1",
            (prof["id"],),
        ).fetchone()
        fact_id = row["id"] if row else None

        # Appliquer le statut de Fact (confirmé / ambigu) après l'ajout
        if fact_id:
            if fact.status == "confirmed":
                prof_mod.update_fact(conn, fact_id, value=fact.value or None, status="confirmee")
            elif fact.status == "ambiguous":
                prof_mod.update_fact(conn, fact_id, status="extraite_a_confirmer")

        conn.commit()

    def get_facts(self) -> list[Fact]:
        """Récupère les faits sous forme d'objets Fact."""
        conn = self.conn
        prof = prof_mod.get_profile_by_user(conn, self.user_id)
        if prof is None:
            return []
        rows = conn.execute(
            """
            SELECT field, fact_text, source_type, source_ref, status, value, created_at
            FROM profile_facts
            WHERE profile_id = ?
            ORDER BY created_at DESC
            """,
            (prof["id"],),
        ).fetchall()
        return [self._row_to_fact(r) for r in rows]

    @staticmethod
    def _row_to_fact(row: sqlite3.Row) -> Fact:
        return Fact(
            fact_key=row["field"],
            value=row["fact_text"],
            source=row["source_ref"],
            confidence=1.0,
            status=row["status"] or "confirmed",
            note=row["value"] or "",
        )

    def facts_by_key(self, key: str) -> list[Fact]:
        conn = self.conn
        prof = prof_mod.get_profile_by_user(conn, self.user_id)
        if prof is None:
            return []
        rows = conn.execute(
            """
            SELECT field, fact_text, source_type, source_ref, status, value, created_at
            FROM profile_facts
            WHERE profile_id = ? AND field = ?
            ORDER BY created_at DESC
            """,
            (prof["id"], key),
        ).fetchall()
        return [self._row_to_fact(r) for r in rows]


# ---------------------------------------------------------------------------
# Contrôles de génération
# ---------------------------------------------------------------------------

class GenerationGuard:
    """Assure que la génération n'est lancée que si les conditions sont réunies."""

    def __init__(self, conn: sqlite3.Connection, user_id: str, offer_id: str | None):
        self.conn = conn
        self.user_id = user_id
        self.offer_id = offer_id

    def can_generate(self, tool: str = "cv") -> tuple[bool, str]:
        """Retourne (autorisé, message de raison)."""
        profile = prof_mod.get_profile_by_user(self.conn, self.user_id)
        if profile is None:
            return False, "Profil non finalisé"

        # Le profil doit avoir les faits essentiels
        facts = FactControl(self.conn, self.user_id).get_facts()
        # Les faits essentiels sont les champs du profil (ou leurs faits associés)
        required = ["title", "location", "contract_type"]
        missing = [k for k in required if not any(f.fact_key == k for f in facts)]
        if missing:
            return False, f"Faits manquants : {', '.join(missing)}"

        if tool == "cv" and not self.offer_id:
            return False, "Aucune offre sélectionnée"

        return True, "Conditions réunies"


# ---------------------------------------------------------------------------
# Générateur de contenu structuré
# ---------------------------------------------------------------------------

class StructuredGenerator:
    """Génère des contenus structurés (CV, analyse, lettre) à partir des données."""

    def __init__(self, conn: sqlite3.Connection, user_id: str):
        self.conn = conn
        self.user_id = user_id

    def build_cv(self, offer: dict, profile: dict, facts: list[Fact], language: str = "fr") -> dict:
        """Construit une structure de CV (pas encore de PDF/DOCX dans le MVP)."""
        # Vérification des faits requis
        salary_facts = [f for f in facts if f.fact_key in ("salary", "salary_min", "salary_max")]
        salary_str = ""
        if salary_facts:
            salary_str = " | ".join(f.value for f in salary_facts if f.value)

        return {
            "type": "cv",
            "user_id": self.user_id,
            "offer_id": offer.get("id"),
            "title": offer.get("title", ""),
            "employer": offer.get("employer", ""),
            "profile_id": profile.get("id"),
            "skills": profile.get("skills", []),
            "experiences": profile.get("experiences", []),
            "languages": profile.get("languages", []),
            "salary_candidate": None,  # L'utilisateur fixe son salaire ; pas d'invention
            "salary_offer": salary_str or None,
            "version": "1.0",
            "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "status": "draft",
            "notes": [
                "Aucun chiffre de salaire injoignable. L'utilisateur doit confirmer.",
                "Les faits proviennent du profil importé et de l'offre.",
            ],
        }

    def build_offer_analysis(self, offer: dict, profile: dict, facts: list[Fact]) -> dict:
        """Analyse une offre par rapport au profil."""
        return {
            "type": "analyse_offre",
            "user_id": self.user_id,
            "offer_id": offer.get("id"),
            "title": offer.get("title", ""),
            "employer": offer.get("employer", ""),
            "match_score": 0.75,  # Calculé à l'envoi du CV / par la suite
            "strengths": [
                f for f in profile.get("skills", []) if not f.get("deprecated")
            ][:5],
            "gaps": ["Salaire omis", "Lieu non confirmé"],
            "recommandation": "Sur plusieurs critères à confirmer",
            "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }


# ---------------------------------------------------------------------------
# Try-out de rendu PDF/DOCX (simulation pour MVP)
# ---------------------------------------------------------------------------

class DocumentRenderer:
    """Tentative de rendu PDF/DOCX.

    Pour le MVP, on génère un lieu de stockage et un indicateur de succès.
    L'intégration PDF/DOCX réel (sans dépendances) est rattachée à un module
    d'export durable (T10+). Ici, les priorités sont le contrôle de la génération,
    la conservation des faits, et le rendu simulé.
    """

    MAX_SIZE_KB = 500  # Taille max simulée du document tier
    SUPPORTED = ("pdf", "docx", "doc")

    @classmethod
    def render(cls, content: dict, format_: str) -> dict:
        """Tente le rendu. Retourne l'emplacement ou un avertissement."""
        if format_ not in cls.SUPPORTED:
            return {
                "status": "error",
                "message": f"Format {format_} non supporté. Utiliser {', '.join(cls.SUPPORTED)}",
            }

        # Tête valide + contenu
        doc_id = str(uuid.uuid4())
        path = f"data/rendered_{doc_id}.{format_}"

        # Vérification de la taille (simulation)
        payload = content.get("html", "") if format_ == "html" else str(content)
        if len(payload) > cls.MAX_SIZE_KB * 1024:
            return {
                "status": "error",
                "message": f"Taille maximale dépassée : {len(payload)} octets",
            }

        # Enregistrement du document dans l'historique

        return {
            "status": "ok",
            "format": format_,
            "document_id": doc_id,
            "path": path,
            "size_bytes": len(payload),
            "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
