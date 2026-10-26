# Check-list du travail — Agent "emploi" sur Hermes

## Contexte
- Spécification technique : Spécification de l'agent emploi pour Hermes, version 1.1 (2026-10-25).
- Référence produit : PRD Agent emploi v2, modèle à crédits.
- Cible : interface web conversationnelle (mobile prioritaire), français par défaut.
- Stack : Python stdlib (aucune dépendance externe), SQLite. Aucune dépendance d'installation requise.
- Build actuel : T01–T04 du PRD (fondations, compte, portefeuille, profil). La base est propre (0 comptes, 0 profils, 0 faits).

## Où en est-on & ce qui reste
- T01 fondations __Fait__ (migrations 1–4, base secrète)
- T02 compte vérifié / propriété __Fait__
- T03 portefeuille / crédits __Fait__
- T04 profil canonique / faits / versions __Fait__
- T05 vocal / support / admin / réconciliation — **À construire**
- T06 profil & import __Bloqué__ (accès source)
- T07 premier connecteur __Bloqué__ (accès source)
- T08 recherche __À venir__
- T09 génération CV / contrôles — __À venir__
- T10 paiement GeniusPay sandbox __À venir__
- T11 vocal / support / admin / réconciliation (travail)
- T12 recette AC01–AC28 __À venir__

## Constitution de mes observations
Pour faire valider mon travail, je dois produire chaque livrable suivant et le démontrer.

### T05 Vocal, support, administration, réconciliation (objectif de ce ticket, à construire)
- Vocal : service de transcription, 60s max, suppression audio après transcription validée, fallback saisie si micro absent.
- Support : tickets de support avec référence, accès restreint au contenu, réponses humaines.
- Administration : panneau admin : santé sources, coûts, files en attente, erreurs, paiements en attente, réservations anciennes.
- Réconciliation : détecter double-débit, reconstitution manquante, réservations anciennes, tâches sans driver. Lancer règles, pas de suppression silencieuse.

### T06 Profil et import
- Interface de saisie manuelle du profil (T06).
- Extraction sécurisée d'un CV (PDF / DOCX) et faits extraits.
- Validation de l'extraction, provenance des faits, statuts.

### T07 Premier connecteur réel
- Créer un connecteur d'offres autorisé (source API ou flux).
- Enregistrer les droits de collecte, attribution, quotas.
- Lancer une recherche qui renvoie des résultats real.

### T08 Recherche
- Recherche multi-source, normalisation, dédoublonnage, explications.
- Résultats sauvegardés AVANT consommation des crédits.
- Résultats vides / partiels traités correctement.

### T09 Génération CV
- Matrice exigences ↔ faits du profil, rédaction, contrôle de fidélité.
- Rendu PDF et DOCX privés.
- Zéro affirmation inventée, deux fichiers lisibles.

### T10 Paiement GeniusPay
- Commandes, packs, sandbox, notifications, rapprochement, support.
- Pas de paiement réel sans vérification bout-en-bout.

### T11 Vocal, support, administration, réconciliation
- Même rubrique que T05, mais pour la version complète de l'agent.

### T12 Recette AC01–AC28
- Exécuter les tests d'acceptation avec des données fictives + annonces autorisées.
- Mesurer coûts, latence, disponibilité.

## Règle d'or de ce ticket T05
Un ticket n'est terminé que si l'écran est utilisable sur téléphone et ordinateur, états vide/chargement/erreur/succès, contrôles côté serveur, tarifs cohérents, événement d'audit, tests pertinents, absence de secrets exposés, et documentation du contrat. Aucun ticket n'est terminé uniquement parce que l'interface est visible.

## Ce qui aide à valider T05
- Vocal : transcription \u2264 60s, suppression audio après transcription.
- Support : références de tâches, crédits, commandes, signalements.
- Admin : flux source, coûts, files, erreurs, paiements en attente, réservations anciennes.
- Réconciliation : détecter doublons, manquements, libérations, tâches sans driver.
