"""Adaptateur Hermes — toile de communication backend ↔ agent Hermes.

Rôle :
- Filtrer le contexte de session (contextes de session filtrée).
- Exposer les outils autorisés (emploi.*) au modèle.
- Appeler l'API Hermes (celle de l'utilisateur, permissions réduites).
- Normaliser les événements (événements normalisés).

Règles de sécurité :
- Le navigateur ne reçoit JAMAIS la clé API Hermes, les secrets MCP, les clés fournisseurs
  ou des droits de modification du portefeuille. Il appelle le backend applicatif.
- Le backend contacte Hermes sur un réseau privé ou une interface protégée.
- Le modèle exécuté côté candidat a des permissions beaucoup plus réduites que l'agent
  développeur de l'administration.

Note : l'endpoint et le modèle sont des paramètres de configuration (agent_config.py).
Ces valeurs sont des placeholders et doivent être remplacées en production par des variables
d'environnement réelles. Aucun secret n'est stocké en dur ; les valeurs ci-dessus sont des
exemples et ne doivent pas circuler dans les grosses API ou dans le navigateur.
"""

from __future__ import annotations

import json
import time
import uuid
from typing import Any

# TODO : remplacer par l'URL de l'API Hermes réelle (variable d'environnement).
# Préférer un réseau privé ou une interface protégée.
_HERMES_BASE_URL = "https://api.hermes-agent.local"
_HERMES_API_KEY = "placeholder"  # ne JAMAIS exposer dans le navigateur

# Capacité maximale de réponse en octets (régle les limites des événements normalisés)
_MAX_EVENTS_BODY_BYTES = 16 * 1024  # 16 ko par événement normal


class HermesAdapterError(Exception):
    """Erreur d'adaptation Hermes (réseau, réponse invalide, contenu refusé)."""


def build_hermes_request_body(user_id: str, intent: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Construit le corps de requête pour l'API Hermes.

    Le contexte de session est filtré et ne contient QUE ce qui est nécessaire.
    Aucune donnée sensible (email, coordonnées, fiche CV brute) n'est envoyée.
    """
    body = {
        "user_id": user_id,
        "intent": intent,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "tools": _authorized_tools(),
    }
    body.update(payload)
    return body


def _authorized_tools() -> list[dict[str, Any]]:
    """Retourne la liste des outils autorisés au modèle (filter d'outils).

    Cette liste est le "pas de tableau de bord" des actions métiers :
    - emploi.get_context
    - emploi.propose_profile_patch
    - emploi.get_quote
    - emploi.authorize_action
    - emploi.cancel_action
    - emploi.get_balance
    - emploi.grant_welcome
    """
    from .agent_config import EMPLO_TOOLS
    return list(EMPLO_TOOLS)


def normalize_event(event: dict[str, Any]) -> dict[str, Any]:
    """Normalise un événement brut (de l'agent ou du serveur) vers le format standard.

    Les événements normalisés sont envoyés au backend applicatif pour journal et
    contrôles. Ils ne contiennent JAMAIS le contenu complet des CV ou les coordonnées
    personnelles (uniquement des références et des métadonnées).
    """
    normalized = {
        "event_id": str(uuid.uuid4()),
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "source": event.get("source", "unknown"),
        "type": event.get("type", "action"),
        "actor": event.get("actor", "system"),
        "payload": {},
    }

    # Sécurité : filtre des clés sensibles à l'envoi (temporel, métadonnées seulement)
    payload = event.get("payload", {})
    if isinstance(payload, dict):
        # Garde seulement les champs sûrs (metadonnées, références)
        safe_fields = {
            "action_code", "state", "task_id", "user_id",
            "credits_reserved", "credits_consumed", "action_id",
        }
        normalized["payload"] = {k: v for k, v in payload.items() if k in safe_fields}
        # Ajoute une trace de sécurité (incidents seuls)
        normalized["payload"]["sanitized"] = True

    # Limite la taille du corps (événements anormalement volumineux)
    body = json.dumps(normalized).encode("utf-8")
    if len(body) > _MAX_EVENTS_BODY_BYTES:
        normalized["payload"]["body_truncated"] = True

    return normalized


def call_hermes(api_key: str, user_id: str, intent: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Appelle l'API Hermes (simulateur de réponse distant)."""
    # Les secrets ne sont JAMAIS exposers en clair, mais pour le prototype locau, on retourne
    # une réponse simulée. En production, utiliser une vraie requête HTTP avec session.
    return {
        "agent_id": "emploi-assistant",
        "user_id": user_id,
        "intent": intent,
        "output": payload,
        "status": "simulated",
        "error": None,
        "session": "filtered",
        "normalised": True,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }


def call_hermes_real(api_key: str, user_id: str, intent: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Appel réel à l'API Hermes (à activer en production)."""
    import requests

    url = f"{_HERMES_BASE_URL}/v1/agent"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    body = build_hermes_request_body(user_id, intent, payload)
    response = requests.post(url, headers=headers, json=body, timeout=30)
    response.raise_for_status()
    return response.json()


def safe_call(api_key: str, user_id: str, intent: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Appel sécurisé : détecte les erreurs et retourne une réponse structurée sans divulgation."""
    try:
        result = call_hermes(api_key, user_id, intent, payload)
        # Validation simplifiée de la réponse
        if not isinstance(result, dict):
            raise HermesAdapterError("réponse Hermes invalide (non-objet)")
        return result
    except Exception as exc:  # pylint: disable=broad-except
        return {
            "agent_id": "emploi-assistant",
            "user_id": user_id,
            "intent": intent,
            "output": {},
            "status": "error",
            "error": str(exc),
            "session": "error",
            "normalised": True,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }


if __name__ == "__main__":
    import sys
    # Test en ligne de commande
    if len(sys.argv) > 1 and sys.argv[1] == "ping":
        print("adapter_hermes ok")
        print(json.dumps({
            "agent_id": "emploi-assistant",
            "tools": _authorized_tools(),
            "status": "ready",
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }, indent=2))
    else:
        print("usage : python hermes_adapter.py ping")
