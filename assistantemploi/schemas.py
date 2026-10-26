"""Schémas de validation pour l'agent emploi-assistant.

Rôle :
- Valider les intentions retournées par l'agent (CHAT, IMPORT, SEARCH, ANALYZE, CV, REVISE, CLARIFY, HELP, ERROR).
- Valider les sorties structurées (offres normalisées, correspondances, documents, résultat d'action).
- Valider les erreurs métier et techniques.
- Fournir un validateur générique pour les schémas d'entrée (requêtes serveur).

Le modèle ne peut ni octroyer de crédits, ni choisir un prix, ni déclencher une action non confirmée.
Les schémas de sortie sont les seuls recus par le serveur ; la validation serveur est obligatoire.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

# ---------------------------------------------------------------------------
# Intentions
# ---------------------------------------------------------------------------

# Intention retournée par l'agent (valide par le serveur).
# L'agent renvoie une intention structurée ; le serveur valide le schéma, le propriétaire et le tarif.
INTENTIONS = (
    "CHAT", "IMPORT", "SEARCH", "ANALYZE", "CV", "REVISE", "CLARIFY", "HELP", "ERROR"
)

# Champs minimum à valider selon l'intention.
INTENT_SCHEMA = {
    "CHAT": ["text", "approved_facts", "conflicts", "missing_inputs"],
    "IMPORT": ["file", "accepted_facts", "missing_fields", "warnings"],
    "SEARCH": ["criteria", "sources", "results", "sources_consulted", "warnings"],
    "ANALYZE": ["offer", "matches", "missing", "warnings"],
    "CV": ["profile_version", "offer", "sections", "controls", "warnings"],
    "REVISE": ["document_version", "updates", "controls", "warnings"],
    "CLARIFY": ["questions", "context", "priority"],
    "HELP": ["message", "options"],
    "ERROR": ["code", "message", "recovery_hints"],
}

# Indexation rapide : intention -> liste de champs requis
def intent_required_fields(intent: str) -> list[str]:
    """Retourne la liste des champs requis pour une intention donnée."""
    if intent not in INTENT_SCHEMA:
        raise ValueError(f"intention inconnue : {intent}")
    return list(INTENT_SCHEMA[intent])


# ---------------------------------------------------------------------------
# Erreurs
# ---------------------------------------------------------------------------

# Codes explicites (CR01-CR12 + erreurs métier)
ERROR_CODES = (
    "INSUFFICIENT_CREDITS",
    "QUOTE_EXPIRED",
    "PROFILE_INCOMPLETE",
    "OFFER_CLOSED",
    "PAYMENT_PENDING",
    "SOURCE_UNAVAILABLE",
    "OUTPUT_VALIDATION_FAILED",
    "ACTION_ALREADY_STARTED",
    "TASK_NOT_FOUND",
    "USER_NOT_FOUND",
    "NOT_AUTHORIZED",
    "RATE_LIMITED",
)

# Messages d'erreur pré-définis (texte clair, sans données sensibles)
ERROR_MESSAGES = {
    "INSUFFICIENT_CREDITS": "solde insuffisant pour cette action",
    "QUOTE_EXPIRED": "devis expiré, veuillez en demander un nouveau",
    "PROFILE_INCOMPLETE": "profil incomplet, veuillez compléter les champs requis",
    "OFFER_CLOSED": "offre clôturée, aucune génération ciblée",
    "PAYMENT_PENDING": "paiement en attente, vérifiez votre transaction",
    "SOURCE_UNAVAILABLE": "source de données temporairement inaccessible",
    "OUTPUT_VALIDATION_FAILED": "résultat invalide, traitement annulé",
    "ACTION_ALREADY_STARTED": "action déjà en cours",
    "TASK_NOT_FOUND": "tâche introuvable",
    "USER_NOT_FOUND": "compte inconnu",
    "NOT_AUTHORIZED": "accès refusé, vérifiez vos permissions",
    "RATE_LIMITED": "trop de requêtes, réessayez plus tard",
}


def make_error(code: str, message: str = "", **extra: Any) -> dict[str, Any]:
    """Construit un objet erreur standardisé."""
    if code not in ERROR_CODES and code not in ERROR_MESSAGES:
        raise ValueError(f"code d'erreur inconnu : {code}")
    data = {
        "code": code,
        "message": message or ERROR_MESSAGES.get(code, "erreur inconnue"),
    }
    data.update(extra)
    return data


# ---------------------------------------------------------------------------
# Modèles de sortie (données métier)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class OfferOccurrence:
    """Une annonce normalisée, encodée source par source."""
    source_id: str
    source_url: str
    title: str
    employer: str
    country: str
    city: str
    contract_type: str
    work_mode: str
    deadline: str | None
    salary_min: int | None
    salary_max: int | None
    salary_currency: str | None
    requirements: str
    translation: str | None
    status: str  # ouverte, clôturée, expirée, incertaine
    published_at: str
    collected_at: str
    checked_at: str

    def to_dict(self) -> dict[str, Any]:
        """Conversion en dictionnaire pour la sérialisation (JSON)."""
        return {
            "source_id": self.source_id,
            "source_url": self.source_url,
            "title": self.title,
            "employer": self.employer,
            "country": self.country,
            "city": self.city,
            "contract_type": self.contract_type,
            "work_mode": self.work_mode,
            "deadline": self.deadline,
            "salary_min": self.salary_min,
            "salary_max": self.salary_max,
            "salary_currency": self.salary_currency,
            "requirements": self.requirements,
            "translation": self.translation,
            "status": self.status,
            "published_at": self.published_at,
            "collected_at": self.collected_at,
            "checked_at": self.checked_at,
        }


@dataclass(frozen=True)
class Match:
    """Correspondance exigence ↔ profil (sans invention de données)."""
    requirement: str
    evidence: str
    coverage: str  # couvert, partiellement, non couvert, inconnu
    is_optional: bool = False
    uncertainty: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "requirement": self.requirement,
            "evidence": self.evidence,
            "coverage": self.coverage,
            "optional": self.is_optional,
            "uncertainty": self.uncertainty,
        }


@dataclass(frozen=True)
class SearchResult:
    """Résultat d'une recherche : offres avec provenance explicite."""
    criteria: dict[str, Any]
    offers: list[OfferOccurrence]
    sources_consulted: list[str]
    missing: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "criteria": self.criteria,
            "offers": [o.to_dict() for o in self.offers],
            "sources_consulted": self.sources_consulted,
            "missing": self.missing,
            "warnings": self.warnings,
        }


