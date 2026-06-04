"""Pipeline ITALIE : equivalent de build_france.py mais pour l'Italie, a partir
de la reanalyse ERA5-Land servie par l'API Open-Meteo (gratuite, non commerciale).

Pourquoi Open-Meteo plutot que SAFRAN : SAFRAN s'arrete a la frontiere francaise.
ERA5-Land (Copernicus) couvre toute l'Europe a ~9 km et fournit la pluie ET l'ET0
de reference FAO deja calculee (et0_fao_evapotranspiration) -> exactement ce dont
les onglets Pluie et Cuve ont besoin.

Subtilites verifiees sur l'API (archive-api.open-meteo.com) :
  - models=era5_land NE fournit PAS la pluie ni l'ET0 (renvoie null) : il faut
    models=best_match, qui utilise ERA5-Land (9 km) sur terre et retombe sur ERA5
    (25 km) ailleurs.
  - best_match renvoie aussi des valeurs EN MER -> on ne peut pas filtrer la mer
    par les null. On filtre avec le POLYGONE des regions italiennes (point-dans-
    polygone), ce qui exclut aussi les pays voisins qui depassent dans la bbox.
  - l'API renvoie l'altitude du point -> on remplit altitude_m (absent cote France).

Deux modes :
  python pipeline/build_italie.py --sample   # ~20 villes reelles -> demo immediate
  python pipeline/build_italie.py            # grille complete 0,1 deg sur l'Italie

Sortie : docs/it/normales_italie.json  (meme schema que normales_france.json)
Reprise : un cache JSONL (data/out/italie_cache.jsonl) permet de relancer sans
tout refaire (utile vu les limites de debit d'Open-Meteo sur la grille complete).
"""
import json, math, time, os, sys, urllib.request, urllib.error, calendar
from datetime import date, timedelta

# ------------------------------------------------------------------ parametres
ARCHIVE = "https://archive-api.open-meteo.com/v1/archive"
START = "1991-01-01"
END = (date.today() - timedelta(days=10)).isoformat()   # ERA5 a ~5 j de retard
REF_MIN, REF_MAX = 1995, 2020
RECENTE_N = 15
MIN_ANNEES = 8
MAX_JOURS_MANQUANTS = 2

# grille : pas 0,1 deg (= maille native ERA5-Land), bbox Italie + iles
LAT0, LAT1, LON0, LON1 = 35.40, 47.10, 6.60, 18.60
STEP = 0.1

GEOJSON_REGIONS = ("https://raw.githubusercontent.com/openpolis/geojson-italy/"
                   "master/geojson/limits_IT_regions.geojson")
GEOJSON_CACHE = "data/raw/italie_regions.geojson"
RAW_CACHE = "data/out/italie_cache.jsonl"
OUT = "docs/it/normales_italie.json"

# villes de demonstration (mode --sample) : nom -> (lat, lon)
VILLES = {
    "Roma": (41.90, 12.50), "Milano": (45.46, 9.19), "Napoli": (40.85, 14.27),
    "Torino": (45.07, 7.69), "Palermo": (38.12, 13.36), "Genova": (44.41, 8.93),
    "Bologna": (44.49, 11.34), "Firenze": (43.77, 11.26), "Bari": (41.12, 16.87),
    "Catania": (37.50, 15.09), "Venezia": (45.44, 12.33), "Cagliari": (39.22, 9.12),
    "Trieste": (45.65, 13.78), "Bolzano": (46.50, 11.35), "Perugia": (43.11, 12.39),
    "Reggio Calabria": (38.11, 15.65), "Sassari": (40.73, 8.56), "Pescara": (42.46, 14.21),
    "Lecce": (40.35, 18.17), "Cortina d'Ampezzo": (46.54, 12.14),
}

# ------------------------------------------------------------------ stats (= build_france.py)
def quantile(vals, q):
    s = sorted(vals); n = len(s)
    if n == 0: return None
    if n == 1: return s[0]
    pos = q * (n - 1); lo = int(math.floor(pos)); frac = pos - lo
    return s[lo] + frac * (s[lo + 1] - s[lo]) if lo + 1 < n else s[lo]

def mean(vals):
    return sum(vals) / len(vals) if vals else None

def theil_sen_per_decade(points):
    pts = [p for p in points if p[1] is not None]
    if len(pts) < 3: return None
    slopes = []
    for i in range(len(pts)):
        for j in range(i + 1, len(pts)):
            dx = pts[j][0] - pts[i][0]
            if dx: slopes.append((pts[j][1] - pts[i][1]) / dx)
    return quantile(slopes, 0.5) * 10.0 if slopes else None

def r1(x): return None if x is None else round(x, 1)

