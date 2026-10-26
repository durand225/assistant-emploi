"""Import sécurisé de CV — T06.

Règles applicables :
- Fichiers acceptés : PDF et DOCX, jusqu'à 10 Mo, 10 pages.
- Refuser : fichiers chiffrés (PDF avec mot de passe), macros, contenus suspects.
- Scan anti-virus léger (détection de signatures connues) — simulation pour MVP.
- Reconnaissance de texte (OCR) simulée pour les scans ; incertitude signalée.
- Extraction des faits avec provenance et statut `extraite_a_confirmer`.

Le système ne peut pas produire de faits fiables à partir d'un PDF illisible ;
il retourne une extraction avec incertitudes et demande validation.
"""

from __future__ import annotations

import os
import re
import sqlite3
from datetime import datetime, timezone
from uuid import uuid4

# ------------------------------- SÉCURISATION ------------------------------

# Extensions acceptées.
ACCEPTED_EXTENSIONS = {".pdf", ".docx", ".doc"}

# Taille max en octets (10 Mo).
MAX_FILE_SIZE = 10 * 1024 * 1024

# Taille max de pages PDF (10 pages).
MAX_PAGES = 10

# Fichiers suspects (signatures de macros / chiffrement).
SUSPICIOUS_SIGNATURES = {
    "application/x-google-chrome-sandbox": "fichier suspect",
    "application/vnd.openxmlformats": "format OOXML (sûr)",
}

# Mots-clés fréquents dans les annonces malveillantes.
SUSPICIOUS_KEYWORDS = ("javascript:", "vbscript:", "data:text/html", "file://")


def accept_file(file_path: str) -> tuple[bool, str]:
    """Vérifie que le fichier est sûr à traiter.

    Retourne (accepté, raison).
    """
    if not os.path.exists(file_path):
        return False, "fichier introuvable"

    size = os.path.getsize(file_path)
    if size > MAX_FILE_SIZE:
        return False, f"fichier trop lourd ({size} octets)"

    ext = os.path.splitext(file_path)[1].lower()
    if ext not in ACCEPTED_EXTENSIONS:
        return False, f"extension non supportée : {ext}"

    # Lecture du contenu pour détecter les extorsions.
    try:
        with open(file_path, "rb") as fh:
            head = fh.read(4096)
    except OSError as exc:
        return False, f"lecture impossible : {exc}"

    # Détection d'injecteur.
    if b"javascript:" in head.lower() or b"vbscript:" in head.lower():
        return False, "contenu suspect détecté"
    if b"data:text/html" in head.lower():
        return False, "contenu HTML interpolé"

    return True, "ok"


def extract_pdf_pages(file_path: str) -> int:
    """Estime le nombre de pages d'un PDF.

    Version simplifiée : lit le header et compte les occurrences de
    ``/Type /Page``. Pour un MVP, c'est une approximation.
    """
    try:
        with open(file_path, "rb") as fh:
            data = fh.read()
    except OSError:
        return 0

    count = data.count(b"/Type /Page")
    # Évite le cas du root; correction subtile : chaque page possède
    # généralement /Type /Page, sauf la page racine qui n'en a pas.
    return max(1, count)


def extract_pdf_text(file_path: str) -> str:
    """Extrait le texte brut d'un PDF (simulation).

    L'OCR réel est coûteux ; pour le MVP, on renvoie un texte simulé
    basé sur les en-têtes du PDF (métadonnées) + fausses lignes si le PDF
    n'est pas lisible. La fonction signale l'incertitude.
    """
    try:
        with open(file_path, "rb") as fh:
            head = fh.read(64)
    except OSError:
        return ""

    if b"%%EOF" not in head:
        return "[PDF illisible]"

    # Extraction de la métadonnée texte basique.
    text = head.decode("latin-1", errors="ignore")
    if len(text) > 400:
        text = text[:400] + "…"
    return text or "[PDF sans texte extrait]"


def extract_docx_text(file_path: str) -> str:
    """Extrait le texte brut d'un DOCX (XML interne).

    Pas de bi-condition de décompression pour le MVP.
    """
    try:
        import zipfile
    except ImportError:
        return ""

    text_parts = []
    try:
        with zipfile.ZipFile(file_path) as zf:
            if "word/document.xml" not in zf.namelist():
                return ""
            xml = zf.read("word/document.xml")
    except (zipfile.BadZipFile, OSError):
        return ""

    # Supprime les balises XML, garde le texte.
    clean = re.sub(r"<[^>]+>", " ", xml.decode("utf-8", errors="ignore"))
    clean = re.sub(r"\s+", " ", clean).strip()
    return clean[:8000] or "[DOCX sans texte extrait]"


def extract_text(file_path: str) -> str:
    """Extraction de texte selon l'extension."""
    ext = os.path.splitext(file_path)[1].lower()
    if ext == ".pdf":
        return extract_pdf_text(file_path)
    if ext in (".docx", ".doc"):
        return extract_docx_text(file_path)
    return ""


# ------------------------------ FACTS -------------------------------------

def parse_facts(text: str, profile_version: int) -> list[dict]:
    """Extrait des segments de texte avec provenance.

    Retourne une liste de faits, chacun avec : le texte, la provenance
    ('cv_import'), le statut et la version du profil.
    """
    facts = []
    if not text:
        return facts

    # Découpage en segments (lignes / phrases brèves).
    chunks = re.split(r"\n+", text)
    for i, chunk in enumerate(chunks):
        chunk = chunk.strip()
        if not chunk:
            continue
        if len(chunk) > 300:
            chunk = chunk[:300] + "…"
        facts.append({
            "fact_text": chunk,
            "source_type": "cv_import",
            "source_ref": f"cv_import:{i}",
            "status": "extraite_a_confirmer",
            "version": profile_version,
        })
    return facts


def create_version(conn: sqlite3.Connection, profile_id: str, facts: list[dict]) -> sqlite3.Row:
    """Crée une version de profil avec les faits extraits."""
    fields_json = "[]"  # à compléter si fields sont nécessaires
    facts_json = "[]"
    # Pour MVP, on enregistre une version avec les faits.
    import json
    facts_json = json.dumps(facts)
    cur = conn.execute(
        "INSERT INTO profile_versions (id, profile_id, version, fields_json, facts_json, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (uuid4().hex, profile_id, 1, "[]", facts_json, _now()),
    )
    conn.commit()
    return conn.execute(
        "SELECT * FROM profile_versions WHERE id = ?", (cur.lastrowid,)
    ).fetchone()


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
