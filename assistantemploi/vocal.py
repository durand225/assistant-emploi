"""Service vocal — T05.

Règles :
- 60 secondes maximum par message vocal.
- Suppression de l'audio brut après transcription validée (ou après 24h).
- Transcription brute non facturée séparément.
- Si le micro est absent, proposer immédiatement la saisie de texte.
- Les transcriptions sont attachées au compte ; aucune transcription exprimée
  dans les logs techniques.

Note : la transcription leverage un fournisseur STT externe (à configurer via
l'environnement). Pour le MVP, un mode test deterministic génère une
transcription à partir du contenu audio (durée + id). Les logs ne contiennent
pas le contenu audio.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from uuid import uuid4

MAX_AUDIO_SECONDS = 60
AUDIO_STATUSES = ("uploaded", "processing", "transcribed", "error")

# Approximation test: la transcription détermine un ID pour le couple (audio_id, duration)
# jusqu'à ce qu'un vrai fournisseur STT soit connecté.
def _mock_transcription(audio_id: str, duration_seconds: int) -> str:
    return f"transcription {duration_seconds}s {audio_id[:8]}"


def create_audio_upload(
    conn: sqlite3.Connection,
    user_id: str,
    audio_path: str,
    duration_seconds: int,
    mime_type: str,
) -> sqlite3.Row:
    """Enregistre la demande vocale côté serveur."""
    if duration_seconds > MAX_AUDIO_SECONDS:
        raise ValueError(f"audio trop long : {duration_seconds}s > {MAX_AUDIO_SECONDS}s")
    if not audio_path:
        raise ValueError("chemin audio obligatoire")
    conn.execute(
        "INSERT INTO audio_uploads (id, user_id, audio_path, duration_seconds, mime_type, status, created_at) "
        "VALUES (?, ?, ?, ?, ?, 'uploaded', ?)",
        (uuid4().hex, user_id, audio_path, duration_seconds, mime_type, _now()),
    )
    conn.commit()
    # The `id` is a UUID (TEXT PRIMARY KEY), so lastrowid isn't the id we inserted.
    return conn.execute(
        "SELECT * FROM audio_uploads WHERE user_id = ? ORDER BY created_at DESC LIMIT 1",
        (user_id,),
    ).fetchone()


def get_audio(conn: sqlite3.Connection, audio_id: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM audio_uploads WHERE id = ?", (audio_id,)
    ).fetchone()


def transcription_required(conn: sqlite3.Connection, user_id: str) -> sqlite3.Row | None:
    """Dernier enregistrement vocal de l'utilisateur."""
    return conn.execute(
        "SELECT * FROM audio_uploads WHERE user_id = ? AND status = 'uploaded' "
        "ORDER BY created_at DESC LIMIT 1",
        (user_id,),
    ).fetchone()


def transcribe_audio(conn: sqlite3.Connection, audio_id: str) -> sqlite3.Row:
    """Transcrit l'audio. Mode test deterministic jusqu'à STT en production."""
    audio = get_audio(conn, audio_id)
    if audio is None:
        raise ValueError("audio introuvable")
    if audio["status"] != "uploaded":
        raise ValueError(f"audio déjà traité (status={audio['status']})")

    conn.execute(
        "UPDATE audio_uploads SET status = 'processing', updated_at = ? WHERE id = ?",
        (_now(), audio_id),
    )
    conn.commit()

    # Transcription brute (mode test). En production : appel STT.
    text = _mock_transcription(audio_id, int(audio["duration_seconds"]))

    transcript_id = uuid4().hex
    conn.execute(
        "INSERT INTO transcriptions (id, audio_id, text, created_at) VALUES (?, ?, ?, ?)",
        (transcript_id, audio_id, text, _now()),
    )
    conn.execute(
        "UPDATE audio_uploads SET status = 'transcribed', updated_at = ? WHERE id = ?",
        (_now(), audio_id),
    )
    conn.commit()
    # Retourne la transcription, pas l'audio.
    return get_transcription(conn, transcript_id)


def get_transcription(conn: sqlite3.Connection, transcription_id: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM transcriptions WHERE id = ?", (transcription_id,)
    ).fetchone()


def purge_audio(conn: sqlite3.Connection, user_id: str) -> int:
    """Supprime les audios bruts après transcription validée (ou 24h)."""
    now = _now()
    cur = conn.execute(
        "DELETE FROM audio_uploads WHERE user_id = ? AND status IN ('transcribed','error') "
        "AND created_at < datetime(?, '-24 hours')",
        (user_id, now),
    )
    conn.commit()
    return cur.rowcount


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
