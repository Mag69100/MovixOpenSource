# Movix TV (native)

Appli Android TV 100 % native : Kotlin, Jetpack Compose for TV, Media3.
Elle remplacera à terme MovixTv-main (React dans une WebView).

- Spécification : [docs/spec.md](docs/spec.md)
- Plans par phase : [docs/plans/](docs/plans/)
- Notes de recherche : [docs/recherche.md](docs/recherche.md), [docs/backend-compte.md](docs/backend-compte.md)
- Maquette validée : [maquette/](maquette/)

**État : phase 3 terminée** (accueil, Films / Séries / Animés, fiche avec
épisodes, recherche, Ma liste, réglages, clé VIP, lecteur natif Media3 avec
les sources du serveur Movix, reprise, épisode suivant, générique, et
**extraction des lecteurs embed sur la télé**, sans VIP et sans WebView).

Journaux du lecteur : `MovixSources` (réponse de chaque route, en ms),
`MovixPlayer` (Cronet ou OkHttp, erreurs de lecture) et `MovixExtract`
(moteur d'extraction, résultat et durée de chaque lecteur).

## Extraction sur la télé (module `extractor/`)

Le userscript Movix (`app/src/main/assets/extract/movix.user.js`, copie
inchangée de `MovixTv-main/userscript/movix.user.js`) tourne dans un QuickJS
natif (`io.github.dokar3:quickjs-kt`), avec des polyfills navigateur minimaux
(`extractor/src/main/resources/movix-extract/`). Pas de WebView.

- La boucle d'événements est pilotée par Kotlin : minuteurs (file unique triée
  par échéance) et requêtes réseau sont des fonctions natives qui rendent la
  main tout de suite ; Kotlin rappelle le JS quand c'est prêt.
- Réseau de l'extraction : OkHttp de l'appli + règles `MediaHeaders` par hôte
  (les mêmes que pour la lecture).
- Fsvid / Vidzy : le QuickJS WebAssembly que le userscript télécharge est
  remplacé par un second QuickJS natif (une seule retouche de texte,
  `UserscriptPatcher`, journalisée si elle ne trouve plus sa cible).
- Bytecode du userscript mis en cache sur disque ; moteur fermé après 2 min
  sans extraction.
- Mettre à jour le userscript = recopier le fichier amont dans
  `app/src/main/assets/extract/`.

Essai réel sur PC (liens pris sur la Main API sans VIP, extraction, lecture du
début de chaque flux) :

```bash
MOVIX_LIVE=1 ./gradlew.bat :extractor:test --tests "*LiveExtractionTest*"
```

## Construire

Outils : JDK 17, SDK Android avec la plateforme 37 et les build-tools 37.
Sur ce poste, ils sont dans `~/.cache/movix-android-build/`.

1. Crée `local.properties` (jamais commité) :

   ```properties
   sdk.dir=C:/Users/<toi>/.cache/movix-android-build/sdk
   ```

   La clé TMDB est celle du site : Gradle lit `VITE_TMDB_API_KEY` dans le
   `.env` à la racine du dépôt movix (ou la variable d'environnement
   `MOVIX_TMDB_KEY`, sinon `tmdb.key` dans `local.properties`) et l'intègre à
   l'APK. Elle n'est jamais écrite dans le dépôt. Sans clé, une release refuse
   de se construire.

2. Lance la compilation et les tests :

   ```bash
   ./gradlew.bat :app:testDebugUnitTest :app:assembleRelease
   ```

