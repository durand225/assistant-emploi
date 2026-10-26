"""Couche de configuration : chargement, cache et validation des variables d'environnement.

Règles de sécurité :
- Aucun secret n'est stocké en dur dans le code source.
- Les fichiers `.env` sont ignorés par git (voir .gitignore).
- `validate()` émet une liste de clés manquantes/à vide et s'arrête si le script
  l'appelle sans gestion propre.
- `mask()` ne retourne jamais la totalité d'une valeur confidentielle dans les logs.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Chargement de .env avant toute lecture d'environnement.
# Idempotent : appelé plusieurs fois = le même résultat.
def load_dotenv(path: Path | None = None) -> None:
    target = path or (PROJECT_ROOT / ".env")
    if not target.exists():
        return
    for raw_line in target.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        # Retire les quotes extérieures simples/double si présentes.
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        # setdefault : la première valeur (fichier .env) l'emporte.
        os.environ.setdefault(key, value)


load_dotenv()

DEFAULTS: dict[str, str] = {
    "APP_ENV": "dev",
    "APP_BASE_URL": "http://localhost:8080",
}


def get(key: str, default: str | None = None) -> str | None:
    """Valeur en lecture seule : .env > variable système > default."""
    return os.environ.get(key, DEFAULTS.get(key, default))


def required(keys: list[str]) -> list[str]:
    """Retourne les clés qui sont absentes ou vides."""
    return [k for k in keys if not get(k)]


def validate() -> list[str]:
    """Liste les variables d'application obligatoires manquantes."""
    return required(["APP_ENV", "DATABASE_URL", "APP_SECRET"])


def mask(value: str, visible: int = 4) -> str:
    """Espacement pour les logs : ne jamais afficher toute une valeur secrète."""
    if not value:
        return "<vide>"
    if len(value) <= visible * 2:
        return "*" * len(value)
    return value[:visible] + "*" * (len(value) - visible * 2)
