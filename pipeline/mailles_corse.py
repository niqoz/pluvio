"""Extrait les mailles SAFRAN de Corse depuis le fichier de grille,
et identifie la maille la plus proche d'Ajaccio (cible du MVP).

Grille : separateur ';', decimale ',' (virgule).
Colonnes : LAMBX (hm);LAMBY (hm);LAT_DG;LON_DG
"""
import csv, math, json, io

GRILLE = "data/raw/grille_safran.csv"
AJACCIO = (41.9192, 8.7386)  # lat, lon

# Boite englobante large de la Corse
LAT_MIN, LAT_MAX = 41.30, 43.05
LON_MIN, LON_MAX = 8.50, 9.65

def f(s):  # convertit "48,38" -> 48.38
    return float(s.replace(",", "."))

def haversine(lat1, lon1, lat2, lon2):
    R = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp/2)**2 + math.cos(p1)*math.cos(p2)*math.sin(dl/2)**2
    return 2*R*math.asin(math.sqrt(a))

corse = []
with open(GRILLE, encoding="utf-8") as fh:
    r = csv.reader(fh, delimiter=";")
    header = next(r)
    for row in r:
        if len(row) < 4:
            continue
        lambx, lamby = int(row[0]), int(row[1])
        lat, lon = f(row[2]), f(row[3])
        if LAT_MIN <= lat <= LAT_MAX and LON_MIN <= lon <= LON_MAX:
            corse.append({"lambx": lambx, "lamby": lamby, "lat": lat, "lon": lon})

# maille la plus proche d'Ajaccio
for m in corse:
    m["dist_ajaccio_km"] = round(haversine(AJACCIO[0], AJACCIO[1], m["lat"], m["lon"]), 2)
corse.sort(key=lambda m: m["dist_ajaccio_km"])

print("Nombre de mailles SAFRAN en Corse :", len(corse))
print("\n5 mailles les plus proches d'Ajaccio :")
for m in corse[:5]:
    print("  LAMBX=%d LAMBY=%d  (%.4f, %.4f)  a %.2f km" %
          (m["lambx"], m["lamby"], m["lat"], m["lon"], m["dist_ajaccio_km"]))

# sauvegarde la liste des mailles de Corse (clef = "LAMBX_LAMBY")
ids = {f'{m["lambx"]}_{m["lamby"]}': m for m in corse}
with open("data/out/mailles_corse.json", "w", encoding="utf-8") as out:
    json.dump(ids, out, ensure_ascii=False, indent=1)
print("\n-> data/out/mailles_corse.json ecrit (%d mailles)" % len(ids))
print("Cible MVP (Ajaccio) : LAMBX=%d LAMBY=%d" % (corse[0]["lambx"], corse[0]["lamby"]))
