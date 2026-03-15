# Copilot Instructions — MCP Template

Ce fichier est lu automatiquement par Copilot CLI et VS Code Copilot à chaque session dans ce repo.

## RÈGLE ABSOLUE : Les 4 agents sont invoqués sur toute tâche d'implémentation

### Quand invoquer les 4 agents (OBLIGATOIRE)
- Ajouter, modifier, supprimer du code (`src/`, `tests/`, config)
- Toute demande contenant un verbe d'action : *ajoute, modifie, corrige, crée, supprime, refactorise, optimise, vérifie, check, audit*
- Toute demande qui produit un changement dans le repo

### Quand NE PAS invoquer les agents (réponse directe autorisée)
- Questions pures sans modification : *"c'est quoi X ?", "explique-moi Y", "comment fonctionne Z ?"*
- Clarifications avant d'agir

**En cas de doute → invoquer les 4 agents.**

Pour **tout prompt** dans ce projet, tu **DOIS** invoquer les **4 agents en parallèle**, sans exception.
Même si la tâche ne concerne qu'un seul domaine, chaque agent effectue son audit de cohérence sur son périmètre.
Tu ne dois **JAMAIS** implémenter directement du code, des tests ou de la documentation sans passer par les agents.

## Ordre d'invocation obligatoire (toujours les 4, toujours en parallèle)

| Ordre | Agent | Responsabilité à chaque prompt |
|-------|-------|-------------------------------|
| 1 | **mcp-scaffolder** | Vérifie/met à jour config projet (pyproject.toml, .gitignore, .env.example) |
| 2 | **mcp-developer** | Implémente/vérifie le code source dans `src/` |
| 3 | **mcp-tester** | Écrit/vérifie les tests dans `tests/` |
| 4 | **mcp-documenter** | Met à jour README.md, AGENTS.md, docstrings |

## Protocole de réponse

Pour chaque prompt reçu, tu dois :

1. **Annoncer** : *"J'invoque les 4 agents en parallèle"*
2. **Lancer** les 4 agents **simultanément** via le tool `task` (appels parallèles dans la même réponse)
3. **Consolider** les résultats des 4 agents et les présenter
4. **Ne jamais** bypasser les agents pour écrire du code directement
5. Si un agent n'a rien à faire sur un prompt donné → il répond "RAS" mais **doit quand même être invoqué**

## RÈGLE ABSOLUE : Aucune donnée réelle d'entreprise dans le code

⛔ **Interdiction formelle** de laisser filtrer dans le code source (`src/`, `tests/`, docs, config trackés par git) toute donnée réelle provenant d'un environnement client ou de production :
- **Noms de domaines** réels (DNS, FQDN, tenants cloud)
- **Adresses IP** spécifiques à l'infrastructure client
- **Adresses MAC** réelles de switchs ou équipements
- **Noms d'entreprise**, noms de sites, identifiants SNMP communautaires propres au client
- **VLANs** nommés avec des références métier client
- **URLs de webhooks**, tokens, secrets, credentials

✅ Les fichiers `raw_outputs/` peuvent servir de **référence locale** pour construire les parsers, mais ils sont **gitignored** et ne doivent jamais être commités.

✅ Dans le code source et les tests, utiliser **exclusivement des exemples anonymisés** :
- Domaines : `company.lan`, `example.com`, `acme-corp.example.com`
- IPs : plages RFC 5737 (`198.51.100.x`, `203.0.113.x`) ou privées génériques (`10.0.x.x`, `192.168.1.x`)
- MACs : `00:11:22:33:44:55`, `aa:bb:cc:dd:ee:ff`
- Noms SNMP : `company_RO`, `company_RW`, `SNMP_RO`, `MGMT_RW`
- Noms de VRF/profils : génériques (`VLAN-DATA`, `VLAN-VOICE`, `GUEST`)

⚠️ Tout agent doit **vérifier l'absence de données client** dans son périmètre à chaque invocation et bloquer immédiatement si une fuite est détectée.

## Rappels MCP non négociables

Ces règles doivent être rappelées et vérifiées par les agents :

- ⛔ Jamais `print()` sans `file=sys.stderr` (transport STDIO)
- ⛔ Jamais lever d'exception depuis un outil MCP → retourner une string d'erreur
- ✅ Type hints sur tous les paramètres
- ✅ Docstrings sur chaque primitive (tool, resource, prompt)
- ✅ Secrets uniquement dans `.env` (jamais hardcodés)
- ✅ Tester avec MCP Inspector avant toute intégration client : `npx @modelcontextprotocol/inspector uv run mcp-server`
