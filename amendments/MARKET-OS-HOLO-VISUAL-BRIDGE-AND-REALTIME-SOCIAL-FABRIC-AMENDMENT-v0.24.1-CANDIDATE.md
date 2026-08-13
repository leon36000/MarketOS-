---
artifact_id: ART-MARKETOS-HOLO-SOCIAL-001
version: "0.24.1-CANDIDATE"
status: DIRECT_OWNER_REQUIREMENT_PENDING_CANON_MERGE
authority: DIRECT_USER_REQUIREMENT
live_trading_state: HARD_LOCKED
profitability: UNPROVEN
---

# MARKET-OS — Holo Visual Platform Bridge et Real-Time Social Intelligence Fabric

## 1. Exigences directes verrouillées

1. MARKET-OS doit pouvoir utiliser un modèle de computer-use tel que Holo3.1 comme **yeux et mains** pour interagir avec des plateformes Web ou desktop dépourvues d'API exploitable.
2. MARKET-OS doit être branché en temps réel aux réseaux sociaux et sources d'événements pertinents afin de détecter rapidement des nouvelles potentiellement importantes pour les marchés.
3. Ces deux capacités doivent augmenter la polyvalence et la vitesse de réaction sans diminuer la sûreté, la traçabilité, la précision point-in-time ou l'autorité du Risk Kernel.
4. Aucun événement social isolé ni aucune action visuelle d'un modèle ne peut contourner les contrôles déterministes, la réconciliation ou les gates de promotion.
5. Le plan final Claude Code doit contenir les fichiers, interfaces, tests, commandes, environnements et gates nécessaires à leur construction.

## 2. Visual Platform Bridge

### 2.1 Hiérarchie d'intégration obligatoire

```text
API officielle / FIX / WebSocket
→ SDK officiel
→ MCP ou outil typé
→ export/import signé
→ DOM + accessibility tree + Playwright/CDP
→ Holo3.1 ou autre modèle visuel
```

Le computer-use est un fallback contrôlé, jamais le premier choix lorsqu'une interface structurée et vérifiable existe.

### 2.2 Rôle de Holo

Holo observe l'écran, propose ou exécute une action bornée et retourne une preuve visuelle. Il ne décide pas seul d'une transaction, d'un risque ou d'une promotion.

```text
Observe
→ ActionIntent typé
→ Policy Check
→ Risk/Permission Gate
→ Pre-Action Verification
→ Action
→ Post-Action Verification
→ Reconciliation
```

### 2.3 Isolation

- VM ou navigateur jetable par plateforme;
- profil et stockage séparés;
- réseau allowlist;
- aucune clé broker visible au modèle;
- injection de secrets hors image et hors presse-papiers;
- session vidéo, screenshots, DOM/AX tree et hashes;
- téléchargement vers zone de quarantaine;
- MFA et challenges soumis à une gate explicite;
- aucune extension non verrouillée;
- aucune route directe vers le Risk Kernel.

### 2.4 Niveaux de permission

```text
V0 OBSERVE_ONLY
V1 NAVIGATE_AND_READ
V2 EXPORT_AND_DOWNLOAD
V3 PAPER_ACTIONS
V4 SENSITIVE_NON_TRADING_WRITE
V5 LIVE_GUI_EXECUTION_CANARY
```

`V5` est une voie dégradée de dernier recours, séparée de l'exécution API, non adaptée au trading ultra-faible latence et bloquée tant que sa fidélité n'est pas mesurée.

### 2.5 Double vérification

Avant et après chaque action sensible :

- screenshot hashé;
- URL, fenêtre et compte attendus;
- élément ciblé avec DOM/AX ou bounding box;
- action et postcondition attendue;
- vérificateur distinct du modèle acteur;
- abort si confiance insuffisante ou état inattendu;
- réconciliation avec la plateforme après action.

## 3. Real-Time Social Intelligence Fabric

### 3.1 Sources

Adapters distincts pour :

- X Filtered Stream / Powerstream selon accès;
- Bluesky Firehose / Jetstream;
- Discord Gateway dans les serveurs autorisés;
- Telegram bot/API dans les canaux autorisés;
- Reddit Data API selon droits et limites;
- Stocktwits lorsque l'accès développeur est disponible;
- RSS/Atom;
- comptes officiels d'entreprises, gouvernements, banques centrales, places et régulateurs;
- fils professionnels et fournisseurs de nouvelles sous licence.

### 3.2 SocialEvent canonique

```yaml
event_id:
source_id:
source_event_id:
source_sequence:
source_published_at:
first_byte_at:
received_at:
persisted_at:
available_to_strategy_at:
raw_payload_sha256:
author_identity:
author_credibility_version:
language:
entities:
claims:
novelty:
velocity:
reach:
bot_manipulation_risk:
corroboration_state:
source_tier:
rights_policy_id:
retention_policy_id:
```

