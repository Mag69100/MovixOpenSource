# Main API Movix

C'est le cœur applicatif du projet. Si le frontend affiche un catalogue, authentifie un user, synchronise du `localStorage`, gère les commentaires, le Wishboard, le Top 10, le Live TV, le debrid ou les pages VIP, il finit très souvent ici.

Le service tourne en mode cluster via `server.js` : un master lance plusieurs workers, surveille les redémarrages et gère un graceful shutdown. `app.js` monte ensuite Express, Redis, le pool MySQL, les caches disque et les routes injectées par dépendances.

## Ce que le service gère

- auth, sessions et profils
- recherche, metadata TMDB et agrégation de sources
- sync frontend <-> backend pour une partie de l'état utilisateur
- commentaires, likes, listes partagées, Wishboard et soumission de liens
- Live TV, proxies, debrid et intégrations de scraping
- VIP, invoices, wrapped et features communautaires

## Démarrage

```bash
cd API/Mainapi
cp .env.example .env
npm install
npm run dev
```

Ne lance pas le service avec un `.env` vide : MySQL, Redis, JWT, TMDB et plusieurs routes métier en dépendent directement.

Notes utiles :

- le serveur HTTP écoute actuellement sur `http://localhost:25565`
- `server.js` bind aujourd'hui le port `25565` en dur
- `NUM_WORKERS` permet de régler le nombre de workers du cluster
- MySQL et Redis sont nécessaires pour une grosse partie des routes

## Architecture

```text
API/Mainapi/
|-- server.js                 # Master cluster + workers + graceful shutdown
|-- app.js                    # Bootstrap Express, middleware, deps partagées
|-- mysqlPool.js              # Pool MySQL unique
|-- config/redis.js           # Redis
|-- middleware/               # CORS, sécurité, auth
|-- routes/                   # Modules avec configure(deps)
|-- commentsRoutes.js         # Commentaires
|-- likesRoutes.js            # Likes / dislikes
|-- sharedListsRoutes.js      # Listes partagées
|-- liveTvRoutes.js           # Live TV
|-- wishboardRoutes.js        # Wishboard
|-- top10Routes.js            # Classements
|-- wrappedRoutes.js          # Wrapped
|-- linkSubmissionsRoutes.js  # Soumission de liens
|-- utils/                    # Cache, proxies, axios helpers, VIP, etc.
|-- cache/                    # Caches disque
`-- exportscripts/            # SQL et scripts de migration
```

Le pattern important dans `routes/` : beaucoup de modules exposent `configure(deps)`. C'est `app.js` qui injecte les clients HTTP, le cache, les helpers et les constantes partagées avant montage.

## Variables d'environnement à renseigner en premier

Le fichier `API/Mainapi/.env.example` est la référence complète. En pratique, les groupes de variables à traiter en premier sont :

- cœur applicatif : `JWT_SECRET`, `TMDB_API_KEY`, `FRONTEND_BASE_URL`
- données : `DB_HOST`, `DB_PORT`, `DB_USER`, `DB_PASSWORD`, `DB_NAME`
- cache et coordination : `REDIS_HOST`, `REDIS_PORT`, `REDIS_PASSWORD`, `NUM_WORKERS`
- scraping / proxy : `PROXY_SERVER_URL`, `IPTV_STREAM_PROXY`, `SOCKS5_PROXIES`, `HTTP_PROXIES`
- anti-abuse / forms : `TURNSTILE_SECRET_KEY`, `TURNSTILE_INVISIBLE_SECRETKEY`, puis `TURNSTILE_DOMAINS_n`, `TURNSTILE_SECRET_KEY_n` et `TURNSTILE_INVISIBLE_SECRETKEY_n` (n de 2 à 10) au-delà de 10 domaines : la clé suit l'`Origin` de la requête (`utils/turnstile.js`)
- paiement / VIP : variables `VIP_*`, `BLOCKCYPHER_TOKEN`

Certaines intégrations sont très spécifiques à des sources données, par exemple les cookies `DARKIWORLD_*`, `FSTREAM_LOGIN_*` ou `XTREAM_*`.

`FSTREAM_BASE_URL` définit l'origine commune aux recherches, à la session et aux pages FrenchStream (`https://french-stream.net` par défaut). Les anciennes URLs `.one` en cache sont normalisées avant les appels, y compris les API d'épisodes : les POST de recherche ne doivent pas suivre une redirection 301 qui perdrait leur formulaire.

