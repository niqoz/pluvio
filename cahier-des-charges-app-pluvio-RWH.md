# Cahier des charges — App Pluviométrie « profil climatique de site »
### Outil d'aide au dimensionnement de la récupération d'eaux pluviales (RWH)

> Document de synthèse destiné à être fourni à Claude Code comme brief de projet.
> Version 0.2 — V1 recentrée sur l'histogramme pluviométrique ; le dimensionnement
> de cuve et le profil multi-variables sont placés en **évolutions futures** (§9).

---

## 1. Objectif

À partir de la position GPS de l'utilisateur (ou d'un point saisi), produire un
**histogramme des cumuls mensuels de précipitations (mm/mois)**, calculé comme
**moyenne climatologique sur longue durée** la plus précise possible pour le point
considéré, afin d'alimenter le dimensionnement d'installations de récupération
d'eaux pluviales.

Priorité n°1 du projet : **la précision de la donnée pluviométrique**, pas la
fraîcheur temps réel.

**Périmètre V1** : visualisation pluviométrique uniquement (histogramme + lectures
de précision). Pas de calcul de cuve, pas de multi-variables (cf. §9).

Contexte utilisateur : concepteur d'installations solaires (PV / thermique SSC),
plombier-chauffagiste, électricien. Usage de terrain, France (métropole + Corse).

---

## 2. Source de données et stratégie de précision

### 2.1 Source primaire (France métropolitaine, Corse incluse)

**Réanalyse SAFRAN / SIM quotidienne (Météo-France).**

