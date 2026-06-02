"""Telecharge UNE tranche SIM en streaming, decompresse a la volee, et n'ecrit
que les lignes des mailles de Corse (colonnes utiles). Le gros volume reste sur
le reseau ; on n'ecrit sur disque qu'un petit extrait.

Usage : python pipeline/extract_corse.py <url> <fichier_sortie.csv>
Sortie : CSV ';' avec colonnes  LAMBX;LAMBY;DATE;PRENEI;PRELIQ
"""
import sys, gzip, json, urllib.request, time

url, out_path = sys.argv[1], sys.argv[2]

# set des mailles de Corse, sous forme de prefixe "LAMBX;LAMBY;"
with open("data/out/mailles_corse.json", encoding="utf-8") as fh:
    mailles = json.load(fh)
prefixes = set()
for key in mailles:  # key = "LAMBX_LAMBY"
    x, y = key.split("_")
    prefixes.add(x + ";" + y + ";")

req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
t0 = time.time()
kept = 0
total = 0
with urllib.request.urlopen(req) as resp, \
     gzip.GzipFile(fileobj=resp) as gz, \
     open(out_path, "w", encoding="utf-8", newline="") as out:
    out.write("LAMBX;LAMBY;DATE;PRENEI;PRELIQ\n")
    header = gz.readline()  # saute l'en-tete d'origine
    for raw in gz:
        total += 1
        line = raw.decode("utf-8", "replace")
        # filtre rapide sur le prefixe "LAMBX;LAMBY;"
        # on coupe apres le 2e ';' pour tester l'appartenance
        i1 = line.find(";")
        i2 = line.find(";", i1 + 1)
        if i2 == -1:
            continue
        if line[:i2 + 1] in prefixes:
            # garde LAMBX;LAMBY;DATE;PRENEI;PRELIQ = 5 premiers champs
            parts = line.split(";", 5)
            out.write(";".join(parts[:5]) + "\n")
            kept += 1
        if total % 5_000_000 == 0:
            print("  ... %d lignes lues, %d gardees (%.0fs)" %
                  (total, kept, time.time() - t0), flush=True)

print("TERMINE : %d lignes lues, %d gardees, %.0fs -> %s" %
      (total, kept, time.time() - t0, out_path), flush=True)
