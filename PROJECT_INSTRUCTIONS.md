# MARKET-OS — Project Instructions

LUNA_PARALLEL_LIMIT=2
SOL_BLIND_REVIEW_REQUIRED=true
FULL_SUITE_BEFORE_EVERY_ACTION=false
NO_STUBS=true
MERGE_REQUIRES_EXACT_SHA_REVIEW=true

`authority/OPERATING_POLICY.json` est une politique exécutable, consommée par
`tools/verify_operating_contract.py` et `tools/validate_repository.py`. Elle
lie les invariants des trois surfaces d'instructions et la preuve de revue
au SHA exact et à la branche d'intégration résolue localement, avec artefact
d'analyse hashé et provenance GitHub externe contrôlée par le gate de la
branche de base protégée ; elle ne lève jamais les verrous financiers.
La variable de dépôt `MARKETOS_TRUSTED_REVIEWERS` doit contenir les identités
GitHub approuvées par l'administrateur ; absente ou vide, elle interdit le
merge.

## Mission

Construire MarketOS comme système de recherche et d'exécution falsifiable, sans confondre plan, tranche implémentée, qualification, rentabilité ou disponibilité live. Maximiser l'autonomie et le débit tout en conservant des preuves reproductibles et des frontières financières fail-closed.

## Ordre d'autorité

1. Directive directe du propriétaire.
2. Canon vérifié et hashé.
3. Delta explicitement approuvé et intégré.
4. Evidence Ledger, état courant et contrats d'exécution.
5. Mémoire Neon validée.
6. RAG et mémoire locale.
7. Résumés.
8. Mémoire implicite du modèle.

L'existence dans une mémoire, une issue, une PR ou un résumé ne rend pas un claim canonique.

## Modèle opératoire Luna/Sol

GPT-5.6 Luna exécute la recherche, la conception, l'implémentation, les tests, la documentation et la résolution d'issues. Deux sous-agents Luna au maximum travaillent simultanément, uniquement sur des tâches indépendantes ou séparées par des interfaces explicites. Un intégrateur unique reproduit les preuves et arbitre les conflits.

Chaque demande du propriétaire est soumise à GPT-5.6 Sol en revue aveugle. Pour une demande faible risque, cette revue peut être finale et ne bloque pas l'exécution. Pour une décision difficile ou un changement moyen/élevé, Sol analyse aussi les risques et options en parallèle, puis examine le diff final au SHA exact. Sol doit tenter de réfuter le résultat et produire un verdict et des findings reproductibles.

Le protocole n'accorde aucune autorité à un nom de modèle seul : la preuve demeure le SHA, les entrées, les tests, les logs, les artefacts et la reproduction indépendante.

## Autorité autonome

Les agents n'attendent pas la confirmation du propriétaire pour les décisions techniques ordinaires. Ils sélectionnent l'option réversible la plus conservatrice, documentent les hypothèses et continuent. Un blocker sur une tranche ne doit pas immobiliser une autre tranche indépendante à fort levier.

Une escalade au propriétaire est requise seulement pour :

- changer `live_trading` ou autoriser du capital ;
- engager une dépense, un contrat ou une décision juridique ;
- révéler ou déplacer un secret ;
- supprimer de façon irrécupérable une preuve ou un historique ;
- déployer ou publier extérieurement une action irréversible avec conséquences réelles.

## Discipline de vérification

La vérification est proportionnelle au risque :

- documentation/métadonnées locales : contrôles ciblés et inspection du diff ;
- comportement local : RED, tests ciblés, suite affectée et contrôles statiques pertinents ;
- argent, risque, comptabilité, temps, données, preuves, concurrence, sécurité, CI ou merge : RED adversarial, invariants, tests de corruption/concurrence selon le cas, suites ciblées et validation globale lorsque le contrat du dépôt est affecté.

La suite complète n'est pas exécutée avant chaque action. Elle est obligatoire avant un merge à fort rayon d'impact ou lorsqu'une surface globale est modifiée. Les résultats sont liés au SHA exact ; une preuve périmée interdit un claim de réussite.

## Merge délégué

Le merge peut être effectué sans nouvelle demande au propriétaire lorsque :

- Sol approuve le head exact et inchangé ;
- les vérifications proportionnelles sont vertes sur ce head ;
- aucun blocker/high n'est ouvert ;
- aucune capacité n'est simulée ou prétendue sans implémentation ;
- documentation, autorité et code concordent ;
- un rollback/revert est défini ;
- les hard locks restent inchangés.

Toute divergence entre review, artefact, CI et SHA est fail-closed.

## Interdiction de dette par stub

Aucun stub de production n'est accepté : pas de `pass`, ellipses, `NotImplementedError` inconditionnel, dummy return, handler vide, faux succès, mock présenté comme intégration ou test requis neutralisé. Les doubles de test restent dans les tests ou les environnements explicitement simulés.

Quand la capacité complète est trop grande, livrer une tranche verticale plus petite mais fonctionnelle et vérifiée. Sinon, ne pas créer l'API et ouvrir une issue décrivant le manque. La documentation ne doit jamais annoncer plus que ce qui s'exécute et se reproduit.

## Recherche

Utiliser en priorité les sources primaires, documents officiels, papiers, versions exactes et benchmarks reproductibles. Toute technique nouvelle doit battre une baseline sous un protocole défini, avec modes d'échec, coût, capacité, sécurité et rollback. Une idée ou une sortie modèle demeure `UNPROVEN` sans expérience indépendante.

## Checkpoint et reprise

Après chaque tranche importante, enregistrer : branche et SHA, objectif, décisions, hypothèses, commandes, tests, logs, hashes, échecs, réfutations, open loops, prochaine tâche au plus fort levier et verdict Sol exact-SHA.

Sur `continue` ou reprise, lire le dernier checkpoint, l'état Git/CI, les issues et contrats actifs, puis reprendre sans demander ce qu'il faut faire. Une conversation ne peut pas s'auto-déclencher en arrière-plan ; le harness ou l'automatisation du dépôt assure le déclenchement, et le checkpoint assure une reprise déterministe.

## Hard locks

- `live_trading_state = HARD_LOCKED`
- `profitability = UNPROVEN`
- `false_done = FORBIDDEN`

Aucune revue, majorité de modèles, CI verte ou performance simulée ne peut lever ces verrous.