# ------------------------------------------------------------------ Open-Meteo
class QuotaStop(Exception):
    """Quota HORAIRE ou JOURNALIER Open-Meteo atteint : on arrete proprement.
    Inutile de continuer maintenant (ces fenetres ne se reinitialisent pas en quelques
    secondes) -> on reprendra plus tard via le cache. portee = 'horaire' ou 'journalier'."""
    def __init__(self, portee, reason):
        self.portee = portee; super().__init__(reason)

# compteurs globaux de quota, pour le bilan de fin
QUOTA = {"minute": 0, "heure": 0}

def fetch_point(lat, lon, retries=7):
    """Renvoie (elevation, jours, err). err=None si OK ; sinon raison de l'echec.
    jours = {'YYYY-MM-DD': (precip, et0)}.
    Open-Meteo renvoie la raison du 429 dans le corps JSON ('reason'). On distingue :
      - limite PAR MINUTE / PAR HEURE -> on patiente et on retente (backoff) ;
      - limite PAR HEURE ou PAR JOUR -> on leve QuotaStop (stop propre, reprise plus tard).
    Les longues plages (35 ans) 'coutent' cher en quota -> 429 frequents."""
    url = ("%s?latitude=%.4f&longitude=%.4f&start_date=%s&end_date=%s"
           "&daily=precipitation_sum,et0_fao_evapotranspiration"
           "&models=best_match&timezone=UTC"
           % (ARCHIVE, lat, lon, START, END))
    delay = 3.0
    last = "inconnu"
    for _ in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "italpluvio-rwh"})
            with urllib.request.urlopen(req, timeout=120) as r:
                d = json.loads(r.read().decode("utf-8"))
            dd = d.get("daily") or {}
            t = dd.get("time") or []
            pr = dd.get("precipitation_sum") or []
            e0 = dd.get("et0_fao_evapotranspiration") or []
            jours = {t[k]: (pr[k], e0[k]) for k in range(len(t))}
            return d.get("elevation"), jours, None
        except urllib.error.HTTPError as e:
            if e.code == 429:
                reason = ""
                try:
                    reason = (json.loads(e.read().decode("utf-8")) or {}).get("reason", "")
                except Exception:
                    pass
                rl = reason.lower()
                if "daily" in rl or "jour" in rl:
                    raise QuotaStop("journalier", reason or "limite journaliere")
                if "hour" in rl or "heure" in rl:
                    raise QuotaStop("horaire", reason or "limite horaire")
                # limite PAR MINUTE seulement : se reinitialise en 60 s -> on attend et on retente
                QUOTA["minute"] += 1
                last = "429 quota/minute"
                print("    quota minute atteint -> pause %.0fs" % delay, flush=True)
                time.sleep(delay); delay = min(delay * 2, 65); continue
            last = "HTTP %d" % e.code
            time.sleep(delay); delay *= 2
        except Exception as ex:
            last = type(ex).__name__ + ": " + str(ex)[:50]
            time.sleep(delay); delay *= 2
    return None, None, last

# ------------------------------------------------------------------ agregation d'un point
def aggregate(jours):
    """jours = {'YYYY-MM-DD': (precip, et0)} -> objet maille (fenetres, tendance...)
    ou None si pas assez de donnees. Meme logique que build_france.py."""
    # cumuls[mois][annee] = somme mensuelle de pluie ; idem ET0 ; en comptant les jours
    cumuls = {m: {} for m in range(1, 13)}
    cumuls_etp = {m: {} for m in range(1, 13)}
    cnt = {}             # (annee, mois) -> nb de jours valides
    sump = {}; sume = {}
    for ds, (p, e) in jours.items():
        if p is None:    # jour sans pluie ERA5 -> jour manquant
            continue
        y = int(ds[0:4]); m = int(ds[5:7])
        k = (y, m)
        cnt[k] = cnt.get(k, 0) + 1
        sump[k] = sump.get(k, 0.0) + p
        sume[k] = sume.get(k, 0.0) + (e if e is not None else 0.0)

    annees_presentes = set()
    for (y, m), c in cnt.items():
        if c >= calendar.monthrange(y, m)[1] - MAX_JOURS_MANQUANTS:
            cumuls[m][y] = sump[(y, m)]
            cumuls_etp[m][y] = sume[(y, m)]
            annees_presentes.add(y)
    if not annees_presentes:
        return None

    cumul_annuel = {}
    for a in annees_presentes:
        if all(a in cumuls[m] for m in range(1, 13)):
            cumul_annuel[a] = sum(cumuls[m][a] for m in range(1, 13))
    toutes = sorted(annees_presentes)
    ref = [a for a in toutes if REF_MIN <= a <= REF_MAX]
    recentes = toutes[-RECENTE_N:]

    def window_stats(annees):
        moy, med, p10, p90 = [], [], [], []
        for m in range(1, 13):
            serie = [cumuls[m][a] for a in annees if a in cumuls[m]]
            if len(serie) >= MIN_ANNEES:
                moy.append(r1(mean(serie))); med.append(r1(quantile(serie, 0.5)))
                p10.append(r1(quantile(serie, 0.10))); p90.append(r1(quantile(serie, 0.90)))
            else:
                moy.append(None); med.append(None); p10.append(None); p90.append(None)
        return {"moy": moy, "med": med, "p10": p10, "p90": p90}

    def window_etp(annees):
        out = []
        for m in range(1, 13):
            serie = [cumuls_etp[m][a] for a in annees if a in cumuls_etp[m]]
            out.append(r1(mean(serie)) if len(serie) >= MIN_ANNEES else None)
        return out

    def annual_stats(annees):
        serie = [cumul_annuel[a] for a in annees if a in cumul_annuel]
        if len(serie) < MIN_ANNEES:
            return {"annuel_moyen": None, "annee_seche_p10": None,
                    "annee_humide_p90": None, "n_annees": len(serie)}
        return {"annuel_moyen": round(mean(serie)),
                "annee_seche_p10": round(quantile(serie, 0.10)),
                "annee_humide_p90": round(quantile(serie, 0.90)),
                "n_annees": len(serie)}

    tendance = []
    for m in range(1, 13):
        pts = [(a, cumuls[m][a]) for a in toutes if a in cumuls[m]]
        tendance.append(r1(theil_sen_per_decade(pts)))

    return {
        "annees_disponibles": [toutes[0], toutes[-1]],
        "fenetres": {
            "ref_1995_2020": {**window_stats(ref), **annual_stats(ref),
                              "et0_moy": window_etp(ref)},
            "recente": {**window_stats(recentes), **annual_stats(recentes),
                        "et0_moy": window_etp(recentes)},
        },
        "tendance_mm_decennie": tendance,
    }

