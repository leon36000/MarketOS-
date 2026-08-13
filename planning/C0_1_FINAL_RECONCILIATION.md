# C0.1 — Réconciliation finale mémoire et exigences

## Verdict

C0.1 est réconciliée pour ce dépôt. Claude Code/Codex peuvent commencer **C1** uniquement après réussite du validateur et des tests du dépôt.

## Réconciliation

- Canon autoritatif externe : v0.23.0, inchangé; son empreinte est conservée dans `canon/CANON_POINTER.json`.
- Directives Holo/Social v0.24.1 et Vendor Compute v0.24.2 sont présentes comme amendements à fusionner explicitement.
- Crosswalk réconcilié : **108 exigences**.
- Contrats Claude Code formels dans le dépôt : **10** — neuf hérités du handoff plus le contrat C1.
- Phases de clôture restantes : C1 à C16.

## Interdictions

- Ne pas promouvoir un candidat comme canon sans delta validé.
- Ne pas créer une nouvelle phase sans preuve d'une lacune indépendante.
- Ne pas charger tout l'historique dans un contexte de modèle.
- Ne pas activer le trading réel ni déclarer la rentabilité prouvée.

## Démarrage

```bash
python tools/validate_repository.py --root . --json
python -m unittest discover -s tests -v
```

Après réussite, créer un worktree C1 et exécuter `planning/phases/C1/EXECUTION_CONTRACT.md`.
