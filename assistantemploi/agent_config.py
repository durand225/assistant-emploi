# Configuration d'agent emploi-assistant
# Spécification technique H1 v1.1 (25 octobre 2026)
# Cible : Hermes Agent de Nous Research
# Référence produit : PRD Agent emploi v2, modèle à crédits

# =============================================================================
# 1. Identité de l'agent
# =============================================================================

# Nom de l'agent (identifiant technique)
AGENT_NAME = "emploi-assistant"

# Version de l'agent
AGENT_VERSION = "1.1.0"

# Langue par défaut (modulable par pays/prise de décision)
DEFAULT_LANG = "fr"

# Pays cible du lancement
TARGET_COUNTRY = "CI"

# URL de base (à configurer en production)
BASE_URL = "http://localhost:8080"

# Clé secrète de session (générée en production, jamais stockée en dur)
SECRET_KEY = "change-me"

# Environnement (dev | test | prod)
ENV = "dev"

# Durée de vie des devis (en minutes)
QUOTE_TTL_MINUTES = 15

# Limite de message (caractères)
MESSAGE_LIMIT = 8000

# Limite audio (secondes, T05)
AUDIO_MAX_SECONDS = 60

# Limite fichier (Mo, T06)
FILE_MAX_MB = 10

# Limite CV (pages, T09)
CV_MAX_PAGES = 10

# Nombre maximum de résultats pour une recherche (T08)
SEARCH_MAX_RESULTS = 20

# Limite d'effort de clarification (tours max, T08)
CLARIFY_MAX_ROUNDS = 3

# =============================================================================
# 2. Architecture recommandée
# =============================================================================

# Mapping entre les composants et leurs responsabilités.
ARCHITECTURE = {
    "interface_web": {
        "responsibility": "Chat, vocal, pièces jointes, cartes d'offres, aperçu CV, confirmation des coûts et recharge",
        "layers": ["web", "mobile"],
    },
    "backend_applicatif": {
        "responsibility": "Authentification, propriété, profil canonique, conversations, tarifs, devis, portefeuille et paiements",
        "layers": ["api", "services"],
    },
    "coordinateur_taches": {
        "responsibility": "Réservation, lancement, annulation, limites, reprise, validation finale et consommation",
        "layers": ["orchestrator"],
    },
    "adaptateur_hermes": {
        "responsibility": "Contexte de session filtré, outils autorisés, appels Hermes et normalisation des événements",
        "layers": ["adapter"],
    },
    "agent_hermes": {
        "responsibility": "Comprendre, clarifier, proposer les actions, expliquer les offres et rédiger des contenus structurés",
        "layers": ["agent", "llm"],
    },
    "services_metier": {
        "responsibility": "Sources approuvées, extraction, transcription, normalisation, rendu PDF/DOCX et contrôles",
        "layers": ["services"],
    },
}

# =============================================================================
# 3. Outils métier (emploi.*) — accessibles par MCP ou adaptateurs serveur
# =============================================================================

