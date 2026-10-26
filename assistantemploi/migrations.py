"""Liste versionnée et ordonnée des migrations de la base de données.

Chaque entrée : (numéro, script SQL). Les numéros sont sans lacune pour garantir
l'ordre et la reproductibilité. Les scripts doivent être idempotents
(`IF NOT EXISTS`) et ne jamais modifier les données déjà enregistrées.
"""

from __future__ import annotations

MIGRATIONS: list[tuple[int, str]] = [
    (
        1,
        """
        CREATE TABLE IF NOT EXISTS _migrations (
            version INTEGER PRIMARY KEY,
            applied_at TEXT NOT NULL DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS users (
            id           TEXT PRIMARY KEY,
            email        TEXT NOT NULL UNIQUE,
            email_verified_at TEXT,
            created_at   TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at   TEXT NOT NULL DEFAULT (datetime('now'))
        );
        """,
    ),
    (
        2,
        """
        CREATE TABLE IF NOT EXISTS registration_tokens (
            id           TEXT PRIMARY KEY,
            user_id      TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            token        TEXT NOT NULL UNIQUE,
            created_at   TEXT NOT NULL DEFAULT (datetime('now')),
            used_at      TEXT,
            expires_at   TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_registration_tokens_user_id ON registration_tokens(user_id);
    """,
    ),
    (
        3,
        """
        CREATE TABLE IF NOT EXISTS wallets (
            id            TEXT PRIMARY KEY,
            user_id       TEXT NOT NULL UNIQUE REFERENCES users(id) ON DELETE CASCADE,
            welcome_granted INTEGER NOT NULL DEFAULT 0,
            created_at    TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at    TEXT NOT NULL DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS credit_lots (
            id        TEXT PRIMARY KEY,
            wallet_id TEXT NOT NULL REFERENCES wallets(id) ON DELETE CASCADE,
            kind      TEXT NOT NULL CHECK (kind IN ('welcome', 'purchase')),
            amount    INTEGER NOT NULL CHECK (amount > 0),
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS ledger_entries (
            id         TEXT PRIMARY KEY,
            wallet_id  TEXT NOT NULL REFERENCES wallets(id) ON DELETE CASCADE,
            amount     INTEGER NOT NULL CHECK (amount <> 0),
            lot_id     TEXT REFERENCES credit_lots(id) ON DELETE SET NULL,
            description TEXT NOT NULL DEFAULT '',
            key        TEXT,
            created_at  TEXT NOT NULL DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS reservations (
            id               TEXT PRIMARY KEY,
            wallet_id        TEXT NOT NULL REFERENCES wallets(id) ON DELETE CASCADE,
            amount           INTEGER NOT NULL CHECK (amount > 0),
            key              TEXT,
            status           TEXT NOT NULL CHECK (status IN ('active', 'released', 'consumed')),
            created_at       TEXT NOT NULL DEFAULT (datetime('now')),
            released_at      TEXT,
            consumed_at      TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_wallets_user_id ON wallets(user_id);
        CREATE INDEX IF NOT EXISTS idx_credit_lots_wallet ON credit_lots(wallet_id);
        CREATE INDEX IF NOT EXISTS idx_ledger_wallet ON ledger_entries(wallet_id);
        CREATE INDEX IF NOT EXISTS idx_reservations_wallet ON reservations(wallet_id);
    """,
    ),
    (
    4,
        """
        CREATE TABLE IF NOT EXISTS profiles (
            id          TEXT PRIMARY KEY,
            user_id     TEXT NOT NULL UNIQUE REFERENCES users(id) ON DELETE CASCADE,
            objective   TEXT,
            country     TEXT,
            city        TEXT,
            mobility    TEXT,
            contract_type TEXT,
            studies     TEXT,
            experiences TEXT,
            projects    TEXT,
            skills      TEXT,
            languages   TEXT,
            salary_preference TEXT,
            created_at   TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at   TEXT NOT NULL DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS profile_facts (
            id           TEXT PRIMARY KEY,
            profile_id   TEXT NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
            field        TEXT NOT NULL,
            fact_text    TEXT NOT NULL,
            source_type  TEXT NOT NULL,
            source_ref   TEXT,
            status       TEXT NOT NULL
                CHECK (status IN ('extraite_a_confirmer', 'confirmee', 'contradictoire', 'supprimee')),
            value        TEXT,
            created_at   TEXT NOT NULL DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS profile_versions (
            id             TEXT PRIMARY KEY,
            profile_id     TEXT NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
            version        INTEGER NOT NULL,
            fields_json    TEXT NOT NULL,
            facts_json     TEXT NOT NULL,
            created_at     TEXT NOT NULL DEFAULT (datetime('now'))
        );

        CREATE INDEX IF NOT EXISTS idx_profile_facts_profile ON profile_facts(profile_id);
        CREATE INDEX IF NOT EXISTS idx_profile_versions_profile ON profile_versions(profile_id);
    """,
    ),
    (
        5,
        """
        CREATE TABLE IF NOT EXISTS action_quotes (
            quote_id         TEXT PRIMARY KEY,
            action_code      TEXT NOT NULL,
            credits          INTEGER NOT NULL CHECK (credits > 0),
            available_balance INTEGER NOT NULL DEFAULT 0,
            inputs_hash      TEXT NOT NULL,
            tariff_version   INTEGER NOT NULL DEFAULT 1,
            expires_at       TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_action_quotes_action_code ON action_quotes(action_code);

        CREATE TABLE IF NOT EXISTS actions (
            id               TEXT PRIMARY KEY,
            reservation_id   TEXT NOT NULL,
            quote_id         TEXT NOT NULL REFERENCES action_quotes(quote_id) ON DELETE CASCADE,
            idempotency_key  TEXT NOT NULL UNIQUE,
            owner_id         TEXT NOT NULL,
            action_code      TEXT NOT NULL,
            state            TEXT NOT NULL DEFAULT 'reserved',
            started_at       TEXT,
            completed_at     TEXT,
            credits_consumed INTEGER,
            credits_reserved INTEGER,
            result_ref       TEXT,
            created_at       TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_actions_owner ON actions(owner_id);
        CREATE INDEX IF NOT EXISTS idx_actions_state ON actions(state);

        CREATE TABLE IF NOT EXISTS audio_uploads (
            id                 TEXT PRIMARY KEY,
            user_id            TEXT NOT NULL,
            audio_path         TEXT NOT NULL,
            duration_seconds   INTEGER NOT NULL,
            mime_type          TEXT NOT NULL,
            status             TEXT NOT NULL DEFAULT 'uploaded',
            created_at         TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at         TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_audio_uploads_user ON audio_uploads(user_id);

        CREATE TABLE IF NOT EXISTS transcriptions (
            id           TEXT PRIMARY KEY,
            audio_id     TEXT NOT NULL REFERENCES audio_uploads(id) ON DELETE CASCADE,
            text         TEXT NOT NULL,
            created_at   TEXT NOT NULL DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS support_cases (
            id           TEXT PRIMARY KEY,
            user_id      TEXT NOT NULL,
            subject      TEXT NOT NULL,
            category     TEXT NOT NULL DEFAULT 'generale',
            priority     TEXT NOT NULL DEFAULT 'moyen',
            description  TEXT NOT NULL DEFAULT '',
            status       TEXT NOT NULL DEFAULT 'ouvrir',
            created_at   TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at   TEXT,
            resolved_at  TEXT,
            resolution   TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_support_cases_user ON support_cases(user_id);
        CREATE INDEX IF NOT EXISTS idx_support_cases_status ON support_cases(status);

        CREATE TABLE IF NOT EXISTS payment_pending (
            id               TEXT PRIMARY KEY,
            user_id          TEXT NOT NULL,
            pack             TEXT NOT NULL,
            amount_cents     INTEGER NOT NULL,
            transaction_id   TEXT NOT NULL UNIQUE,
            status           TEXT NOT NULL DEFAULT 'en_attente',
            note             TEXT NOT NULL DEFAULT '',
            verified_at      TEXT,
            created_at       TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_payment_pending_user ON payment_pending(user_id);

        -- Environnement de paiement (production/sandbox)
        CREATE TABLE IF NOT EXISTS _payment_env (
            id      INTEGER PRIMARY KEY AUTOINCREMENT,
            env     TEXT NOT NULL DEFAULT 'production'
        );
        INSERT OR IGNORE INTO _payment_env (env) VALUES ('production');

        CREATE TABLE IF NOT EXISTS tasks (
            id              TEXT PRIMARY KEY,
            user_id         TEXT NOT NULL,
            action_code     TEXT NOT NULL,
            state           TEXT NOT NULL DEFAULT 'en_attente',
            driver_id       TEXT,
            created_at      TEXT NOT NULL DEFAULT (datetime('now')),
            started_at      TEXT,
            completed_at    TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_tasks_user ON tasks(user_id);
        CREATE INDEX IF NOT EXISTS idx_tasks_state ON tasks(state);

        CREATE TABLE IF NOT EXISTS errors (
            id            TEXT PRIMARY KEY,
            user_id       TEXT,
            action_code   TEXT,
            message       TEXT NOT NULL,
            stack         TEXT,
            created_at    TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_errors_created ON errors(created_at);
    """,
    ),
]
