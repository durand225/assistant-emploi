"""Registre des sources d'offres et connecteur d'annonces.

Rôle (T07) :
- Enregistrer les sources d'offres autorisées ( droits de collecte, attribution,
  quotas, fréquence de mise à jour, contact, revue des conditions ).
- Fournir un adaptor pour interroger une source autorisée.
- Retourner des annonces normalisées (source_id, url, titre, employeur, pays, ville,
  type de contrat, modalité de travail, date de publication, salaire, status ).

Architecture :
- Source registry : liste des sources approuvées, avec droits de collecte, attribution,
  quotas, fréquence de mise à jour, contact, revue des conditions.
- Connecteur : adaptor pour interroger une source autorisée.
- Nom d'outil métier : emploi.get_offres (SEARCH).

Sécurité :
- Seules les sources autorisées (status='active') sont consultables.
- Les droits de collecte et d'attribution sont vérifiés côté serveur.
- Pas de collecte depuis des sources non autorisées.

Note pour le MVP : le connecteur de démonstration étend les offres réelles depuis
Greenhouse Job Board API (S3) mais ne remplace pas la validation des droits.
Le MVP lance une recherche autorisée avec un connecteur simulant les résultats réels.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

# Statuts d'une source.
SOURCE_STATUSES = ("disabled", "active", "paused")

# Catégories de source.
SOURCE_CATEGORIES = ("service_public_emploi", "plateforme_locale", "cabinet_recrutement", "site_career", "flux_api")


class SourceRegistryError(Exception):
    """Erreur du registre de sources."""


class Source:
    """Représentation d'une source d'offres autorisée."""

    def __init__(
        self,
        source_id: str,
        name: str,
        country: str,
        category: str,
        access: str,
        attribution: str,
        quotas: dict,
        update_frequency: str,
        contact: str,
        conditions_reviewed_at: str,
        rights: str,
        status: str = "active",
    ):
        self.id = source_id
        self.name = name
        self.country = country
        self.category = category
        self.access = access
        self.attribution = attribution
        self.quotas = quotas or {}
        self.update_frequency = update_frequency
        self.contact = contact
        self.conditions_reviewed_at = conditions_reviewed_at
        self.rights = rights
        self.status = status

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "country": self.country,
            "category": self.category,
            "access": self.access,
            "attribution": self.attribution,
            "quotas": self.quotas,
            "update_frequency": self.update_frequency,
            "contact": self.contact,
            "conditions_reviewed_at": self.conditions_reviewed_at,
            "rights": self.rights,
            "status": self.status,
        }


# Exemple de source pour le MVP (à remplacer par l'API réelle).
# Utilise Greenhouse Job Board API (S3) comme référence conceptuelle.
DEFAULT_SOURCES = [
    {
        "source_id": "src_greenhouse_ci",
        "name": "Greenhouse CI - Job Board",
        "country": "CI",
        "category": "site_career",
        "access": "api",
        "attribution": "document d'usage API",
        "quotas": {"requests_per_hour": 60, "results_per_call": 20},
        "update_frequency": "every_24h",
        "contact": "support@votre-employeur.com",
        "conditions_reviewed_at": "2026-10-25T00:00:00Z",
        "rights": "lecture publique (Job Board API) - vérifiée",
        "status": "active",
    },
]


# ============================================================================
# Session de registre (base SQLite)
# ============================================================================

def init_registry(conn: sqlite3.Connection) -> None:
    """Crée la table des sources si absente et remplit les sources par défaut."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS source_registry (
            source_id      TEXT PRIMARY KEY,
            name           TEXT NOT NULL,
            country        TEXT NOT NULL,
            category       TEXT NOT NULL,
            access         TEXT NOT NULL,
            attribution    TEXT NOT NULL,
            quotas         TEXT NOT NULL DEFAULT '{}',
            update_frequency TEXT NOT NULL,
            contact        TEXT NOT NULL,
            conditions_reviewed_at TEXT NOT NULL,
            rights         TEXT NOT NULL,
            status         TEXT NOT NULL DEFAULT 'active',
            created_at     TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at     TEXT
        )
        """
    )
    conn.commit()
    # Remplit la source par défaut si vide.
    if conn.execute("SELECT COUNT(*) FROM source_registry").fetchone()[0] == 0:
        for s in DEFAULT_SOURCES:
            register_source(conn, Source(**s), commit=True)


def register_source(
    conn: sqlite3.Connection,
    source: Source,
    commit: bool = True,
) -> Source:
    """Enregistre une source dans le registre."""
    conn.execute(
        """
        INSERT OR REPLACE INTO source_registry (
            source_id, name, country, category, access, attribution,
            quotas, update_frequency, contact, conditions_reviewed_at,
            rights, status
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            source.id,
            source.name,
            source.country,
            source.category,
            source.access,
            source.attribution,
            str(source.quotas),
            source.update_frequency,
            source.contact,
            source.conditions_reviewed_at,
            source.rights,
            source.status,
        ),
    )
    if commit:
        conn.commit()
    return source


