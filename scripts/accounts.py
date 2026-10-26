#!/usr/bin/env python3
"""Interface de ligne de commande pour le ticket T02 (compte + vérification email).

Usage :
    python scripts/accounts.py register <email>
    python scripts/accounts.py link <email>
    python scripts/accounts.py verify <token>
    python scripts/accounts.py status <email>
    python scripts/accounts.py test-isolation
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from assistantemploi.config import get, load_dotenv  # noqa: E402
from assistantemploi.accounts import (  # noqa: E402
    check_owner,
    create_user,
    get_user_by_email,
    get_verification_status,
    issue_verification_token,
    verify_email,
)
from assistantemploi.db import connect, migrate  # noqa: E402
from scripts.init_db import ensure_env_file  # noqa: E402


def _db_conn():
    from assistantemploi.db import database_path, connect, migrate  # noqa: F402

    conn = connect(database_path())
    migrate(conn)
    return conn


def cmd_register(conn, email: str) -> None:
    try:
        row = create_user(conn, email)
    except ValueError as exc:
        print(f"Erreur : {exc}", file=sys.stderr)
        sys.exit(1)
    print(f"Compte créé — id : {row['id']}  (créé={row['created']})  email={row['email']}")


def cmd_link(conn, email: str) -> None:
    user = get_user_by_email(conn, email)
    if user is None:
        print(f"Erreur : aucun compte pour {email!r}. Lancez 'register' d'abord.", file=sys.stderr)
        sys.exit(1)
    token = issue_verification_token(conn, user["id"])
    print(f"Lien de vérification : http://localhost:8080/verify?token={token[:8]}...  (token={token})")


def cmd_verify(conn, token: str) -> None:
    res = verify_email(conn, token)
    print(f"Vérification : {'OK (email vérifié)' if res['verified'] else 'Refusé - ' + res['reason']}")


def cmd_status(conn, email: str) -> None:
    user = get_user_by_email(conn, email)
    if user is None:
        print(f"Aucun compte pour {email!r}.")
        return
    print(f"Compte {user['id']} ({user['email']}) : {'vérifié' if user['email_verified_at'] else 'non vérifié'}")


def cmd_test_isolation(conn) -> None:
    """Démonstration de la frontière de propriété entre deux comptes."""
    from assistantemploi.accounts import is_owner  # local import pour l'exemple

    a = create_user(conn, "a@exemple.test")
    b = create_user(conn, "b@exemple.test")
    token_a = issue_verification_token(conn, a["id"])
    token_b = issue_verification_token(conn, b["id"])

    # L'un des deux comptes (A) est validé par son token, avant les essais.
    verify_email(conn, token_a)

    print(f"Compte A (propriétaire de ses données) : {a['id']}")
    print(f"Compte B (autre comptent)              : {b['id']}")

    # B tente d'agir pour A.
    print("\n---tentative B sur A---")
    try:
        check_owner(b["id"], a["id"])
        print("REFUS : check_owner(A, B) n'a pas levé d'erreur (problème de frontière).")
        ok = False
    except PermissionError as exc:
        print(f"OK (frontière respectée) : {exc}")
        ok = True

    # A ne peut pas s'instruser sur B de façon croisée.
    print("\n---tentative A sur B---")
    try:
        check_owner(a["id"], b["id"])
        print("REFUS : check_owner(B, A) n'a pas levé d'erreur (problème de frontière).")
        ok_b = False
    except PermissionError:
        print("OK (frontière respectée) : A est refusé sur B.")
        ok_b = True

    # Vérification de séparation des identités.
    status_a = get_verification_status(conn, a["id"])
    status_b = get_verification_status(conn, b["id"])
    print(f"\nÉtat du compte A : {status_a['email_verified']}")
    print(f"État du compte B : {status_b['email_verified']}")

    passed = ok and ok_b and status_a["email_verified"] and not status_b["email_verified"]
    print(f"\nRésultat isolation : {'PASS' if passed else 'FAIL'}")
    sys.exit(0 if passed else 1)


def main() -> None:
    load_dotenv()
    ensure_env_file()

    parser = argparse.ArgumentParser(prog="accounts", description="Compte et vérification email (T02)")
    sub = parser.add_subparsers(dest="command", required=True)

    p_reg = sub.add_parser("register")
    p_reg.add_argument("email")
    p_reg.set_defaults(func=cmd_register)

    p_link = sub.add_parser("link")
    p_link.add_argument("email")
    p_link.set_defaults(func=cmd_link)

    p_ver = sub.add_parser("verify")
    p_ver.add_argument("token")
    p_ver.set_defaults(func=cmd_verify)

    p_stat = sub.add_parser("status")
    p_stat.add_argument("email")
    p_stat.set_defaults(func=cmd_status)

    p_iso = sub.add_parser("test-isolation")
    p_iso.set_defaults(func=cmd_test_isolation)

    args = parser.parse_args()
    conn = _db_conn()
    try:
        if args.command == "test-isolation":
            cmd_test_isolation(conn)
        elif args.command == "verify":
            cmd_verify(conn, args.token)
        else:
            args.func(conn, args.email)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