FStream partage les liens bruts par saison ; `episode` sélectionne toujours l'épisode à résoudre. Les anciens caches par épisode sont repris progressivement. `FSTREAM_CACHE_REFRESH_MS` vaut 10 minutes par défaut : une requête déclenche l'actualisation lorsque les données sont périmées. Une recherche sans fiche validée attend également ce délai, tandis qu'une panne peut être retentée après une minute. Les liens utilisables sont conservés si l'actualisation échoue.

FStream et Wiflix vérifient les titres français, originaux et alternatifs. Une année différente ou absente nécessite des indices supplémentaires : affiche TMDB identique, ou concordance du titre avec plusieurs acteurs/créateurs ou un synopsis corroboré. Le synopsis seul ne suffit pas. Pour les séries, l'année de la saison et celle de la série sont admises ; la saison demandée reste contrôlée. Les diagnostics indiquent les motifs d'acceptation ou de rejet des candidats.

PurStream conserve les succès pendant six heures et les absences pendant cinq minutes. La date d'une tentative échouée est séparée de celle des données conservées. Un stream en 404 provoque une revalidation de son identifiant fournisseur. La source TV Direct a été retirée : ses anciens appels renvoient 410 sans contacter le fournisseur. `CLONE_LINKS_MISSING_RETRY_MS` espace les tentatives sur un fichier Uqload déclaré absent (24 heures par défaut).

Cpasmal privilégie les proxys dédiés de `SOCKS5_PROXIES`, puis le pool partagé en repli. Ses journaux de refus indiquent le proxy et le chemin ciblés, sans identifiants ni paramètres de requête.

Les proxys Cpasmal refusés sont écartés pendant une minute dans le worker (30 secondes sur erreur réseau). Le diagnostic d'un 403 indique également le nombre de tentatives et leurs statuts HTTP.

Les routes Cpasmal film et épisode servent le cache immédiatement et l'actualisent en arrière-plan si nécessaire. Sans cache utilisable, elles renvoient `202` avec `pending: true`, `code: "retrieval_in_progress"` et `Retry-After: 2` : rappeler la même URL pour obtenir le résultat une fois la récupération terminée. Une panne amont donne ensuite un `503`, sans créer de faux cache « introuvable » ; les nouvelles tentatives sont espacées d'une minute.

Redis partage désormais la récupération Cpasmal entre workers, les recherches positives pendant 40 minutes et les fiches série validées pendant 10 minutes. Les extractions sont limitées à trois lecteurs par épisode et douze requêtes par worker ; au-delà de trois lecteurs, le premier résultat est publié avant la liste complète. Une publication partielle conserve les lecteurs déjà utilisables. Sans Redis, le repli local reste limité à 64 récupérations simultanées ; les caches de recherche locaux sont bornés en nombre d'entrées et en octets.

Les recherches Coflix positives sont partagées pendant 30 minutes et les échecs pendant une minute lorsque Redis est disponible. Chaque worker écarte pendant 30 secondes les proxys refusés ou en panne. Les prérequêtes CORS autorisées annoncent `Access-Control-Max-Age: 600` pour permettre leur réutilisation par le navigateur.

## Fichiers SQLite pour Darkino / DarkiWorld

La source téléchargements (`routes/darkiworld.js` et `utils/darkiworldSqlite.js`) lit des snapshots SQLite locaux : `mirror.sqlite`, `darkino.sqlite` et `links_small.sqlite`. Ces fichiers ne sont pas versionnés dans le dépôt public.

