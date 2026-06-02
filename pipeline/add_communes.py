"""Ajoute la commune (et le departement) de chaque maille au jeu France.

Utilise geo.api.gouv.fr/communes?lat=&lon= qui renvoie la commune CONTENANT le
point (decoupage administratif) -> marche partout sur terre, y compris zones
rurales/montagne (contrairement a la Base Adresse Nationale). Requetes
parallelisees. Appel fait UNE fois au pre-calcul -> noms embarques, app offline.
Points en mer -> pas de commune (normal).

Sortie : met a jour data/out/normales_france.json (champs commune/departement/insee)
"""
import json, urllib.request, urllib.error
from concurrent.futures import ThreadPoolExecutor

SRC = "data/out/normales_france.json"
WORKERS = 24

data = json.load(open(SRC, encoding="utf-8"))
items = list(data.items())
print("Mailles a geocoder : %d" % len(items), flush=True)

def geocode(item):
    mid, d = item
    url = ("https://geo.api.gouv.fr/communes?lat=%f&lon=%f&fields=nom,code,departement"
           % (d["lat"], d["lon"]))
    for _ in range(2):  # 1 retry
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "pluvio-rwh"})
            with urllib.request.urlopen(req, timeout=15) as r:
                arr = json.loads(r.read().decode("utf-8"))
            if arr:
                c = arr[0]
                dep = (c.get("departement") or {}).get("nom", "")
                return mid, c.get("nom", ""), dep, c.get("code", "")
            return mid, "", "", ""      # en mer / hors decoupage
        except Exception:
            continue
    return mid, None, None, None        # echec reseau -> a retenter

done = 0; sans = 0; echecs = 0
with ThreadPoolExecutor(max_workers=WORKERS) as ex:
    for mid, com, dep, insee in ex.map(geocode, items):
        done += 1
        if com is None:
            echecs += 1
        else:
            data[mid]["commune"] = com
            data[mid]["departement"] = dep
            data[mid]["insee"] = insee
            if not com:
                sans += 1
        if done % 1000 == 0:
            print("  ... %d / %d  (%d en mer, %d echecs reseau)"
                  % (done, len(items), sans, echecs), flush=True)

json.dump(data, open(SRC, "w", encoding="utf-8"), ensure_ascii=False)
print("Reecrit %s" % SRC, flush=True)
print("Bilan : %d communes, %d en mer/sans, %d echecs reseau"
      % (len(items)-sans-echecs, sans, echecs), flush=True)
for mid in ("11320_16810", "7028_24528"):
    if mid in data:
        print("  %s -> %s (%s)" % (mid, data[mid].get("commune"), data[mid].get("departement")), flush=True)
