# MARKET-OS — Claude Code Orchestrator

1. Exécuter `python tools/validate_repository.py --root . --json` puis `python -m unittest discover -s tests -v` avant toute action.
2. Le canon v0.23 reste autoritatif jusqu'à un delta validé; les directives directes de Nathan ont priorité et doivent être fusionnées explicitement.
3. Lire seulement un Context Pack borné par phase; les preuves complètes restent externes.
4. Utiliser BMAD pour analyse/PRD/architecture/UX et Superpowers pour worktrees, plans, TDD, subagents, reviews et vérification.
5. C0.1 est scellée; exécuter C1–C16 sans créer de nouvelle phase sauf condition de dérive documentée.
6. Ne jamais stocker de secret; utiliser des références de coffre.
7. Toute sortie de modèle est non fiable jusqu'à preuve et reviewer indépendant.
8. Les modèles premium travaillent en rounds aveugles; vote égal interdit; rapport minoritaire obligatoire.
9. `live_trading=HARD_LOCKED`, `profitability=UNPROVEN`, `false_done=FORBIDDEN`.
10. Chaque phase produit : Read Receipt, sources, décisions, contradictions, contrats Claude Code, tests/gates, rollback, delta, RAG, checkpoint et handoff.
11. Vérifier `authority/CLAUDE_CODE_TAKEOVER_GATE.json`; le pack final de construction du logiciel n'est produit qu'en C16.