- Grille régulière **8 km × 8 km**, 9 892 mailles, France métropolitaine.
- Pas **journalier**, de **1958 à aujourd'hui** (~67 ans de profondeur).
- Réanalyse à partir des observations locales interpolées dans chaque maille
  (réseau climatique d'État, ~1 500 postes) → adaptée au relief, très supérieure
  à ERA5 (25 km) pour la pluie.
- **Licence Ouverte 2.0** — accès libre depuis 2025.

Variables utiles :
| Code | Signification | Unité |
|------|---------------|-------|
| `PRELIQ_Q` | Précipitations liquides (cumul quotidien 06-06 UTC) | mm |
| `PRENEI_Q` | Précipitations solides (cumul quotidien 06-06 UTC) | mm |
| `SSI_Q` | Rayonnement visible (cumul quotidien) — *réservé évolutions* | J/cm² |
| `ETP_Q` | Évapotranspiration potentielle — *réservé évolutions* | mm |
| `T_Q` | Température moyenne quotidienne — *réservé évolutions* | °C |

> **Précipitation totale = `PRELIQ_Q` + `PRENEI_Q`.** (Neige incluse : elle finit en
> eau ; le décalage de fonte est négligeable au pas mensuel.)

Accès possibles (à arbitrer §10) :
- **API OGC EDR SAFRAN** : requête par point, 1958–2024.
- **Téléchargement CSV** « Données changement climatique — SIM quotidienne »
  (meteo.data.gouv.fr), lots de 1 à 10 ans.
- **NetCDF** (dépôt INRAE), une variable / fichier, toute la période.

### 2.2 Sources de précision complémentaires (cross-check, optionnel)

- **Séries homogénéisées mensuelles RR** : corrigées des ruptures artificielles →
  référence pour la moyenne de long terme et la tendance d'une station proche.
- **Séries Quotidiennes de Référence (SQR)** : stations de qualité, séries longues.
- **Base quotidienne « toutes stations »** : station réelle la plus proche.

### 2.3 Fallback hors métropole

- DOM / étranger : pas de SAFRAN → **Open-Meteo Historical (ERA5-Land ~9 km)**,
  endpoint `/v1/archive`, `precipitation_sum`, sans clé API.
  Avertir l'utilisateur de la précision moindre.

---

## 3. Méthodologie statistique

### 3.1 Normale mensuelle

Pour la maille SAFRAN contenant le point :
1. Série journalière de précipitation totale sur toute la profondeur disponible.
2. Cumul par (année, mois).
3. Moyenne des cumuls mensuels sur l'ensemble des années → 12 valeurs (mm/mois).

### 3.2 Compromis durée vs non-stationarité (réchauffement)

L'erreur-type de la moyenne décroît en ~1/√N → fenêtre longue = estimation plus
précise. Mais la pluie n'est pas stationnaire (séchage méditerranéen). On expose
**trois lectures en parallèle** :

- **Moyenne historique complète** (1958→présent) — variance minimale.
- **Normale WMO glissante 30 ans** (1991-2020) — standard officiel.
- **Fenêtre récente** (15 dernières années) — climat actuel.

Plus, par mois : **tendance** (mm/décennie), **médiane**, **P10 / P90**
(la pluie est dissymétrique → extrêmes plus parlants que la seule moyenne).

### 3.3 Indicateurs V1

- Histogramme 12 mois (moyenne) + bande de variabilité P10–P90.
- Cumul annuel moyen + cumul de l'**année déficitaire P10** (lecture « prudente »).

> Les indicateurs de sécheresse avancés et la simulation de cuve relèvent du §9.

---

## 4. Sélection spatiale

- GPS (API Geolocation) ou point saisi.
- **France métropolitaine** : maille **SAFRAN** contenant le point (mailles en
  Lambert II étendu ; prévoir conversion WGS84 ↔ Lambert via pyproj). Pas
  d'interpolation à coder : SAFRAN a déjà interpolé en tenant compte du relief.
- Afficher **altitude de la maille**, distance au point, et **avertir si l'écart
  d'altitude point/maille est important** (effet orographique).
- Hors métropole : bascule auto sur le fallback ERA5-Land.

---

## 5. Architecture

Modèle : **données pré-calculées + app cliente légère (PWA)**.

```
[Pipeline de pré-traitement (one-shot / périodique)]
   Téléchargement SAFRAN (CSV/NetCDF)
        │  agrégation : normales mensuelles (3 fenêtres), tendances, P10/P90
        ▼
   Base de normales compacte (1 enregistrement / maille)
        │
        ▼
[App PWA mobile]
   GPS → maille → lecture normales → histogramme (hors-ligne après cache)
```

La donnée brute SAFRAN est volumineuse (Go) : on ne la requête pas live depuis le
téléphone. On **pré-calcule une fois** les normales par maille (jeu final léger),
embarqué ou mis en cache (IndexedDB). Le fallback ERA5-Land peut être appelé live.

**Rafraîchissement** : SAFRAN 1958-2020 est figé ; les années récentes sont
réactualisées (mensuel/annuel). Prévoir une **version datée** du jeu pré-calculé
pour pouvoir régénérer la fenêtre récente.

---

## 6. Interface (V1)

- **Histogramme principal** : 12 barres, X = mois, Y = mm/mois.
  - Barre = moyenne ; bande **P10–P90** superposée.
  - Sélecteur de fenêtre : historique / 1991-2020 / récente
    (**défaut : lecture récente prudente**, à confirmer §10).
- **Bandeau récap** : cumul annuel moyen, cumul année sèche P10, maille utilisée,
  altitude, station de référence la plus proche, source + licence.
- Affichage clair des **réserves de précision** (cf. §11).

---

## 7. Stack technique suggérée

- **Pipeline** : Python (pandas / xarray pour NetCDF, geopandas pour les mailles,
  pyproj pour les coordonnées). Sortie : JSON ou SQLite/Parquet compact.
- **App** : PWA — HTML/JS, **Chart.js**, IndexedDB (cache hors-ligne),
  manifest + service worker (installation écran d'accueil).
- **Fallback** : fetch direct Open-Meteo `/v1/archive` (aucune clé).
- Pas d'`<form>` HTML ; gestionnaires `onClick`/`onChange`.

---

## 8. Jalons V1

1. **MVP donnée** : pipeline SAFRAN → normales mensuelles d'une maille (ex. Corse) → JSON.
2. **MVP app** : PWA, GPS → maille → histogramme 12 mois (fenêtre historique seule).
3. Trois fenêtres + bande P10/P90 + tendance + bandeau récap.
4. Fallback ERA5-Land hors métropole.

---

## 9. Évolutions futures (hors V1)

> Non implémentées au premier tour, mais l'architecture et la donnée SAFRAN les
> permettent sans refonte.

1. **Module de dimensionnement de cuve**
   - Entrées : surface de toiture, **coefficient de ruissellement** (tuiles ~0,8-0,9,
     toiture rugueuse/végétalisée moindre), pertes de **premier flush** et de filtration,
     profil de consommation.
   - Moteur : **simulation bilan entrées/sorties (méthode de Rippl / simulation
     comportementale)** sur la série journalière longue.
   - Sorties : volume de cuve conseillé, **taux de couverture des besoins**, risque
     de rupture, dimensionnement sur **année déficitaire** plutôt que sur la moyenne.
   - Indicateurs sécheresse avancés : plus longue séquence sèche, déficits mensuels
     consécutifs.

2. **Onglet solaire / thermique (métier SSC)**
   - À partir des mêmes mailles SAFRAN : **irradiation** (`SSI_Q`), **ETP** (`ETP_Q`),
     **température** (`T_Q`) en normales mensuelles.
   - Profil d'irradiation pour le pré-dimensionnement PV / thermique sur site.

3. **Cross-check station automatique** : comparaison de la normale de maille avec la
   normale homogénéisée de la station Météo-France la plus proche (contrôle qualité).

4. **Correction d'altitude locale** : ajustement optionnel point/maille en relief marqué.

---

## 10. Points à confirmer

1. **Périmètre V1** : France métropole + Corse uniquement (full SAFRAN, **recommandé**),
   ou besoin DOM / étranger dès la V1 (→ fallback ERA5-Land actif d'emblée) ?
2. **Fenêtre par défaut à l'ouverture** : lecture récente prudente (**recommandé pour
   le RWH**), normale 1991-2020, ou historique complet ?
3. **Accès SAFRAN** : pré-calcul depuis CSV/NetCDF (**recommandé**, robuste, offline)
   ou API OGC EDR ?

---

## 11. Réserves de précision à afficher

- La maille SAFRAN reste **8 km** : sur relief marqué (Corse), un écart d'altitude
  point/maille peut biaiser la pluie locale.
- C'est une **réanalyse** (observations + modèle), pas un pluviomètre sur site :
  excellente pour une normale, à pondérer pour un microclimat très particulier.
- Pour un enjeu fort, croiser avec la **station Météo-France la plus proche**.

---

## 12. Attribution / licences

- **SAFRAN / SIM quotidienne** : Licence Ouverte v2.0 (Etalab) —
  « Source : Météo-France — données SAFRAN/SIM ».
- **Open-Meteo (fallback)** : ERA5 sous CC BY 4.0 (attribution requise).
- Vérifier au build les conditions à jour de l'**API Données Climatologiques**
  Météo-France (conditions modifiées le 05/02/2026).