# Liste des outils exposés à l'agent (et aux services), accessibles par le backend.
# Le navigateur ne reçoit JAMAIS la clé API Hermite, les secrets MCP ou les droits de paiement.
EMPLO_TOOLS = [
    {
        "name": "emploi.get_context",
        "description": "Récupère les informations contextuelles de l'utilisateur (compte, profil, dernière action, solde).",
        "params": {
            "user_id": {"type": "string", "description": "Identifiant de l'utilisateur"},
        },
        "returns": {
            "user_id": "string",
            "account_status": "string",  # verified, unverified, etc.
            "profile_version": "integer",
            "balance": "integer",  # crédits disponibles
            "last_action": "object | null",
            "last_seen_at": "string | null",
        },
    },
    {
        "name": "emploi.propose_profile_patch",
        "description": "Propose une mise à jour du profil basée sur une extraction ou une correction.",
        "params": {
            "user_id": {"type": "string"},
            "facts": {
                "type": "array",
                "description": "Nouveaux faits à ajouter avec leur provenance",
                "items": {
                    "type": "object",
                    "properties": {
                        "fact": {"type": "string"},
                        "source_type": {"type": "string"},
                        "source": {"type": "string"},
                        "status": {"type": "string", "enum": ["extraite_a_confirmer", "confirmee", "contradictoire", "supprimee"]},
                    },
                },
            },
        },
        "returns": {
            "profile_version": "integer",
            "facts": "array",
            "conflicts": "array",
        },
    },
    {
        "name": "emploi.get_quote",
        "description": "Calcule un devis pour une action (CHAT, IMPORT, SEARCH, ANALYZE, CV, REVISE) avec prix figé.",
        "params": {
            "user_id": {"type": "string"},
            "action_code": {"type": "string", "enum": ["CHAT", "IMPORT", "SEARCH", "ANALYZE", "CV", "REVISE"]},
            "inputs_hash": {"type": "string", "description": "Hash des entrées (pour la version du devis)"},
        },
        "returns": {
            "quote_id": "string",
            "action_code": "string",
            "credits": "integer",
            "available_balance": "integer",
            "inputs_hash": "string",
            "tariff_version": "integer",
            "expires_at": "string",
            "included_content": "string",
        },
    },
    {
        "name": "emploi.authorize_action",
        "description": "Autorise et réserve une action (débit atomique, vérification du solde).",
        "params": {
            "quote_id": {"type": "string"},
            "idempotency_key": {"type": "string"},
            "owner_id": {"type": "string"},
        },
        "returns": {
            "reservation_id": "string",
            "action_id": "string",
            "status": "string",
            "credits_reserved": "integer",
        },
    },
    {
        "name": "emploi.cancel_action",
        "description": "Annule une action en attente ou en cours (libère la réservation).",
        "params": {
            "action_id": {"type": "string", "description": "Identifiant de l'action à annuler"},
            "owner_id": {"type": "string"},
        },
        "returns": {
            "action_id": "string",
            "status": "string",
            "credits_released": "integer | null",
        },
    },
    {
        "name": "emploi.get_balance",
        "description": "Lecture du solde de crédits d'un utilisateur (lecture seule, pas de débit).",
        "params": {
            "user_id": {"type": "string"},
        },
        "returns": {
            "user_id": "string",
            "available_balance": "integer",
            "reserved_balance": "integer",
            "pending_actions": "integer",
        },
    },
    {
        "name": "emploi.grant_welcome",
        "description": "Octroie le bonus unique de 15 crédits à un compte vérifié (une seule fois).",
        "params": {
            "user_id": {"type": "string"},
        },
        "returns": {
            "user_id": "string",
            "granted": "boolean",
            "welcome_lot_id": "string | null",
            "balance_after": "integer",
        },
        "notes": "Octroi unique par compte. Double octroi interdit (verrouillage atomique).",
    },
]

# =============================================================================
# 4. Schémas d'intentions (sorties IA du modèle)
# =============================================================================

# Intention retournée par l'agent (valide par le serveur)
# CHAT, IMPORT, SEARCH, ANALYZE, CV, REVISE, CLARIFY, HELP, ERROR
AGENT_INTENTIONS = {
    "CHAT": {
        "description": "Réponse conversationnelle",
        "required_fields": ["text", "approved_facts", "conflicts", "missing_inputs"],
    },
    "IMPORT": {
        "description": "Import de CV (PDF/DOCX) et extraction de faits",
        "required_fields": ["file", "accepted_facts", "missing_fields", "warnings"],
    },
    "SEARCH": {
        "description": "Recherche d'offres multi-source",
        "required_fields": ["criteria", "sources", "results", "sources_consulted", "warnings"],
    },
    "ANALYZE": {
        "description": "Analyse d'une offre extérieure (lien ou texte)",
        "required_fields": ["offer", "matches", "missing", "warnings"],
    },
    "CV": {
        "description": "Génération d'un CV adapté à une offre",
        "required_fields": ["profile_version", "offer", "sections", "controls", "warnings"],
    },
    "REVISE": {
        "description": "Révision substantielle d'un CV",
        "required_fields": ["document_version", "updates", "controls", "warnings"],
    },
    "CLARIFY": {
        "description": "Demande de clarification à l'utilisateur",
        "required_fields": ["questions", "context", "priority"],
    },
    "HELP": {
        "description": "Aide ou indication d'utilisation",
        "required_fields": ["message", "options"],
    },
    "ERROR": {
        "description": "Erreur métier ou technique",
        "required_fields": ["code", "message", "recovery_hints"],
    },
}

# Codes d'erreur métier (CR01-CR12 + autres)
ERROR_CODES = [
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
]

# =============================================================================
# 5. Modèles de données (clés)
# =============================================================================

# Utilisateur
USER_FIELDS = [
    "id", "email", "email_verified_at", "created_at", "updated_at",
]

# Profil et versions
PROFILE_FIELDS = [
    "id", "user_id", "objective", "country", "city", "work_mobility", "contract_type",
    "contract_duration", "study_level", "experience_years", "skills", "languages",
    "salary_min", "salary_max", "salary_currency", "created_at", "updated_at",
]

# Fait (provenance-encodé)
FACT_FIELDS = [
    "id", "profile_id", "key", "value", "provenance", "source_type", "source", "status", "confirmed_at", "created_at",
]

