# Assistant emploi MVP

Assistant IA de recherche d'emploi et de candidature — MVP construit à partir du
**PRD v2.0** (25 octobre 2026), préparé pour Jaheim Kouaho.

## Pile technique

- **Python 3.14**, stdlib uniquement. Aucune dépendance externe installable
  (pas de `pip`, pas de `flask`/`fastapi`/`requests` sur la machine cible).
- **SQLite** via le module stdlib `sqlite3`.
- Piles suivantes pour le MVP : fichier `data/assistant-emploi.db` (environnement
  `dev`), environnement `test` séparé, environnements `dev`/`prod` via
  `APP_ENV`.
- Architecture modulaire : `assistantemploi/config` (hidden config), `db` (base
  et migrations), `services/` (par étape de ticket), `scripts/` (outils CLI).
- Un seul processus ne peut exister pour un environnement donné ; les ports sont
  configurables et découplés des latences réseau du MVP.

## Démarrage

```bash
# 1. Construit .env depuis .env.example (génère une clé secrète si absente)
# 2. Initialise la base de données et applique les migrations
python scripts/init_db.py
```

`Vérification` : la commande affiche le nombre de migrations appliquées et le
chemin de la base. Aucun débit de paiement, de compte ni de tâche n'est lancé.

## Structure du projet

```
assistant-emploi-mvp/
├── .env.example            # Variables à personnaliser (jamais à commiter)
├── .gitignore
├── README.md
├── assistantemploi/         # Package de la couche fondations
│   ├── config.py            # C Cache-des-secrets, chargement .env, validation
│   ├── db.py                # Connexion SQLite, exécution des migrations
│   └── migrations.py        # Liste ordonnée des migrations (versionnée)
└── scripts/
    └── init_db.py           # Outil CLI : init + migration + vérification
```

## Backlog vertical (tickets d'acceptation)

| Ticket | Livrable | Dépendance |
|--------|----------|------------|
| T01    | Fondations : projet, dev/test, secrets, migrations | — |
| T02    | Compte vérifié, propriétaire sur chaque ressource, tests croisés | T01 |
| T03    | Wallet, lots, journal des crédits, bonus unique de 15 | T02 |
| T04    | Catalogue des actions, devis versionnés, idempotence | T03 |
| T05    | Chat responsive, sidebar, reprise des tâches | T02 + T04 |
| T06    | Profil manuel, versions, import sécurisé, extraction | T04 + T05 |
| T07    | Registre et premier connecteur réel autorisé | T01 + accès source |
| T08    | Recherche, normalisation, dédoublonnage, explications | T06 + T07 |
| T09    | Génération CV, contrôles, éditeur, deux exports privés | T06 + T08 |
| T10    | Packs, commande, notifications de paiement sandbox | T03 + prestataire |
| T11    | Vocal, support, administration, réconciliation | T05 + T10 |
| T12    | Recette AC01–AC28, coûts mesurés, pilote 50–100 personnes | T01–T11 |

**État des tickets (courant)**
- **T01 – fait** : fondations, environnements, gestion des secrets, migrations
  (démo `python scripts/init_db.py`).
- **T02 – fait** : compte vérifié, frontières de propriété, tests croisés
  (démo `python scripts/accounts.py test-isolation` → `PASS`).
- **T03 – fait** : portefeuille, lots, journal immutables, réservations atomiques
  et idempotentes, bonus de bienvenue unique de 15 (démo test-isolation → PASS,
  11 tests du wallet rouges/verts).
- **T04 – fait** : profil canonique par utilisateur, faits provenance-traçables
  (source + statut), versions immuables et historisées (démo CLI profile.py →
  PASS, 9 tests rouges/verts).
- **T05–T12** – non commencés ; reprendre par l'ordre des dépendances.

Chaque ticket se termine sur une définition de terminé (écran utilisable sur
téléphone et ordinateur, états vide/chargement/erreur/succès, contrôles côté
serveur, tarif cohérent, événement d'audit, tests pertinents, absence de
secrets exposés).
