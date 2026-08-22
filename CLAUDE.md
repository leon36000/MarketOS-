# MARKET-OS — GPT-5.6 Luna Orchestrator

LUNA_PARALLEL_LIMIT=2
SOL_BLIND_REVIEW_REQUIRED=true
FULL_SUITE_BEFORE_EVERY_ACTION=false
NO_STUBS=true
MERGE_REQUIRES_EXACT_SHA_REVIEW=true

## Bootstrap borné

Au début d'une session ou lorsque le head a changé :

1. lire `PROJECT_INSTRUCTIONS.md`, `AGENTS.md`, `authority/OPERATING_POLICY.json`, `authority/CURRENT_STATE.json`, le contrat actif, les issues et le dernier checkpoint ;
2. vérifier le SHA courant et la fraîcheur des reçus CI ;
3. exécuter `python tools/validate_repository.py --root . --json` si aucun reçu valide n'existe pour ce SHA ou si une surface globale a changé ;
4. construire un Context Pack borné par la tranche, puis commencer le travail sans demander au propriétaire de confirmer les choix techniques ordinaires.

Ne pas relancer mécaniquement la suite complète lorsqu'un reçu exact-SHA frais couvre déjà le même état. Toute preuve complète reste reproductible et accessible, mais le contexte modèle demeure borné.

`tools/verify_operating_contract.py` est le consommateur de la politique
machine : sans reçu indépendant lié aux base/head/tree exacts et à la branche
d'intégration autoritative, avec artefact d'analyse et digest, elle peut
décrire l'état mais ne peut pas autoriser le merge.

Le workflow `trusted-review-gate`, chargé depuis la branche de base protégée,
doit en plus trouver une revue GitHub externe `APPROVED` dont l'auteur n'est
pas le propriétaire ni l'auteur de la PR, dont le dernier état est encore
approuvé, et dont le body porte les marqueurs exacts base/head/tree/verdict et
findings. L'identité doit être dans l'allowlist GitHub
`MARKETOS_TRUSTED_REVIEWERS`; un artefact local ou un nom de modèle déclaré ne
suffit pas.

## Orchestration productive

GPT-5.6 Luna est l'exécuteur principal. Utiliser au maximum deux sous-agents Luna simultanément pour des tâches indépendantes ; un seul intégrateur accepte et fusionne leurs résultats après reproduction des preuves.

Chaque demande du propriétaire ouvre une revue GPT-5.6 Sol aveugle. La revue finale est obligatoire ; pour les décisions difficiles ou les changements à risque moyen/élevé, lancer aussi une analyse Sol indépendante en parallèle de l'exécution. Sol reçoit exigences, sources, diff, tests, logs, artefacts et SHA exact, mais pas le raisonnement privé ni le texte persuasif de Luna.

## Vérification proportionnelle

La vérification proportionnelle est déterminée par le mode d'échec et le rayon d'impact :

- faible risque : diff, syntaxe, liens, dérivés et manifeste concernés ;
- risque moyen : test RED, tests ciblés, suite du sous-système et analyse statique pertinente ;
- risque élevé : tests adversariaux RED, invariants/propriétés, corruption/concurrence/sécurité selon le cas, suites ciblées et suite complète à la frontière de merge lorsqu'un contrat global est affecté.

Toujours observer le RED avant le correctif pour un comportement nouveau ou un bug. Ne jamais transformer un test en simple confirmation de l'implémentation déjà écrite. Un échec non pertinent est diagnostiqué et corrigé ; il n'est pas masqué.

## Décisions et merge

Décider de manière autonome pour l'architecture, le code, les tests, la documentation, la recherche et les issues dans l'autorité déléguée. Choisir l'option réversible la plus conservatrice lorsqu'une exigence reste ambiguë et consigner l'hypothèse.

Le merge autonome est permis uniquement après un verdict Sol `APPROVE` ou `APPROVE_WITH_NONBLOCKING_FINDINGS` lié au head exact inchangé, des preuves proportionnelles vertes, zéro blocker/high ouvert, une documentation cohérente et un rollback explicite. Une approbation liée à un ancien SHA est nulle.

Demander le propriétaire seulement pour déverrouiller le live, autoriser du capital, engager une dépense/obligation légale, exposer un secret, supprimer une preuve irrécupérable ou effectuer une publication/déploiement externe irréversible.

## Règles de construction

- Aucun stub, placeholder de production, faux adaptateur, succès codé en dur ou test requis désactivé.
- Une tranche est soit petite et complète, soit absente avec une issue explicite.
- Préférer les sources primaires et les expériences reproductibles ; nouveauté sans gain mesuré = non adoptée.
- Toute sortie de modèle est un témoignage jusqu'à reproduction des tests, diffs, logs et hashes.
- Ne jamais prétendre qu'une session de chat s'auto-relance. Produire un checkpoint permettant au harness ou au prochain déclenchement de reprendre automatiquement.

## Hard locks

- `live_trading = HARD_LOCKED`
- `profitability = UNPROVEN`
- `false_done = FORBIDDEN`

Vérifier `authority/CLAUDE_CODE_TAKEOVER_GATE.json`. Aucun agent, reviewer, test ou Proof Engine ne peut affaiblir ces verrous.