Les APK sortent dans `app/build/outputs/apk/<type>/`, un par ABI
(`armeabi-v7a` pour la plupart des Fire TV Sticks, `arm64-v8a`, `x86` pour
l'émulateur).

| Type | Usage |
|---|---|
| `debug` | développement |
| `benchmark` | comme la release (R8, non débogable), signée debug, avec la clé VIP de test : mesurer la vraie vitesse |
| `release` | diffusion, signée avec la clé de diffusion ; la clé TMDB du site est intégrée, l'utilisateur peut mettre la sienne dans les réglages |

Ne juge jamais la vitesse sur un build `debug` : Compose y est plusieurs fois plus lent.

## Publier une mise à jour

L'appli vérifie `app-tv/version.json` du dépôt MovixOpenSource au démarrage (au
plus une fois toutes les 12 h) et à la demande dans Réglages → Mise à jour.
Elle télécharge `app-tv/movix-tv.apk`, contrôle taille, SHA-256, paquet et
version, puis passe la main à l'installeur d'Android : l'utilisateur confirme
toujours. Journaux sous l'étiquette `MovixUpdate`.

1. Augmente `versionCode` (et `versionName`) dans `app/build.gradle.kts` :
   une télé ne propose que les `versionCode` plus grands que le sien.
2. Lance, depuis `app-tv/` dans Git Bash :

   ```bash
   scripts/release.sh "Notes en français" "Notes in English"
   ```

   Le script construit `:app:assembleRelease`, prend l'APK `armeabi-v7a`
   (Fire TV ; les appareils arm64 l'installent aussi), vérifie la signature
   avec `apksigner` et **refuse une APK signée avec la clé de debug**, puis
   écrit `app-tv/movix-tv.apk` et `app-tv/version.json` (taille et SHA-256
   calculés).
3. Copie ces deux fichiers dans `MovixOpenSource1/app-tv/`, puis commit et
   push dans ce dépôt-là. Le CDN de `raw.githubusercontent.com` peut garder
   l'ancien `version.json` environ 5 minutes.

Format de `version.json` (aussi lu par la page du site) :

```json
{
  "versionCode": 2,
  "versionName": "0.2.0",
  "apkUrl": "https://raw.githubusercontent.com/movixstream/MovixOpenSource/main/app-tv/movix-tv.apk",
  "apkSize": 8437487,
  "apkSha256": "<64 caractères hexadécimaux>",
  "minSdk": 25,
  "notes": { "fr": "…", "en": "…" }
}
```

Un champ manquant, une URL hors `raw.githubusercontent.com` / `github.com` ou
en `http`, une empreinte mal formée : l'appli ignore le manifeste. Une télé
qui a une copie signée avec une autre clé (build de debug) ne peut pas se
mettre à jour : il faut désinstaller puis installer la release une fois.

## Tester sur émulateur TV

Émulateur `movix_tv` (Android TV 9, x86, 1080p), sans fenêtre ni son :

```bash
~/.cache/movix-android-build/sdk/emulator/emulator.exe -avd movix_tv -no-window -no-audio -no-boot-anim -no-snapshot -gpu host -port 5560
```

Puis `adb -s emulator-5560 install -r app/build/outputs/apk/benchmark/app-x86-benchmark.apk`.
Toujours passer `-s emulator-5560` : un téléphone peut être branché en adb sans fil.

Les journaux utiles sont sous les étiquettes `MovixPerf` (temps de chargement)
et `MovixNet` (appels réseau de plus de 2 s, étape par étape).

## Mesures (2026-10-15, émulateur, build benchmark)

- Démarrage à froid : 0,45 s.
- Catalogue de l'accueil : 0,4 s ; accueil complet avec images : < 2,5 s
  après une installation neuve.
- APK release : 1,7 Mo en phase 1, 2,6 Mo avec Media3 et Cronet (phase 2).
- Sources : les 10 routes répondent en parallèle en 70 ms quand le serveur a
  son cache (KissKH : 2,7 s).
- Fil de l'interface : 1 à 4 ms par image en défilement.
- Extraction (phase 3) : moteur prêt en 0,18 s sur PC, 0,34 à 0,53 s sur
  l'émulateur (3,2 s la toute première fois, avant le cache du bytecode) ;
  un lecteur extrait en 0,3 à 0,8 s. APK armeabi-v7a : 3,4 Mo.

## Polices

Bricolage Grotesque et Instrument Sans, sous licence SIL Open Font License 1.1,
réduites aux caractères latins (`app/src/main/res/font/`).
