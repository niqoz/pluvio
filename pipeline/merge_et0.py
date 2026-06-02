"""Fusionne et0_moy[12] (produit par build_france.py dans data/out/) DANS le jeu
existant docs/normales_france.json, SANS toucher au reste (communes, departement,
insee, stats de pluie). Permet d'ajouter l'ET0 sans re-solliciter geo.api.gouv.fr.

Usage : python pipeline/merge_et0.py
"""
import json, sys

SRC = "data/out/normales_france.json"      # nouveau build (avec et0_moy, sans communes)
DST = "docs/normales_france.json"          # jeu de prod (avec communes, sans et0_moy)

src = json.load(open(SRC, encoding="utf-8"))
dst = json.load(open(DST, encoding="utf-8"))

maj, sans_et0, absents = 0, 0, 0
for key, d in dst.items():
    s = src.get(key)
    if s is None:
        absents += 1
        continue
    for win in ("ref_1995_2020", "recente"):
        et0 = s.get("fenetres", {}).get(win, {}).get("et0_moy")
        if et0 is not None and win in d.get("fenetres", {}):
            d["fenetres"][win]["et0_moy"] = et0
            maj += 1
        else:
            sans_et0 += 1

json.dump(dst, open(DST, "w", encoding="utf-8"), ensure_ascii=False)
print("Fusion terminee : %d fenetres mises a jour, %d sans et0, %d mailles absentes du build"
      % (maj, sans_et0, absents))
# controle rapide sur Ajaccio
aj = dst.get("11320_16810", {}).get("fenetres", {}).get("ref_1995_2020", {}).get("et0_moy")
print("Ajaccio et0_moy (ref 1995-2020) :", aj)
