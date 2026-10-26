#!/usr/bin/env python3
"""Interface de ligne de commande pour le ticket T04 (profil canonique).

Usage :
    python scripts/profile.py create <email> [--objective X] [--country CI] ...
    python scripts/profile.py add-fact <email> <champ> <texte> <source> [ref]
    python scripts/profile.py confirm-fact <email> <fact_id> [valeur]
    python scripts/profile.py versions <email>
    python scripts/profile.py status <email>
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from assistantemploi.config import get, load_dotenv  # noqa: E402
from assistantemploi.accounts import create_user, get_user_by_email  # noqa: E402
from assistantemploi.db import connect, migrate  # noqa: E402
from assistantemploi.profile import (
    FIELD_CHOICES,
    add_fact,
    confirm_fact,
    create_profile,
    create_version,
    delete_fact,
    get_fact,
    get_profile_by_user,
    get_versions,
)


def _db_conn():
    load_dotenv()
    from assistantemploi.db import database_path, migrate, connect  # noqa: E402

    conn = connect(database_path())
    migrate(conn)
    return conn


def _ensure_user(conn, email: str):
    user = get_user_by_email(conn, email)
    if user is None:
        user = create_user(conn, email)
    return user


def cmd_create(args):
    user = _ensure_user(conn, args.email)
    kwargs = {k: getattr(args, k) for k in FIELD_CHOICES if getattr(args, k, None) is not None}
    profil = create_profile(conn, user["id"], **kwargs)
    print(f"Profil créé — id={profil['id']}  email={args.email}  version=1")


def cmd_add_fact(args):
    user = _ensure_user(conn, args.email)
    profil = get_profile_by_user(conn, user["id"])
    if profil is None:
        print("Aucun profil. Lancez 'profile create' d'abord.", file=sys.stderr)
        sys.exit(1)
    if args.champ not in FIELD_CHOICES:
        print(f"champ inconnu : {args.champ}. Choix: {FIELD_CHOICES}", file=sys.stderr)
        sys.exit(1)
    fact = add_fact(conn, profil["id"], args.champ, args.texte, args.source, args.ref)
    print(f"fait ajoute — id={fact['id']}  champ={args.champ}  statut=extraite_a_confirmer")


def cmd_confirm_fact(args):
    user = _ensure_user(conn, args.email)
    profil = get_profile_by_user(conn, user["id"])
    if profil is None:
        print("Aucun profil.", file=sys.stderr)
        sys.exit(1)
    fact = get_fact(conn, args.fact_id)
    if fact is None or fact["profile_id"] != profil["id"]:
        print("fait introuvable ou ne bel appartient pas à ce profil.", file=sys.stderr)
        sys.exit(1)
    value = args.valeur or fact["fact_text"]
    updated = confirm_fact(conn, fact["id"], value=value)
    print(f"factorisé — id={updated['id']}  statut=confirmee  valeur={updated['value']}")


def cmd_versions(args):
    user = _ensure_user(conn, args.email)
    profil = get_profile_by_user(conn, user["id"])
    if profil is None:
        print("Aucun profil.", file=sys.stderr)
        sys.exit(1)
    versions = get_versions(conn, profil["id"])
    print(f"profil {profil['id']} — {len(versions)} version(s)")
    for v in reversed(versions):
        print(f"  v{v['version']} créé {v['created_at']}")


def cmd_status(args):
    user = _ensure_user(conn, args.email)
    profil = get_profile_by_user(conn, user["id"])
    faits = conn.execute(
        "SELECT status, field, fact_text, source_type, value FROM profile_facts "
        "WHERE profile_id = ? ORDER BY field", (profil["id"],)
    ).fetchall()
    print(f"profil {profil['id']} — {user['email']}")
    print("champs :", {
        k: (profil[k] if profil[k] else "—") for k in (
            "objective", "country", "city", "mobility", "contract_type",
            "studies", "experiences", "projects", "skills", "languages",
            "salary_preference",
        ) if profil[k]
    })
    print("faits :")
    for f in faits:
        print(f"  [{f['status']}] {f['field']} | {f['fact_text']} "
              f"({f['source_type']}): {f['value'] or '-'}")


if __name__ == "__main__":
    load_dotenv()
    import argparse as _argparse

    parser = _argparse.ArgumentParser(prog="profile", description="Gestion des profils (T04)")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("create")
    p.add_argument("email")
    for champ in FIELD_CHOICES:
        p.add_argument(f"--{champ}", default=None)
    p.set_defaults(func=cmd_create)

    p = sub.add_parser("add-fact")
    p.add_argument("email")
    p.add_argument("champ")
    p.add_argument("texte")
    p.add_argument("source")
    p.add_argument("ref", nargs="?", default=None)
    p.set_defaults(func=cmd_add_fact)

    p = sub.add_parser("confirm-fact")
    p.add_argument("email")
    p.add_argument("fact_id")
    p.add_argument("valeur", nargs="?")
    p.set_defaults(func=cmd_confirm_fact)

    p = sub.add_parser("versions")
    p.add_argument("email")
    p.set_defaults(func=cmd_versions)

    p = sub.add_parser("status")
    p.add_argument("email")
    p.set_defaults(func=cmd_status)

    args = parser.parse_args()
    conn = _db_conn()
    try:
        args.func(args)
    finally:
        conn.close()