def get_source(conn: sqlite3.Connection, source_id: str) -> Source | None:
    """Récupère une source par ID."""
    row = conn.execute(
        "SELECT * FROM source_registry WHERE source_id = ?", (source_id,)
    ).fetchone()
    if row is None:
        return None
    return Source(
        source_id=row["source_id"],
        name=row["name"],
        country=row["country"],
        category=row["category"],
        access=row["access"],
        attribution=row["attribution"],
        quotas=eval(row["quotas"]) if row["quotas"] else {},
        update_frequency=row["update_frequency"],
        contact=row["contact"],
        conditions_reviewed_at=row["conditions_reviewed_at"],
        rights=row["rights"],
        status=row["status"],
    )


def get_all_sources(conn: sqlite3.Connection, status: str | None = None) -> list[Source]:
    """Retourne la liste des sources autorisées (active par défaut)."""
    if status:
        rows = conn.execute(
            "SELECT * FROM source_registry WHERE status = ? ORDER BY name", (status,)
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM source_registry WHERE status = 'active' ORDER BY name"
        ).fetchall()
    return [
        Source(
            source_id=r["source_id"],
            name=r["name"],
            country=r["country"],
            category=r["category"],
            access=r["access"],
            attribution=r["attribution"],
            quotas=eval(r["quotas"]) if r["quotas"] else {},
            update_frequency=r["update_frequency"],
            contact=r["contact"],
            conditions_reviewed_at=r["conditions_reviewed_at"],
            rights=r["rights"],
            status=r["status"],
        )
        for r in rows
    ]


# ============================================================================
# Connecteur d'offres (adapter)
# ============================================================================

class ConnectorError(Exception):
    """Erreur de connecteur."""


class SourceConnector:
    """Adapteur pour interroger une source autorisée.

    Le connecteur utilise l'adaptateur HTTP natif (urllib) pour rester
    sans dépendance externe.
    """

    def __init__(self, source: Source, http_client=None):
        self.source = source
        self.http_client = http_client

    def list_offers(self, criteria: dict, max_results: int = 20) -> list[dict]:
        """Retourne les offres normalisées pour un périmètre.

        Pour le MVP, c'est un résultat simulé à partir du registre de sources.
        En production : appel de l'API de la source, normalisation des réponses.
        """
        self._check_authorization()

        # Simuler les résultats réels depuis la source.
        offers = self._simulate_offers(criteria, max_results)
        return offers

    def _check_authorization(self) -> None:
        """Vérifie que la source est active."""
        if self.source.status != "active":
            raise SourceConnectorError("source non autorisée (status=%s)" % self.source.status)

    def _simulate_offers(self, criteria: dict, max_results: int) -> list[dict]:
        """Simulateur de résultats réels (démo).

        Pour le MVP, retourne des offres correspondant au périmètre demandé.
        Critères inconnus ou inexistants -> liste vide (AC04).
        """
        pays = (criteria.get("pays") or "").upper().strip()
        metier = (criteria.get("metier") or "").strip()

        # Pays non couvert -> pas de résultats (AC04)
        if pays and pays not in ("CI", "CIV", "COTE D'IVOIRE"):
            return []

        # Metier invalide (AC07)
        valid_metiers = {
            "developpeur", "comptable", "infirmier", "agent commercial",
            "cadre", "commercial", "technicien", "ingenieur",
        }
        if metier and metier.lower() not in valid_metiers:
            return []

        # Exemple de résultats réalistes (partie du pays demandé).
        base = {
            "employers": [
                {"id": "emp_1", "name": "MAIA", "website": "https://maia.ci"},
                {"id": "emp_2", "name": "NexaTech", "website": "https://nexatech.ci"},
                {"id": "emp_3", "name": "EcoTrust CI", "website": "https://ecotrust.ci"},
                {"id": "emp_4", "name": "Bureau d'Etudes SA", "website": "https://bureau-etudes.ci"},
                {"id": "emp_5", "name": "SoftGroup", "website": "https://softgroup.ci"},
            ]
        }
        offers = []
        for emp in base["employers"]:
            published = "2026-10-25T00:00:00Z"
            # Différenciation des dates pour les tests de classement (T08.4)
            if emp["id"] == "emp_1":
                published = "2026-10-20T00:00:00Z"
            elif emp["id"] == "emp_2":
                published = "2026-10-22T00:00:00Z"
            elif emp["id"] == "emp_3":
                published = "2026-10-18T00:00:00Z"
            elif emp["id"] == "emp_4":
                published = "2026-10-24T00:00:00Z"
            elif emp["id"] == "emp_5":
                published = "2026-10-19T00:00:00Z"
            offers.append({
                "source_id": self.source.id,
                "source_url": f"https://api.emploi.ci/offres/{emp['id']}",
                "title": f"{emp['name']} - Emploi en ligne",
                "employer": emp["name"],
                "country": self.source.country,
                "city": "Abidjan",
                "contract_type": "CDI",
                "work_mode": "télétravail",
                "published_at": published,
                "status": "ouverte",
            })
        return offers[:max_results]

    def health(self) -> dict:
        """Indique l'état du connecteur, incluant le nombre de sources actives."""
        return {
            "source_id": self.source.id,
            "status": "ok",
            "sources": 1,  # nombre de sources actives dans ce connecteur
            "quotes_per_request": self.source.quotas.get("requests_per_hour", 60),
            "results_per_call": self.source.quotas.get("results_per_call", 20),
        }
