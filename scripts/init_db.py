"""Outil CLI de fondation T01 : initialisation et vérification de la base.

Rôle :
- garantit l'existence d'un `.env` (créé depuis `.env.example`, clé secrète aléatoire
  si absente) ;
- valide les variables obligatoires ;
- initialise la base de données à l'emplacement configéré et applique les migrations ;
- s'arrête sans lancer de tâche, de paiement ou de compte.
"""

from __future__ import annotations

import secrets
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from assistantemploi.config import get, load_dotenv  # noqa: E402
from assistantemploi.db import connect, migrate, database_path  # noqa: E402
from assistantemploi.migrations import MIGRATIONS  # noqa: E402


def ensure_env_file() -> None:
    """Crée `.env` à partir de `.env.example` si absent, avec un secret généré."""
    project = Path(__file__).resolve().parent.parent
    env = project / ".env"
    example = project / ".env.example"

    if env.exists():
        return

    if not example.exists():
        print("Erreur : .env.example manquant. Copiez .env.example vers .env puis",
              "modifiez les valeurs.", file=sys.stderr)
        sys.exit(1)

    content = example.read_text(encoding="utf-8")
    if "APP_SECRET=" in content:
        content = content.replace(
            "APP_SECRET=change-me-in-production",
            f"APP_SECRET={secrets.token_urlsafe(48)}",
        )
    else:
        content += "\nAPP_SECRET=" + secrets.token_urlsafe(48) + "\n"
    env.write_text(content, encoding="utf-8")


def main() -> None:
    # .env doit exister AVANT d'importer config (le chargement a lieu au niveau
    # du module en Python). On le crée donc en premier.
    ensure_env_file()
    load_dotenv()  # re-charge .env si celui-ci vient d'être créé

    missing = [k for k in ("APP_ENV", "DATABASE_URL", "APP_SECRET") if not get(k)]
    if missing:
        print("Erreur : variables d'environnement manquantes : " + ", ".join(missing),
              file=sys.stderr)
        sys.exit(1)

    db_path = database_path()
    conn = connect(db_path)
    try:
        applied = migrate(conn)
        print(f"[T01] Base initialisée — migrations appliquées : {applied}")
        print(f"[T01] Chemin de la base : {db_path or '<mémoire>'}")
        print(f"[T01] Environnement : {get('APP_ENV')}")
        print("[T01] Aucune action IA, de paiement ou de compte n'a été lancée.")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
