# CLAUDE.md — Movix

Ce fichier contient les règles propres à Claude pour ce dépôt. Les préférences générales viennent du `CLAUDE.md` global ; les outils et modèles Codex de `AGENTS.md` ne s’appliquent pas à Claude.

## Lire selon la tâche

Commencer par l’index du [README principal](README.md), puis les sections pertinentes du module. Ne pas relire intégralement les grands README à chaque tour. Les manifestes et le code actuel priment sur les anciennes descriptions.

- [Frontend](src/README.md) : routage, état, services, conventions et vérification.
- [Main API](API/Mainapi/README.md) : cluster, auth, profils, sync et sources.
- [WatchParty](API/watchpartyAPI/README.md) et [Rust/WASM](wasm/watchparty-sync/README.md) : synchronisation.
- [Proxy Python](API/proxiesembed/README.md) : extraction et DRM.
- [Extension](extension/README.md), [userscript](userscript/README.md) et [app mobile](app/README.md) : intégrations navigateur et WebView.
- [Appli TV native](app-tv/README.md) : Kotlin, Compose for TV, Media3, extraction QuickJS et publication de l’APK.

## Contraintes du dépôt

- Travailler directement sur `main`, sans nouvelle branche ni worktree sauf demande explicite contraire.
- Ne pas ouvrir de panneau navigateur ni lancer de serveur de développement sans demande explicite.
- Les autres copies du dépôt évoluent séparément ; ne pas y récupérer automatiquement du travail.
- Conserver les crédits et respecter [LICENSE](LICENSE). Ne pas committer de secrets ou de `.env`.
- Frontend : React/TypeScript et Vite, ESM à la racine. Main API : **CommonJS**, comme l’indique `API/Mainapi/package.json` ; conserver `require` et `module.exports`.
- Préserver les conventions React Context, Tailwind, Radix/shadcn, alias `@/`, services API et traductions FR/EN. Les versions sont celles des manifestes.
- Préserver requêtes SQL paramétrées, contrôles d’accès, limitations et cycle de vie du cluster. Auth et profils traversent le frontend, `localStorage` et `/api/sync`.
- Comparer Chrome MV3 et Firefox MV2 pour les changements partagés. Le userscript est aussi embarqué dans l’app : vérifier le bridge et régénérer avec `node app/scripts/build-userscript.js` si nécessaire.
- Une modification de Sync Pro concerne serveur, hook, worker et Rust ; régénérer `public/wasm/watchparty-sync/` et conserver le repli JavaScript.
- Le service worker est le fichier personnalisé `public/sw.js`, enregistré par `src/main.tsx`. Vérifier son code et `src/services/blockDetection.ts` pour les miroirs ; ne pas supposer un TTL ou un domaine historique.
- Plusieurs hébergements sont possibles (`build:cf`, `build:coolify`, `server/index.js`) : vérifier la cible du déploiement demandé.

## Vérifier selon le risque

Des tests ciblés existent dans `tests/`, les backends et l’app, même si la racine n’a pas de script `npm test`. Utiliser les commandes documentées du module et distinguer les problèmes préexistants des régressions.

Pour le frontend, choisir lint, tests ou build selon le changement ; le build Vite seul ne remplace pas TypeScript. Pour Main API, privilégier syntaxe et tests ciblés. Une documentation seule nécessite une relecture et un contrôle des liens, pas un build applicatif. Ne pas annoncer de validation visuelle sans l’avoir effectuée.
