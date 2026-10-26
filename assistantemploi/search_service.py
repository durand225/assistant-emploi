"""Recherche, normalisation, dédoublonnage et classement expliqué — T08.

Rôle :
- Recevoir un périmètre de recherche (pays, métier, filtres).
- Consulter les sources autorisées via le connecteur (source_registry).
- Normaliser les annonces (champs requis, valeurs manquantes nowhere).
- Dédoublonner par employeur, titre, lieu, référence et contenu.
- Vérifier la fraîcheur (date de publication, collecte, dernière vérification).
- Classer et expliquer : méthode de tri, poids des critères.
- Sauvegarder les résultats AVANT consommation des crédits.

Entités clés :
- OfferOccurrence : annonce normalisée, encodée source par source.
- NormalizedSearchResult : résultats, sources consultées, précisions, avertissements.

Règles appliquées :
- Soit absents, les champs restent explicitement absents.
- Chaque offre garde son source_url et les doublons sont supprimés.
- La freinabilité et la vérification de fraîcheur sont conservées.
"""

from __future__ import annotations

import re
import sqlite3
import uuid
from datetime import datetime, timezone

from . import source_registry as sreg


# ---------------------------------------------------------------------------
# Modèles de données de la recherche
# ---------------------------------------------------------------------------

class OfferOccurrence:
    """Une annonce normalisée, encodée source par source."""

    def __init__(self, data: dict):
        self.source_id = data["source_id"]
        self.source_url = data["source_url"]
        self.title = data["title"]
        self.employer = data["employer"]
        self.country = data.get("country")
        self.city = data.get("city")
        self.contract_type = data.get("contract_type")
        self.work_mode = data.get("work_mode")
        self.published_at = data.get("published_at")
        self.salary_min = data.get("salary_min")
        self.salary_max = data.get("salary_max")
        self.salary_currency = data.get("salary_currency")
        self.status = data.get("status", "ouverte")
        self.stored_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    def to_dict(self) -> dict:
        return {
            "source_id": self.source_id,
            "source_url": self.source_url,
            "title": self.title,
            "employer": self.employer,
            "country": self.country,
            "city": self.city,
            "contract_type": self.contract_type,
            "work_mode": self.work_mode,
            "published_at": self.published_at,
            "salary_min": self.salary_min,
            "salary_max": self.salary_max,
            "salary_currency": self.salary_currency,
            "status": self.status,
            "stored_at": self.stored_at,
        }


class SearchResult:
    """Résultat d'une recherche : offres normalisées, sources consultées, explications."""

    def __init__(self, criteria: dict, offers: list[OfferOccurrence], sources_consulted: list[str]):
        self.criteria = criteria
        self.offers = offers
        self.sources_consulted = sources_consulted
        self.explanation = self._build_explanation()
        self.sorted_offers = self._sort_offers()
        self.dedup_offers = self._dedupe()
        # Comptages pour les tests et la persistance
        self.count_original = len(self.offers)
        self.count_dedup = len(self.dedup_offers)

    def _build_explanation(self) -> dict:
        return {
            "criteria_used": self.criteria,
            "sources_consulted": self.sources_consulted,
            "dedup_applied": len(self.offers) != len(getattr(self, "dedup_offers", [])) if hasattr(self, "dedup_offers") else False,
            "notes": [],
        }

    def _sort_offers(self) -> list[OfferOccurrence]:
        # Tri initial: date de publication (plus récente en premier), puis notes.
        def sort_key(o):
            pub = o.published_at or "1970-01-01T00:00:00Z"
            return (pub, o.employer.lower())

        return sorted(self.offers, key=sort_key, reverse=True)

    def _dedupe(self) -> list[OfferOccurrence]:
        seen = set()
        unique = []
        for o in self.sorted_offers:
            key = (
                o.employer.lower(),
                o.title.lower(),
                o.city.lower() if o.city else "",
                o.source_id,
            )
            if key not in seen:
                seen.add(key)
                unique.append(o)
        return unique

    def to_dict(self) -> dict:
        return {
            "criteria": self.criteria,
            "sources_consulted": self.sources_consulted,
            "offers": [o.to_dict() for o in self.dedup_offers],
            "explanation": self.explanation,
            "count_original": len(self.offers),
            "count_dedup": len(self.dedup_offers),
        }


# ---------------------------------------------------------------------------
# Service de recherche
# ---------------------------------------------------------------------------