# Portefeuille et crédits
WALLET_FIELDS = ["id", "user_id", "available_balance", "created_at", "updated_at"]

# Lots de crédits
CREDIT_LOT_FIELDS = [
    "id", "wallet_id", "lot_type", "amount", "created_at", "expires_at", "is_active",
]

# Journal (ledger) — écritures immuables
LEDGER_ENTRY_FIELDS = [
    "id", "wallet_id", "amount", "lot_id", "action", "key", "created_at",
]

# Réservations
RESERVATION_FIELDS = [
    "id", "action_id", "credits", "status", "expires_at", "created_at",
]

# Actions
ACTION_FIELDS = [
    "id", "reservation_id", "quote_id", "action_code", "inputs_hash", "owner_id",
    "status", "started_at", "completed_at", "credits_consumed", "result_ref", "created_at",
]

# Offres (JobOccurrence)
OFFER_FIELDS = [
    "id", "source_id", "source_url", "title", "employer", "country", "city",
    "contract_type", "work_mode", "deadline", "salary_min", "salary_max", "salary_currency",
    "requirements", "translation", "status", "published_at", "collected_at", "checked_at",
    "created_at", "updated_at",
]

# =============================================================================
# 6. Intégrations
# =============================================================================

# Adapteur Hermes (connexion serveur→LLM, outils autorisés)
HERMES_ADAPTER = {
    "endpoint": "https://api.hermes-agent.nousresearch.com/v1",
    "model": "gpt-4o-mini",
    "timeout_seconds": 30,
    "tools": EMPLO_TOOLS,
    "max_tokens": 4096,
}

# Paiement GeniusPay (sandbox en développement)
GENIUSPAY = {
    "sandbox": True,
    "base_url": "https://api-sandbox.geniuspay.ci",
    "webhook_secret": "change-me",
    "features": ["payments", "refunds", "subscriptions"],
}

# Sources approuvées (generation T07)
SOURCES = [
    # {"id": "source_1", "country": "CI", "name": "...", "access": "api", "rights": "..."},
]

# =============================================================================
# 7. Règles de facturation (CR01-CR12)
# =============================================================================

CREDITS = {
    "CHAT": 1,
    "IMPORT": 3,
    "SEARCH": 8,
    "ANALYZE": 3,
    "CV": 10,
    "REVISE": 3,
    "READ": 0,
    "EDIT": 0,
    "REPAIR": 0,
}

WELCOME_BONUS = 15

# Restrictions critiques
CR_RULES = {
    "CR01": "Le serveur fixe le coût ; aucune valeur de crédit fournie par le navigateur ne fait autorité.",
    "CR02": "Une action métier possède une clé d'idempotence et au maximum une consommation nette.",
    "CR03": "Vérifier et réserver le solde dans une transaction atomique avant tout appel coûteux.",
    "CR04": "Consommer uniquement après résultat validé et sauvegardé ; voir un chargement ne suffit pas.",
    "CR05": "Un échec de service libère la réservation ; retries et contrôles ne sont jamais refacturés.",
    "CR06": "Un message déclenchant une autre action ne cumule pas CHAT avec cette action.",
    "CR07": "Les clarifications nécessaires à l'action autorisée font partie de son prix.",
    "CR08": "Les lectures, téléchargements et modifications manuelles restent accessibles à zéro crédit.",
    "CR09": "La recharge ouvre un solde ; elle ne déclenche pas automatiquement une action ancienne.",
    "CR10": "Un devis fige tarif et périmètre ; une extension nécessite une nouvelle autorisation.",
    "CR11": "Une recherche sans offre n'est pas une panne ; sa règle de facturation est annoncée.",
    "CR12": "Tous les mouvements sont auditables ; aucune correction du solde par simple écrasement.",
}

# =============================================================================
# 8. Configuration de test/développement
# =============================================================================

DEV_CONFIG = {
    "db_path": "data/assistant-emploi.db",
    "auto_migrate": True,
    "seed_demo": False,
    "prices_sandbox": True,
    "log_level": "debug",
}

# =============================================================================
# 9. Notes de compatibilité
# =============================================================================

# - Le navigateur ne reçoit jamais la clé API Hermite, les secrets MCP, les clés fournisseurs
#   ou des droits de modification du portefeuille. Il appelle le backend applicatif.
# - Le backend contacte Hermes sur un réseau privé ou une interface protégée.
# - Le support utilise des contrôleurs séparés et audités.
# - Hermes n'a ni les secrets du marchand ni un outil de paiement ou de remboursement.
# - Les prix sont configurables ; seul le serveur et son catalogue publié font autorité.
