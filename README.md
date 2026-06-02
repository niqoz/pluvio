# Pluvio RWH — Profil climatique de site

Application web (PWA) qui affiche l'**histogramme des cumuls mensuels de précipitations**
(moyenne climatologique longue durée) pour n'importe quel point de France métropolitaine,
afin d'aider au **dimensionnement de la récupération d'eaux pluviales** (RWH).

➡️ **Application en ligne : https://niqoz.github.io/pluvio/**

## Données

- Source : **Météo-France — réanalyse SAFRAN/SIM quotidienne** (grille 8 km), Licence Ouverte 2.0.
- Précipitation totale = `PRELIQ` + `PRENEI` (pluie + neige).
- Normales calculées sur 2 fenêtres : **1995-2020** (référence) et **15 dernières années** (climat récent).
- Par mois : moyenne, P10/P90 ; par an : cumul moyen, année sèche (P10) et humide (P90).
- 9 892 mailles couvrant la métropole + Corse, commune de chaque maille via `geo.api.gouv.fr`.

## Fonctionnement

Architecture **données pré-calculées + app cliente légère** :

- `pipeline/` : scripts Python qui téléchargent SAFRAN en streaming, agrègent les normales
  par maille et produisent `normales_france.json` (~11 Mo, embarqué dans l'app).
- `docs/` : la PWA (HTML/JS, Chart maison, carte Leaflet). Servie par GitHub Pages.
  Fonctionne **hors-ligne** une fois installée (service worker). 3 modes de localisation :
  GPS, sélecteur de villes, carte interactive.

## Régénérer les données

```bash
python pipeline/build_france.py      # SAFRAN -> data/out/normales_france.json
python pipeline/add_communes.py      # ajoute la commune de chaque maille
cp data/out/normales_france.json docs/normales_france.json
```

## Licences / attribution

- Données : © Météo-France (SAFRAN/SIM, Licence Ouverte 2.0).
- Communes : © geo.api.gouv.fr / découpage administratif (Etalab).
- Fond de carte : © OpenStreetMap contributors.
- Bibliothèque carte : Leaflet (BSD-2).