1. Télécharger [l’archive des fichiers SQLite sur Pixeldrain](https://pixeldrain.com/u/n2M1s1MA).
2. Extraire les fichiers `.sqlite` dans `API/Mainapi/darkino-backups/`.
3. Pour utiliser un autre dossier, définir `DARKIWORLD_SQLITE_DIR` avec son chemin absolu, par exemple `/home/container/darkino-backups`.

Démarrer ou redémarrer Main API après l’installation des fichiers. Sans ces snapshots, les liens absents du cache local peuvent renvoyer `sqlite_miss`. Avec `HYDRACKER_BLACKOUT=true` (valeur par défaut), aucune résolution en direct auprès d’Hydracker ou de DarkiWorld ne prend le relais.

## Points d'entrée utiles

- auth et profils : `routes/authRoutes.js`, `routes/sessions.js`, `routes/profiles.js`
- persistance frontend : `routes/sync.js`, historique et progression : `routes/history.js`
- recherche et catalogues : `routes/search.js`, `routes/tmdb.js`
- scraping / lecture : `routes/cpasmal.js`, `routes/fstream.js`, `routes/wiflix.js`, `liveTvRoutes.js`
- communautaire : `commentsRoutes.js`, `likesRoutes.js`, `sharedListsRoutes.js`, `wishboardRoutes.js`, `linkSubmissionsRoutes.js`
- VIP / paiements : `utils/vipDonations.js`, `routes/vipDonations.js` ; réglages des dons gérés depuis l'admin (montant libre, moyens actifs, cartes cadeaux, contacts) : `utils/vipDonationSettings.js`

## Synchro : historique et progression en base

L'historique et la progression sortent du fichier de synchro (limite de 600 clés par profil) vers MySQL. Les clients écrivent toujours `progress_*` et `continueWatching` via `/api/sync` ; le serveur les recopie dans les tables.

Tables (`db/schema/history.js`, créées au démarrage avec les autres) :

- `watch_progress` : une ligne par film ou épisode regardé (position et durée en secondes, `updated_at`). Un film a saison et épisode à 0.
- `watch_history` : une ligne par titre, avec l'épisode pointé, `finished`, `hidden` et `last_watched_at`.
- `watch_history_imports` : profils dont les anciennes données sont déjà importées.
- `watch_marks` : marques « Déjà vu » du site (`watched_movie`, `watched_tv`, `watched_episodes_tv_<id>`), une ligne par marque avec `marked_at`. Saison/épisode 0/0 = titre entier (film vu, série entière vue), sinon un épisode. Une marque ne crée pas de ligne `watch_history` et ne touche pas « Reprendre ».
- `tmdb_media` et `tmdb_episodes` : cache TMDB permanent partagé par tous, une ligne par titre (ou épisode) et par langue (`fr-FR` ou `en-US`, toute autre valeur devient `fr-FR`).

Le propriétaire d'une ligne est toujours `user_type` + `user_id` + `profile_id`.

Règles de la rangée « Reprendre » (`utils/historyRules.js`, `utils/historyStore.js`) :

- un titre y entre dès qu'on le lance, sans durée minimum ni limite de nombre ; le plus récemment ouvert passe en premier ;
- film fini (position ≥ 95 % de la durée) : il sort de la rangée ;
- épisode fini : la carte passe à l'épisode suivant ; après le dernier épisode de la dernière saison, la série sort. Sans infos TMDB sur les saisons, la carte reste sur l'épisode fini ;
- deux appareils en même temps : l'écriture la plus récente (`updated_at`, `last_watched_at`) gagne ;
- un titre retiré (`hidden`) revient seulement sur une lecture strictement plus récente ;
- à date égale, l'ordre est stable (type puis id).

Infos TMDB (`utils/mediaStore.js`, durées `runtimeMinutes` comprises) : un titre absent est demandé une seule fois à TMDB puis gardé. Une ligne de plus de 7 jours est servie telle quelle et rafraîchie en arrière-plan. Un échec TMDB ou SQL donne un titre sans infos (`title: null`), jamais une erreur. Un titre que TMDB ne connaît pas (404 ou réponse sans id) est gardé comme ligne « inconnue » (titre vide, jamais renvoyée) et redemandé après 1 jour ; une panne (délai, 5xx) n'est pas redemandée pendant 10 minutes (mémoire du worker). Même mémoire pour une saison : 404 → 1 jour, panne ou saison vide → 10 minutes. Au plus 300 demandes TMDB par lecture (4 en même temps), les titres les plus récents d'abord : une grosse rangée arrive complète dès la première lecture, le reste éventuel à la lecture suivante.

Les listes SQL de longueur variable (progression des cartes, lecture de `tmdb_media`, insertion d'une saison) passent par `pool.query`, toujours avec des `?` : avec `execute`, chaque longueur créerait une requête préparée (`max_prepared_stmt_count`).

Miroir de `/api/sync` (`routes/sync.js`, `utils/historyImport.js`) : après chaque POST, les ops `set`/`objPatch` sur `progress_*` et `continueWatching` sont recopiées en tâche de fond, sans faire attendre la réponse. Une erreur est seulement loguée `[HISTORY]` : la synchro n'échoue jamais à cause de l'historique. Une entrée retirée de `continueWatching` masque le titre. Un `remove` de `continueWatching`, ou `settings_disable_history` passé à `'true'` (historique désactivé dans les réglages), vide toute la rangée (`hideAll`). Le site ne lit plus la rangée du serveur tant que l'historique est désactivé.

Marques « Déjà vu » : pour `watched_movie`, `watched_tv` et `watched_episodes_tv_*`, toute op compte (le site envoie `arrayAdd` / `arrayRemove` pour les listes, `objPatch` pour les épisodes, `remove` pour vider la clé). Contrairement au reste du miroir, elles sont écrites pendant le POST, **sous le verrou de synchro du profil** et attendues (`applyMarkOps`) : deux envois s'appliquent donc dans l'ordre. Une erreur est seulement loguée `[HISTORY]`, la synchro réussit quand même. La valeur finale est comparée à la précédente : ajouts → `INSERT IGNORE` (une marque déjà là garde sa date), retraits → `DELETE`. L'ancienne clé `watched_tv_episodes` (`[{ id, episodeInfo: { season, episode }, addedAt }]`, encore lue par le site) donne aussi des marques d'épisodes ; une entrée sans `episodeInfo` valide est ignorée. Les marques sont l'union de toutes ces clés : un épisode retiré d'une clé reste marqué s'il l'est encore par une autre. Seuls les épisodes à `true` comptent ; `marked_at` vient de `addedAt` pour un titre, sinon c'est l'heure de l'insertion. Nouvelle valeur illisible : rien ne bouge ; ancienne valeur inconnue ou illisible : ajouts seulement.

Suppression d'un profil (`DELETE /api/profiles/:id`, `DELETE /api/oauth/profiles/:id`) : sa progression, son historique, ses marques « Déjà vu » et sa marque d'import sont effacés au mieux (`deleteProfileHistory`), une erreur est seulement loguée.

Les routes OAuth qui modifient un profil (`withProfileMutation`) lisent les données complètes du fichier, jamais la vue élaguée en mémoire : au-delà de 600 clés, l'écriture est refusée comme avant.

Import silencieux des anciennes données (`ensureImported`) :

- une seule fois par profil, à la première lecture de « Reprendre » ou au premier POST `/api/sync` ;
- un seul import à la fois par profil (verrou MySQL `mainapi:history-import:<sha1>`), au plus 2 en même temps par worker ;
- statuts : `imported`, `already`, `deferred` (pas de place libre, ou échec de moins de 10 minutes), `failed` ;
- les marques « Déjà vu » ne passent pas par l'import. Après un import réussi, `resyncProfileMarks` relit le fichier **sous le verrou de synchro** et aligne `watch_marks` dessus (`replaceMarks` : ajouts manquants, retraits du reste ; ajouts seulement si une clé est illisible). Un retrait fait avant ou pendant l'import n'est donc jamais défait. Ce n'est jamais attendu : une synchro peut attendre l'import en tenant déjà ce verrou. Le recalage se répare tout seul : `GET /history/list` (import fait) l'attend une fois par profil et par worker (`ensureProfileMarks`, mémoire de 10 000 profils). S'il échoue, il est logué, la liste n'est pas gardée et il est retenté à l'appel suivant. Les routes OAuth qui changent `watched_*` (`withProfileMutation`) recopient aussi leurs marques sous le verrou ;
- un titre avec progression mais absent d'un `continueWatching` lisible est importé masqué (sauf un film déjà fini) ;
- un profil dont l'historique est désactivé (`settings_disable_history` à `'true'`) est importé entièrement masqué : les progressions sont gardées.

Élagage (`pruneProgressKeys`) : au-delà de 600 clés, les `progress_*` les plus vieilles sont retirées du fichier jusqu'à 550 clés, au lieu de répondre 413. Cela se fait seulement pendant un POST, après un import réussi (`imported` ou `already`) ; sinon rien n'est élagué et la limite répond 413 comme avant. Un GET élague seulement en mémoire et n'écrit jamais le fichier.

Routes (`routes/history.js`, montées sous `/api`) : comptes `oauth` et `bip39` seulement (401 sinon), profil vérifié via `getOwnedProfile` (404 s'il n'est pas au compte), 120 requêtes par minute et par IP. Les invités gardent leur `localStorage`.

- `GET /history/continue?profileId=&language=` → `{ items, complete }`. Lance d'abord l'import ; `complete` vaut `true` si l'import est fait (`imported` ou `already`), sinon le client garde sa rangée locale. Historique désactivé (`settings_disable_history` à `'true'` dans le profil) : `{ items: [], complete: true }`, sans import ni lecture des tables.
- `GET /history/list?profileId=&language=&status=&page=&pageSize=` → `{ items, page, pageSize, total, counts, stats, complete }` : onglet « Historique » du profil (`listHistory`, règles dans `utils/historyOverview.js`, mêmes seuils que la page profil du site). `status` vaut `in_progress`, `finished` ou `not_started`, sinon 400. `page` ≥ 1 (défaut 1), `pageSize` 1-50 (défaut 20). Import et historique désactivé comme `GET /history/continue` (désactivé : liste vide, chiffres à 0).
  - Titres : lignes `watch_history` (masquées comprises), titres marqués « Déjà vu » et séries avec un épisode marqué. Chaque titre a un seul statut : les trois `counts` font le nombre de titres.
  - Avancement : position exacte (`watch_progress` > 0), sinon estimé avec le temps passé dans un lecteur web (`wrapped_viewing_data`, même filtre que `GET /api/wrapped/progress`, plus les lignes `anime` du lecteur anime, comptées comme la série TMDB de même id ; jamais `live-tv`), rapporté à la durée TMDB (épisode, sinon durée type de la série). L'estimé ne sert jamais quand une position exacte existe. Les numérotations ne sont jamais mêlées : pour les épisodes (vus, estimés, épisode affiché), une série normale n'utilise que ses lignes `tv`, une série en mode anime que ses lignes `anime`. `trackedSeconds` compte toutes les lignes.
  - Film : terminé si marqué, `finished = 1` ou ≥ 95 % ; en cours dès 5 % ; sinon non démarré.
  - Série : un épisode est vu si exact > 85 %, marqué, ou estimé ≥ 85 %. Elle est terminée si marquée, `finished = 1` ou si tous les épisodes connus sont vus ; en cours si un épisode est vu ou à ≥ 5 % ; sinon non démarrée.
  - Chaque ligne = un `ContinueItem` + `finished`, `estimated` (position ou épisode affiché estimé), `markedWatched` (titre marqué). Un film marqué sans aucune progression a `position` et `duration` à null.
  - Pour une série : `episodesWatched` (saison 0 exclue, plafonné à `episodesTotal` ; série marquée en entier = `episodesTotal` quand il est connu) et `episodesTotal` (`seasons_json`, saison 0 exclue, null si inconnu). Épisode affiché : celui de l'historique, sinon le dernier vu. Tri : date de lecture (sinon de la marque la plus récente), puis type, puis id, tout décroissant.
  - `animeMode` (lignes de `GET /history/list` et de `GET /history/continue`) : vrai si la ligne `wrapped_viewing_data` la plus récente de la série (`MAX(created_at)`, même requête) est de type `anime`. Le lecteur anime suit alors la numérotation anime-sama.
    - Pour ces séries : `episodesTotal`, `episodeName`, `episodeOverview` et `stillPath` à null, sans aucune lecture TMDB de saison.
    - `episodesWatched` compte les épisodes vus sans plafond.
    - Terminée seulement par une marque de série ou `finished = 1`.
  - `stats` : `watchedSeconds` = positions exactes + temps de lecteur web sans position exacte (borné à la durée connue) ; `trackedSeconds` = temps réel passé sur la page du lecteur, somme brute de `watch_duration` des lignes film/série/anime du profil (même source que Wrapped, sans requête de plus ; 0 si l'historique est désactivé) ; `moviesFinished` = films terminés ; `episodesFinished` = somme des `episodesWatched`.
  - Classement en mémoire après 4 lectures indexées. Il est gardé 30 s par profil et langue, et oublié à chaque écriture du profil dans le worker. Import pas encore fait (`complete: false`) : il est calculé sans être gardé.
  - Infos TMDB seulement pour les séries et les films à estimer, plus la page affichée. Durées d'épisodes : une lecture groupée de `tmdb_episodes` (`getEpisodeRuntimes`), puis TMDB pour au plus 300 saisons absentes.
  - Position exacte = position **et** durée > 0, comme sur le site.
- `GET /history/title?profileId=&type=movie|tv&id=&language=` → `{ complete, title }` : fiche film ou série (`MovieDetails`, `TVDetails`), tirée du même classement mémorisé que l'onglet (`titleDetails` de `utils/historyOverview.js`), sans lecture TMDB de plus. Auth, profil, limite, import, recalage des marques et historique désactivé (`title: null`) : comme `GET /history/list`. Titre absent du classement → `title: null`.
  - `title` : `status`, `markedWatched`, `animeMode`, `estimated`, `position` / `duration` (film, ou épisode courant), `season` / `episode`, `episodesWatched` / `episodesTotal`.
  - `position` / `duration` valent null quand ils sont inconnus : ni position exacte ni estimé, ou série sans épisode courant.
  - Une série avec `markedWatched: true` (marquée vue en entier) compte tous ses épisodes comme vus. `episodes[]` n'est pas complété pour autant.
  - Pour une série, `episodes[]` : un élément par épisode avec position exacte, estimé (durée connue) ou marque, `{ season, episode, position, duration, estimated, watched, marked }`, trié. `watched` suit la règle de l'onglet ; en mode anime, les numéros sont ceux d'anime-sama. Pour un film, `episodes` vaut null.
- `GET /history/progress?profileId=&type=&id=` → `{ items }` : position de chaque épisode (ou du film) d'un titre.
- `POST /history/progress` `{ profileId, type, id, season?, episode?, position, duration }` → 204. `type` vaut `movie` ou `tv` (sinon 400) ; saison et épisode obligatoires pour une série, interdits pour un film.
- `DELETE /history/continue/:type/:id?profileId=` → 204 : retire le titre de « Reprendre ».
- `DELETE /history/title/:type/:id?profileId=` → 204 : « Supprimer de l'historique », définitif. Sous le verrou de synchro du profil (`deleteTitleFromProfile`), dans cet ordre :
  1. **Fichier du profil**, lu complet (`removeTitleFromProfile`), réécrit seulement s'il change :
     - film : `progress_<id>`, l'entrée de `continueWatching`, l'entrée de `watched_movie` ;
     - série : toutes les `progress_tv_<id>_s*_e*`, l'entrée de `continueWatching` et de `watched_tv`, la clé `watched_episodes_tv_<id>`, les entrées de `watched_tv_episodes`.

     Au-delà de 600 clés : même règle d'élagage que POST /sync.
  2. **Base** : `watch_progress`, `watch_history`, `watch_marks` du titre.
  3. **Temps du lecteur web** : `wrapped_viewing_data`, `movie` pour un film, `tv` et `anime` pour une série. Une panne de cette étape est seulement loguée.

  Le classement mémorisé est oublié.
  - Avant l'effacement en base, la route attend au plus 10 s les travaux encore en cours pour le profil : le miroir et l'import lancés sans attente par un POST /sync précédent. Ils sont suivis par profil, au plus 10 000 profils. Si l'attente expire, la route attend encore une fois puis efface de nouveau.
  - Les POST suivants, l'import et le recalage des marques relisent un fichier déjà sans le titre : ils ne le font pas revenir.
  - Une erreur après l'écriture du fichier se rattrape en relançant la suppression : le fichier propre n'est pas réécrit, la base est effacée.
- `DELETE /history/continue?profileId=` → 204 : « Tout retirer », masque toutes les cartes du profil en une seule requête SQL.

## Liaison d'une télé (`/api/tv/link`)

`routes/tvLink.js` relie l'appli télé à un compte par un code à 5 caractères. Contrat complet : [`app-tv/docs/plans/2026-10-15-phase4-liaison-compte.md`](../../app-tv/docs/plans/2026-10-15-phase4-liaison-compte.md).

- `POST /start` (télé, sans compte) `{ deviceName?, clientId }` → `deviceCode` secret, `userCode`, `verificationUrl` (`PUBLIC_SITE_URL`, sinon `https://movix.luxe`), `expiresIn` 600, `interval` 5. 10 / 10 min par IP.
- `GET /info?code=` et `POST /confirm { userCode, profileId }` (site, Bearer) : 401, 404 `code_invalid`, 403 `profile_not_owned`, 429 après cinq codes faux par utilisateur en 10 min. La confirmation crée une ligne `user_sessions` (`deviceType: 'tv'`, `name`, `clientId`) et émet le JWT ; la clé VIP du profil est revérifiée par `verifyAccessKey`.
- `POST /poll { deviceCode }` (télé) : `pending`, `slow_down` (moins de 4 s), `expired` ou `approved` avec le jeton, remis une seule fois. 40 / min par IP.

Tout l'état vit dans Redis (`tvlink:*`, `deviceCode` haché en sha256) ; sans Redis, les routes répondent 503.

## À garder en tête

- Le backend actif est ici, pas dans l'ancien contenu direct de `API/`.
- Plusieurs tables MySQL sont initialisées automatiquement au démarrage.
- Une partie du comportement applicatif dépend de caches disque et de proxys externes ; un bug peut venir d'ailleurs que du code route lui-même.
- Si une feature touche la lecture vidéo, regarde aussi `API/proxiesembed/` et parfois l'extension navigateur.
