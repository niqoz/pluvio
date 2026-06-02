# Pluvio RWH — Contexte projet pour Claude Code

## Décisions fonctionnelles V1 (§10 du cahier des charges)

1. **Périmètre** : France métropolitaine + Corse uniquement. SAFRAN seul, pas de fallback ERA5-Land en V1.
2. **Fenêtre par défaut** : **1995-2020** (2 fenêtres affichées : 1995-2020 et les 15 dernières années ; la fenêtre « toute l'histoire » a été retirée).
3. **Accès SAFRAN** : Option A — pré-calcul depuis fichiers (streaming CSV.gz, sans écriture d'intermédiaires pour la France entière).
4. **Sélection spatiale** : GPS smartphone (prioritaire) + sélecteur de villes + carte interactive (Leaflet, mode complémentaire).
5. **Commune** : position GPS exacte via `geo.api.gouv.fr` (appel en ligne) ; commune du carré embarquée dans le JSON pour fallback offline.
6. **Point en mer** : message « pas de donnée ici », pas de traitement spécial.
7. **Année sèche/humide** : P10/P90 des cumuls **annuels réels** (PAS la somme des P10/P90 mensuels — piège évité).

## Architecture

```
pipeline/          Scripts Python de pré-calcul (one-shot)
  build_france.py  SAFRAN -> data/out/normales_france.json  (streaming, ~5 min)
  add_communes.py  Ajoute commune/departement/insee à chaque maille (geo.api.gouv.fr, 24 threads)
  aggregate.py     Agrégation Corse seule (test/validation)
  extract_corse.py Extraction streaming d'une zone (CSV intermédiaire)
  mailles_corse.py Identifie les 168 mailles de Corse
  generate_icons.py Génère les icônes PWA (Pillow)
  sniff_header.py  Outil de diagnostic (lit quelques lignes d'un CSV.gz distant)

docs/              App cliente PWA (GitHub Pages)
  index.html       App complète (HTML/JS, pas de framework)
  normales_france.json  Jeu de données (11,8 Mo, 9892 mailles)
  sw.js            Service worker (network-first, cache offline)
  manifest.webmanifest  Identité PWA
  icon-192/512.png Icônes (goutte d'eau bleue)
  vendor/leaflet/  Leaflet 1.9.4 embarqué localement

data/              Données brutes et intermédiaires (dans .gitignore, ~5 Go)
  raw/grille_safran.csv   Grille SAFRAN (9892 mailles, Lambert II étendu)
  raw/corse_*.csv         Extraits Corse par décennie (reproductibles)
  out/normales_france.json Source → copier dans docs/ après regénération
```

## Données SAFRAN : détails techniques

- **Source** : `https://object.files.data.gouv.fr/meteofrance/data/synchro_ftp/REF_CC/SIM/`
- **Fichiers** : `QUOT_SIM2_1990-1999.csv.gz`, `…2000-2009`, `…2010-2019`, `QUOT_SIM2_previous-2020-202604.csv.gz`
- **Colonnes réelles** : `LAMBX;LAMBY;DATE;PRENEI;PRELIQ;T;…` — séparateur `;`, décimale **point**, DATE=YYYYMMDD.
  ⚠️ Les noms sont `PRELIQ`/`PRENEI` **sans** le suffixe `_Q` annoncé dans le cahier des charges.
- **Pluie totale** = `PRELIQ + PRENEI` (pluie + neige).
- **Grille** : `coordonnees_grille_safran_lambert-2-etendu.csv` — séparateur `;`, décimale **virgule**, colonnes `LAMBX (hm);LAMBY (hm);LAT_DG;LON_DG`. Pas d'altitude dans ce fichier.
- **9 892 mailles**, France métropolitaine + Corse.
- Maille cible Ajaccio : **`11320_16810`** (centre 41.939, 8.738, à 2,25 km du centre-ville).

## Jeu de données produit (`normales_france.json`)

Par maille (clé = `"LAMBX_LAMBY"`) :
```json
{
  "lambx": 11320, "lamby": 16810, "lat": 41.939, "lon": 8.738,
  "altitude_m": null,
  "commune": "Ajaccio", "departement": "Corse-du-Sud", "insee": "2A004",
  "annees_disponibles": [1990, 2026],
  "fenetres": {
    "ref_1995_2020": { "moy":[...], "med":[...], "p10":[...], "p90":[...],
                       "annuel_moyen": 771, "annee_seche_p10": 520,
                       "annee_humide_p90": 988, "n_annees": 26 },
    "recente":       { ... }
  },
  "tendance_mm_decennie": [9.7, 8.0, ...]
}
```
- **8 594/9 892** mailles ont une commune (87 %) ; 1 298 en mer/côte (normal).
- `altitude_m` = null partout (pas dans la grille, à faire).

## Application (docs/)

- **findMaille** : plus proche voisin haversine, **privilégie les mailles avec commune** (évite les carrés maritimes près des côtes).
- **Commune position** : appel `geo.api.gouv.fr/communes?lat=&lon=` au clic (en ligne) ; fallback offline = commune du carré embarquée.
- **Service worker** : network-first. Incrémenter `const CACHE = "pluvio-rwh-vN"` à chaque mise à jour pour forcer le rechargement.
- **Aide iOS** : bandeau automatique si iPhone/iPad non installé (pas de bouton d'install auto sur iOS — geste manuel Partager → Sur l'écran d'accueil dans Safari).
- **Vérifier la version** : étiquette footer affiche `"N carrés · M communes"` ; 0 communes = ancien cache.

## Déploiement

- **URL de production** : https://niqoz.github.io/pluvio/
- **Repo** : https://github.com/niqoz/pluvio
- GitHub Pages sert `main /docs`. Redéploiement ~1 min après `git push`.
- Git user local : `niqoz / niqoz@users.noreply.github.com` (pas de config globale sur la machine d'origine).

## Régénérer les données (si nouvelles années SAFRAN disponibles)

```bash
python pipeline/build_france.py           # streaming ~5 min -> data/out/normales_france.json
python pipeline/add_communes.py           # ~2 min -> ajoute commune/departement/insee
cp data/out/normales_france.json docs/normales_france.json
# Incrémenter CACHE dans docs/sw.js
git add docs/ && git commit -m "Regénération données SAFRAN YYYY" && git push
```

## Évolutions prévues (hors V1, §9 du cahier des charges)

- **Altitude des mailles** : absente du fichier grille, à récupérer (shapefile SIM ou MNT).
- **APK Android** : via PWABuilder depuis l'URL Pages → autonomie totale indépendante du cache navigateur.
- **Module dimensionnement de cuve** : surface toiture, coefficient de ruissellement, profil consommation → simulation Rippl → volume conseillé + taux de couverture.
- **Onglet solaire/thermique** : irradiation SSI_Q, ETP, température T_Q (données déjà dans SAFRAN).
- **Fallback hors-métropole** : Open-Meteo Historical (ERA5-Land) pour DOM/étranger.
- **Nom définitif** : « Pluvio RWH » est provisoire.

## User

- Installateur solaire (PV/thermique SSC) + plombier-chauffagiste, usage terrain.
- En SSH sur la machine Windows (serveur distant). Commandes interactives à taper avec le préfixe `!` dans l'invite Claude Code.
- Box Orange (livebox) ne résout pas `*.trycloudflare.com` — sans objet depuis le passage à github.io.
- Préfère les explications en langage simple (pas de jargon technique non expliqué).