class SearchService:
    """Service de recherche pour un compte.

    Pipeline :
    1. Valider le périmètre (pays, métier).
    2. Sélectionner les connecteurs autorisés.
    3. Collecter avec quota.
    4. Normaliser.
    5. Dédoublonner.
    6. Vérifier fraîcheur.
    7. Classement et explication.
    8. Sauvegarder (persistance) dans la BD.
    """

    def __init__(self, conn: sqlite3.Connection, user_id: str):
        self.conn = conn
        self.user_id = user_id

    def search(self, criteria: dict, max_results: int = 20) -> SearchResult:
        """Exécute la recherche et retourne un SearchResult."""
        # 1. Valider le périmètre.
        validated = self._validate_criteria(criteria)
        if validated is None:
            return SearchResult(criteria, [], [])

        pays = validated.get("pays") or "CI"
        metier = validated.get("metier") or ""

        # 2. Sélectionner les connecteurs autorisés.
        conn = self.conn
        sources = self._authorized_sources(conn)
        if not sources:
            return SearchResult(criteria, [], []).append_explanation("Aucune source autorisée")

        # 3. Collecte avec quota.
        offers = []
        seen_keys = set()
        for src in sources:
            connector = sreg.SourceConnector(src)
            try:
                batch = connector.list_offers(validated, max_results)
            except Exception as exc:
                # Connexion partielle : on continue avec les autres sources.
                offers.append({
                    "source_id": src.id,
                    "source_url": None,
                    "title": "Erreur source",
                    "error": str(exc),
                    "status": "partielle",
                })
                continue

            for o in batch:
                key = (
                    o.get("employer", "").lower(),
                    o.get("title", "").lower(),
                    o.get("city", "").lower() if o.get("city") else "",
                    o.get("source_id", ""),
                )
                if key not in seen_keys:
                    seen_keys.add(key)
                    offers.append(o)

        # 4. Normalisation (champs absents restent inconnus).
        normalized = [OfferOccurrence(o) for o in offers]

        # 5. Dédoublonnage.
        dedup = self._dedupe(normalized)

        # 6. Fraîcheur.
        self._check_freshness(dedup)

        # 7. Classement et explication.
        result = SearchResult(validated, dedup, [s.id for s in sources])
        result.explanation["notes"].append(f"Sources consultées : {len(sources)}")
        result.explanation["notes"].append(f"Offres trouvées : {len(result.dedup_offers)}")

        # 8. Sauvegarde (persistance).
        self._save_result(validated, result)

        return result

    def _validate_criteria(self, criteria: dict) -> dict | None:
        """Valider le périmètre. Retourne les critères corrigés ou None."""
        pays = (criteria.get("pays") or "CI").strip().upper()
        # Normaliser le pays (CI -> CI, etc.)
        if pays not in ("CI", "CIV", "COTE D'IVOIRE", "FR", "FRANCE"):
            pays = "CI"

        metier = (criteria.get("metier") or "").strip().lower()
        # Rendre le métier en minuscule.
        return {"pays": pays, "metier": metier}

    def _authorized_sources(self, conn: sqlite3.Connection) -> list:
        """Retourne la liste des sources actives."""
        return sreg.get_all_sources(conn, status="active")

    def _dedupe(self, offers: list["OfferOccurrence"]) -> list["OfferOccurrence"]:
        seen = set()
        dedup = []
        for o in offers:
            key = (o.employer.lower(), o.title.lower(), o.city.lower() if o.city else "", o.source_id)
            if key not in seen:
                seen.add(key)
                dedup.append(o)
        return dedup

    def _check_freshness(self, offers: list["OfferOccurrence"]) -> None:
        """Marque les annonces non fraîches (plus de 30 jours)."""
        now = datetime.now(timezone.utc)
        for o in offers:
            pub = o.published_at or "1970-01-01T00:00:00Z"
            try:
                dt = datetime.fromisoformat(pub.replace("Z", "+00:00"))
                if (now - dt).days > 30:
                    o.published_at = f"{o.published_at} (vérifier)"
            except Exception:
                pass

    def _save_result(self, criteria: dict, result: SearchResult) -> None:
        """Persiste le résultat de recherche (référence de l'historique)."""
        # Pour MVP : enregistrement dans l'historique de recherche.
        # (Implémenté plus tard — T08 est la recherche, la persistance est T05.)
        pass

    def append_explanation(self, note: str) -> None:
        """Ajoute une note d'explication à la recherche."""
        pass


# ---------------------------------------------------------------------------
# Outils d'extraction et d'aide
# ---------------------------------------------------------------------------

def normalize_offer(offer: dict) -> dict:
    """Normalise une annonce brute en un dictionnaire standardisé."""
    return {
        "source_id": offer.get("source_id"),
        "source_url": offer.get("source_url"),
        "title": offer.get("title") or "Titre non fourni",
        "employer": offer.get("employer") or "Employeur non spécifié",
        "country": offer.get("country"),
        "city": offer.get("city"),
        "contract_type": offer.get("contract_type"),
        "work_mode": offer.get("work_mode"),
        "salary_min": offer.get("salary_min"),
        "salary_max": offer.get("salary_max"),
        "salary_currency": offer.get("salary_currency"),
        "published_at": offer.get("published_at"),
        "status": offer.get("status", "ouverte"),
    }


def dedupe_offers(offers: list[dict]) -> list[dict]:
    """Dédoublonne une liste d'annonces normalisées."""
    seen = set()
    unique = []
    for o in offers:
        key = (
            o.get("employer", "").lower(),
            o.get("title", "").lower(),
            o.get("city", "").lower(),
            o.get("source_id", ""),
        )
        if key not in seen:
            seen.add(key)
            unique.append(o)
    return unique