@dataclass(frozen=True)
class ActionOutput:
    """Résultat d'une action métier (résultat structuré, référence, état)."""
    task_id: str
    state: str
    deliverable: str | None
    warnings: list[str] = field(default_factory=list)
    sources_consulted: list[str] = field(default_factory=list)
    tariff_version: int = 1
    credits_consumed: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "state": self.state,
            "deliverable": self.deliverable,
            "warnings": self.warnings,
            "sources_consulted": self.sources_consulted,
            "tariff_version": self.tariff_version,
            "credits_consumed": self.credits_consumed,
        }


# ---------------------------------------------------------------------------
# Validation générique
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ValidationResult:
    """Résultat d'une validation de schéma."""
    valid: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def add_error(self, msg: str) -> None:
        self.errors.append(msg)

    def add_warning(self, msg: str) -> None:
        self.warnings.append(msg)


def validate_required_fields(intent: str, data: dict[str, Any]) -> ValidationResult:
    """Vérifie que tous les champs requis d'une intention sont présents."""
    result = ValidationResult(valid=True)
    required = intent_required_fields(intent)
    for field in required:
        if field not in data:
            result.valid = False
            result.add_error(f"champ manquant pour {intent} : {field}")
    return result


def validate_offer(offer: dict[str, Any]) -> ValidationResult:
    """Valide une annonce normalisée (scalaires obligatoires, pas de valeurs fabriquées)."""
    result = ValidationResult(valid=True)
    required = ["source_id", "source_url", "title", "employer", "country", "city", "requirements", "status"]
    for field in required:
        if field not in offer:
            result.valid = False
            result.add_error(f"offer : champ manquant {field}")
    if offer.get("salary_min") is not None and not isinstance(offer["salary_min"], (int, type(None))):
        result.valid = False
        result.add_error("offer : salary_min doit être un entier ou null")
    return result


def validate_match(match: dict[str, Any]) -> ValidationResult:
    """Valide une correspondance exigence ↔ profil."""
    result = ValidationResult(valid=True)
    for field in ["requirement", "evidence", "coverage"]:
        if field not in match:
            result.valid = False
            result.add_error(f"match : champ manquant {field}")
    if match.get("coverage") not in ("couvert", "partiellement", "non couvert", "inconnu"):
        result.valid = False
        result.add_error(f"match : coverage invalide {match.get('coverage')}")
    return result


# ---------------------------------------------------------------------------
# IDs et horodatage standard
# ---------------------------------------------------------------------------

def new_task_id() -> str:
    """Identifiant de tâche unique (UUID v4)."""
    return uuid.uuid4().hex[:16]


def now_iso() -> str:
    """Horodatage UTC au format ISO 8601."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def normalize_text(text: str, max_len: int = 1000) -> str:
    """Nettoie et tronque un texte pour la validation, s'il est trop long."""
    if not isinstance(text, str):
        raise ValueError("texte invalide")
    text = " ".join(text.split())
    if len(text) > max_len:
        text = text[:max_len] + "…"
    return text
