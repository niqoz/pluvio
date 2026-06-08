# Pluvio RWH — Profil climatique de site

Application web (PWA) pour la **récupération d'eaux pluviales** (RWH) en France métropolitaine et Corse. Deux outils :

- **Onglet Pluie** : histogramme des **cumuls mensuels de précipitations** (moyenne
  climatologique longue durée) pour n'importe quel point, avec année sèche/humide.
- **Onglet Cuve** : **dimensionnement d'une cuve d'arrosage** (méthode de Rippl) à partir de
  la surface de toit, du type de couverture et des surfaces arrosées par culture.

➡️ **France (Pluvio RWH) : https://niqoz.github.io/pluvio/**
➡️ **Italie : voir le projet [Italpluvio](../italpluvio/)** — interface FR / DE / IT

## Données

- Source : **Météo-France — réanalyse SAFRAN/SIM quotidienne** (grille 8 km), Licence Ouverte 2.0.
- Précipitation totale = `PRELIQ` + `PRENEI` (pluie + neige).
- Évapotranspiration de référence ET0 = `ETP` (Penman-Monteith), utilisée par le module cuve.
- Normales calculées sur 2 fenêtres : **1995-2020** (référence) et **15 dernières années** (climat récent).
- Par mois : moyenne, P10/P90, ET0 ; par an : cumul moyen, année sèche (P10) et humide (P90).
- 9 892 mailles couvrant la métropole + Corse, commune de chaque maille via `geo.api.gouv.fr`.

## Fonctionnement

Architecture **données pré-calculées + app cliente légère** :

- `pipeline/` : scripts Python qui téléchargent SAFRAN en streaming, agrègent les normales
  par maille et produisent `normales_france.json` (~11 Mo, embarqué dans l'app).
- `docs/` : la PWA (HTML/JS, Chart maison, carte Leaflet). Servie par GitHub Pages.
  Fonctionne **hors-ligne** une fois installée (service worker). 3 modes de localisation :
  GPS, sélecteur de villes, carte interactive.
  **Responsive** : mise en page 2 colonnes automatique sur navigateur bureau (≥ 768 px).

### Module cuve

Bilan mensuel de Rippl : l'apport (pluie × toit × coefficient de ruissellement) alimente une
cuve qui couvre le besoin d'arrosage (ET0 × coefficient cultural − pluie), calculé **par
culture puis additionné**. Types de plantes : gazon froid (climat tempéré), **gazon chaud /
kikuyu** (Méditerranée, ~30 % plus sobre), potager, massifs, verger, oliviers/agrumes. Le
module propose un volume de cuve et son taux de couverture, et permet de **tester une autre
capacité** si la cuve conseillée ne rentre pas.

## Régénérer les données

```bash
python pipeline/build_france.py      # SAFRAN -> data/out/normales_france.json (pluie + ET0)
python pipeline/add_communes.py      # ajoute la commune de chaque maille
cp data/out/normales_france.json docs/normales_france.json
# Variante : pour rafraîchir seulement l'ET0 sans re-solliciter geo.api,
# utiliser `python pipeline/merge_et0.py` qui préserve les communes déjà présentes.
```

## Licences / attribution

- Données France : © Météo-France (SAFRAN/SIM, Licence Ouverte 2.0).
- Données Italie : © Copernicus Climate Change Service (ERA5-Land, Licence Copernicus).
- Communes France : © geo.api.gouv.fr / découpage administratif (Etalab).
- Communes Italie : © OpenStreetMap contributors (Nominatim).
- Fond de carte : © OpenStreetMap contributors.
- Bibliothèque carte : Leaflet (BSD-2).