### 3.3 Pipeline

```text
Raw Stream
→ Timestamp + Hash + Sequence
→ Deduplication
→ Language/Media Extraction
→ Entity Resolution
→ Claim Extraction
→ Bot/Spam/Manipulation Detection
→ Source Credibility
→ Cross-Source Corroboration
→ Exposure Graph
→ Impact Distribution
→ Time Decay
→ Risk-Aware Action Proposal
```

### 3.4 Deux chemins de réaction

**Fast Path**

- petit modèle local;
- entités, classification, nouveauté, urgence;
- règles déterministes;
- actions sûres : alerte, pause, réduction du risque, collecte accélérée;
- aucun nouveau risque important sur une rumeur isolée.

**Deep Path**

- RAG point-in-time;
- modèles premium spécialisés;
- analyse causale et cross-asset;
- contradicteur;
- distribution d'impact et horizon;
- Portfolio/Risk Kernel;
- shadow ou paper avant toute promotion.

### 3.5 Hiérarchie de confiance

```text
Tier 0 : source primaire officielle
Tier 1 : fil professionnel / média fiable
Tier 2 : journaliste ou expert vérifié
Tier 3 : communauté sociale corroborée
Tier 4 : rumeur ou compte inconnu
```

Un événement Tier 3/4 peut accélérer une enquête, jamais devenir seul une vérité financière.

### 3.6 Scores et apprentissage

- Brier score et calibration par type d'événement;
- précision historique par auteur et domaine;
- latence de confirmation;
- taux de corrections et suppressions;
- valeur marginale après coûts;
- demi-vie du signal;
- performance par régime;
- conservation des faux positifs et faux négatifs;
- interdiction d'apprendre directement d'un PnL isolé.

## 4. Interface premium

### 4.1 Configuration Visual Bridge

- `+ Ajouter une plateforme`;
- type API/DOM/Holo;
- URL;
- profil navigateur;
- secret reference;
- actions permises;
- compte paper/live;
- politique MFA;
- rétention vidéo;
- test sandbox;
- bouton désactiver/supprimer avec analyse des dépendances.

### 4.2 Configuration Social Fabric

- `+ Ajouter une source`;
- catalogue des endpoints;
- clés et secret references;
- règles, entités, mots-clés, langues et zones;
- priorités;
- budget et quotas;
- backfill;
- durée de conservation;
- droits d'usage et d'entraînement;
- santé, latence, gaps et statut de replay.

### 4.3 Écrans

- Social Pulse;
- Event Timeline;
- Rumor vs Corroborated;
- Source Credibility;
- Entity/Exposure Graph;
- Impact Distribution;
- Latency & Gap Monitor;
- Holo Session Replay;
- Action Audit;
- Kill Switch.

## 5. Tests obligatoires Claude Code

### Visual Bridge

- mauvais onglet;
- fenêtre déplacée;
- popup inattendue;
- session expirée;
- captcha/MFA;
- changement DOM;
- cible visuelle ambiguë;
- clic sur mauvais instrument;
- montant ou quantité divergente;
- téléchargement malveillant;
- postcondition non atteinte;
- double soumission;
- reprise après crash.

### Social Fabric

- déconnexion et reprise avec curseur;
- événements hors séquence;
- duplication multi-source;
- suppression/correction;
- timestamp futur;
- botnet coordonné;
- faux compte officiel;
- média manipulé;
- rumeur non corroborée;
- source primaire contradictoire;
- burst massif;
- panne d'un fournisseur;
- droits expirés;
- rétention et suppression obligatoires;
- look-ahead dans le replay.

## 6. Gates

```yaml
visual_bridge_read_only: DESIGN_REQUIRED
visual_bridge_paper: TEST_REQUIRED
visual_bridge_live: HARD_BLOCKED_SEPARATE_CANARY
social_fast_path: DESIGN_REQUIRED
social_deep_path: DESIGN_REQUIRED
single_post_direct_trade: FORBIDDEN
source_terms_and_rights: REQUIRED
point_in_time_replay: REQUIRED
execution_reconciliation: REQUIRED
```

## 7. Placement dans la feuille de route

- Phase 06B / C4 : Trading Tool Gateway et Visual Platform Bridge.
- Phase 16, 18 / C9 : Real-Time Social Intelligence Fabric.
- Phase 22 / C10 : replay événementiel, coûts et fidélité.
- Phase 25 / C12 : agents spécialisés et conseil premium.
- Phase 26 / C12 : mémoire des événements, crédibilité et corrections.
- Phase 30 / C13 : exécution et réconciliation.
- Phase 32 / C14 : cockpit premium.
- Phase 36 / C15 : red team, manipulation sociale et GUI adversarial.
- C16 : intégration au pack final Claude Code.