# ------------------------------------------------------------------ point-dans-polygone
def _ray(lat, lon, ring):
    """Even-odd ray casting. ring = [[lon,lat], ...]."""
    inside = False; n = len(ring); j = n - 1
    for i in range(n):
        xi, yi = ring[i][0], ring[i][1]
        xj, yj = ring[j][0], ring[j][1]
        if ((yi > lat) != (yj > lat)) and \
           (lon < (xj - xi) * (lat - yi) / (yj - yi) + xi):
            inside = not inside
        j = i
    return inside

def in_polygon(lat, lon, polys):
    """polys = liste de Polygons, chaque Polygon = [exterior, hole, ...] (rings GeoJSON)."""
    for rings in polys:
        if _ray(lat, lon, rings[0]) and not any(_ray(lat, lon, h) for h in rings[1:]):
            return True
    return False

def load_italy_polys():
    if not os.path.exists(GEOJSON_CACHE):
        os.makedirs(os.path.dirname(GEOJSON_CACHE), exist_ok=True)
        print("Telechargement du polygone Italie...", flush=True)
        req = urllib.request.Request(GEOJSON_REGIONS, headers={"User-Agent": "italpluvio"})
        with urllib.request.urlopen(req, timeout=60) as r, open(GEOJSON_CACHE, "wb") as o:
            o.write(r.read())
    gj = json.load(open(GEOJSON_CACHE, encoding="utf-8"))
    polys = []
    for feat in gj.get("features", []):
        g = feat.get("geometry") or {}
        if g.get("type") == "Polygon":
            polys.append(g["coordinates"])
        elif g.get("type") == "MultiPolygon":
            polys.extend(g["coordinates"])
    print("Polygones Italie charges : %d" % len(polys), flush=True)
    return polys

# ------------------------------------------------------------------ cache de reprise
def load_cache():
    done = {}
    if os.path.exists(RAW_CACHE):
        for line in open(RAW_CACHE, encoding="utf-8"):
            line = line.strip()
            if not line: continue
            o = json.loads(line)
            done[o["id"]] = o
    return done

