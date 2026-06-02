"""Lit seulement les premieres lignes d'un gros CSV.gz distant, en streaming.
Sert a decouvrir la structure (colonnes, separateur) sans tout telecharger."""
import sys, gzip, urllib.request

URL = "https://object.files.data.gouv.fr/meteofrance/data/synchro_ftp/REF_CC/SIM/QUOT_SIM2_2010-2019.csv.gz"
N = 4  # nombre de lignes a afficher

req = urllib.request.Request(URL, headers={"User-Agent": "Mozilla/5.0"})
with urllib.request.urlopen(req) as resp:
    with gzip.GzipFile(fileobj=resp) as gz:
        for i, raw in enumerate(gz):
            line = raw.decode("utf-8", "replace").rstrip("\n")
            print(line)
            if i + 1 >= N:
                break
print("--- OK (lecture interrompue apres %d lignes) ---" % N)
