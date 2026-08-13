# MARKET-OS — Politique des outils de qualité

- Les tests et validateurs du dépôt constituent la gate minimale locale.
- SonarQube est un candidat de qualité/sécurité centralisée lorsque le projet, le serveur et les
  permissions sont configurés. L’absence de connexion Sonar ne peut être présentée comme un scan.
- Fallow est réservé aux graphes TypeScript/JavaScript lorsque le cockpit contient un codebase
  significatif. Il n’apporte pas de preuve sur les documents C1 ni sur le validateur Python actuel.
- Temporal sera évalué en C4/C12 pour les workflows durables, pas comme outil de validation C1.
- Les AMD/NVIDIA/Intel skills sont réservées aux phases C5/C6 et ne qualifient aucun matériel sans
  inventaire et benchmark des nœuds réels.
- Toute intégration de qualité doit produire une sortie machine-readable, être épinglée par version
  et ne pas envoyer du code ou des données sensibles à un service externe sans autorisation.