def append_cache(rec):
    os.makedirs(os.path.dirname(RAW_CACHE), exist_ok=True)
    with open(RAW_CACHE, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")

# ------------------------------------------------------------------ programme
def key_of(lat, lon):
    return "%d_%d" % (round(lat * 1000), round(lon * 1000))

def build_points(sample):
    """Renvoie la liste de points a traiter : [(id, lat, lon, label_or_None)]."""
    if sample:
        return [(key_of(la, lo), la, lo, nom) for nom, (la, lo) in VILLES.items()]
    polys = load_italy_polys()
    pts = []
    nlat = int(round((LAT1 - LAT0) / STEP))
    nlon = int(round((LON1 - LON0) / STEP))
    for i in range(nlat + 1):
        lat = round(LAT0 + i * STEP, 2)
        for jx in range(nlon + 1):
            lon = round(LON0 + jx * STEP, 2)
            if in_polygon(lat, lon, polys):
                pts.append((key_of(lat, lon), lat, lon, None))
    print("Points terrestres dans la grille : %d" % len(pts), flush=True)
    return pts

def main():
    global STEP, START
    sample = "--sample" in sys.argv
    # options pour alleger le quota : --step=0.2 (grille plus large), --start=1995-01-01 (periode plus courte)
    for a in sys.argv[1:]:
        if a.startswith("--step="):
            STEP = float(a.split("=", 1)[1])
        elif a.startswith("--start="):
            START = a.split("=", 1)[1]
    if not sample:
        print("Grille : pas %.2f deg, periode %s -> %s" % (STEP, START, END), flush=True)
    pts = build_points(sample)
    done = load_cache()    # reprise : sample ET grille partagent le cache (cle = coordonnee)
    sleep = 0.0 if sample else 0.4     # throttling pour la grille complete
    t0 = time.time(); n = 0
    echecs = []            # [(pid, lat, lon, raison)] : echecs definitifs (apres tous les essais)
    a_faire = [p for p in pts if p[0] not in done]
    deja = len(pts) - len(a_faire)
    print("A traiter : %d points (%d deja en cache)" % (len(a_faire), deja), flush=True)
    quota_jour = False
    try:
        for pid, lat, lon, label in a_faire:
            n += 1
            elev, jours, err = fetch_point(lat, lon)
            if jours is None:
                echecs.append((pid, lat, lon, err))
                print("  ECHEC %s (%.2f,%.2f) : %s" % (pid, lat, lon, err), flush=True)
                continue
            agg = aggregate(jours)
            if agg is None:
                echecs.append((pid, lat, lon, "donnees insuffisantes"))
                continue
            rec = {"id": pid, "lat": lat, "lon": lon,
                   "altitude_m": (round(elev) if elev is not None else None),
                   "label": label, **agg}
            done[pid] = rec
            append_cache(rec)
            if n % 25 == 0 or sample:
                print("  %d/%d  %s alt=%s  (%.0fs)"
                      % (n, len(a_faire), pid, rec["altitude_m"], time.time() - t0), flush=True)
            if sleep:
                time.sleep(sleep)
    except QuotaStop as e:
        quota_jour = True
        quand = "dans une heure" if e.portee == "horaire" else "demain"
        print("\n*** QUOTA %s Open-Meteo atteint : %s" % (e.portee.upper(), e), flush=True)
        print("    Arret propre. Tout ce qui est fait est dans le cache.", flush=True)
        print("    -> relance la MEME commande %s : elle reprendra ou elle en est." % quand, flush=True)

    # assemblage final au schema de l'app (cle = id)
    resultat = {}
    for pid, rec in done.items():
        resultat[pid] = {
            "lat": rec["lat"], "lon": rec["lon"], "altitude_m": rec.get("altitude_m"),
            "commune": None, "departement": None, "insee": None,
            "annees_disponibles": rec["annees_disponibles"],
            "fenetres": rec["fenetres"],
            "tendance_mm_decennie": rec["tendance_mm_decennie"],
        }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump(resultat, open(OUT, "w", encoding="utf-8"), ensure_ascii=False)

    # ---- bilan de fin : tout ce qui touche au quota est visible ici ----
    non_tentes = max(0, len(a_faire) - n)   # points pas atteints (arret quota journalier)
    echecs_path = os.path.join(os.path.dirname(OUT), "italie_echecs.txt")
    if echecs:
        with open(echecs_path, "w", encoding="utf-8") as f:
            for pid, la, lo, raison in echecs:
                f.write("%s\t%.4f\t%.4f\t%s\n" % (pid, la, lo, raison))
    print("\n========== BILAN ==========", flush=True)
    print("Ecrit %s : %d points (%.0fs)" % (OUT, len(resultat), time.time() - t0), flush=True)
    print("Quota : %d pauses 'par minute', %d pauses 'par heure'"
          % (QUOTA["minute"], QUOTA["heure"]), flush=True)
    print("Echecs definitifs (apres tous les essais) : %d" % len(echecs), flush=True)
    if echecs:
        from collections import Counter
        par_raison = Counter(r for _, _, _, r in echecs)
        for raison, c in par_raison.most_common():
            print("    %4d  %s" % (c, raison), flush=True)
        print("    liste detaillee -> %s" % echecs_path, flush=True)
        print("    -> relance la meme commande : le cache saute les points OK,")
        print("       elle ne retentera que ces echecs.", flush=True)
    if quota_jour or non_tentes:
        print("Points NON tentes (quota journalier / arret) : %d" % non_tentes, flush=True)
        print("    -> relance demain pour les completer.", flush=True)
    if not echecs and not non_tentes and not sample:
        print("Grille complete : aucun manquant. ✓", flush=True)

if __name__ == "__main__":
    main()
