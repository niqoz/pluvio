"""Pipeline FRANCE ENTIERE : streame les tranches SAFRAN, agrege en memoire
(sans CSV intermediaire) et produit les normales mensuelles de TOUTES les mailles.

Strategie memoire : deux grands tableaux plats indexes par
   base = idx_maille * 444 + (annee-1990)*12 + (mois-1)
   444 = 37 annees (1990..2026) x 12 mois.
SUM[base] = cumul de precip, CNT[base] = nb de jours observes.
~4,4 M slots -> ~53 Mo de RAM. Aucune dependance externe.

Sortie : data/out/normales_france.json  (+ refresh maquette/ajaccio.json)
"""
import gzip, json, calendar, math, time, urllib.request
from array import array

YEAR0, YEAR1 = 1990, 2026
NYEARS = YEAR1 - YEAR0 + 1          # 37
SLOTS = NYEARS * 12                 # 444
REF_MIN, REF_MAX = 1995, 2020
RECENTE_N = 15
MIN_ANNEES = 8
MAX_JOURS_MANQUANTS = 2

URLS = [
    "https://object.files.data.gouv.fr/meteofrance/data/synchro_ftp/REF_CC/SIM/QUOT_SIM2_1990-1999.csv.gz",
    "https://object.files.data.gouv.fr/meteofrance/data/synchro_ftp/REF_CC/SIM/QUOT_SIM2_2000-2009.csv.gz",
    "https://object.files.data.gouv.fr/meteofrance/data/synchro_ftp/REF_CC/SIM/QUOT_SIM2_2010-2019.csv.gz",
    "https://object.files.data.gouv.fr/meteofrance/data/synchro_ftp/REF_CC/SIM/QUOT_SIM2_previous-2020-202604.csv.gz",
]

# ---------- stats maison ----------
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

# ---------- grille : maille -> (lat, lon), et index ----------
maille_index = {}     # "LAMBX_LAMBY" -> i
meta = []             # i -> {"lambx","lamby","lat","lon"}
def f(s): return float(s.replace(",", "."))
with open("data/raw/grille_safran.csv", encoding="utf-8") as fh:
    next(fh)
    for line in fh:
        p = line.rstrip("\n").split(";")
        if len(p) < 4: continue
        key = p[0] + "_" + p[1]
        maille_index[key] = len(meta)
        meta.append({"lambx": int(p[0]), "lamby": int(p[1]),
                     "lat": f(p[2]), "lon": f(p[3])})
N = len(meta)
print("Mailles dans la grille : %d" % N, flush=True)

# ---------- allocation des tableaux ----------
M = N * SLOTS
SUM = array('d', [0.0]) * M
SUM_ETP = array('d', [0.0]) * M   # cumul ET0 (evapotranspiration de reference, colonne ETP)
CNT = array('I', [0]) * M
print("Tableaux alloues : %d slots (~%.0f Mo)" % (M, (M*20)/1e6), flush=True)

# ---------- streaming + agregation ----------
t_start = time.time()
for url in URLS:
    name = url.rsplit("/", 1)[-1]
    print("--- stream %s ---" % name, flush=True)
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    t0 = time.time(); total = 0
    with urllib.request.urlopen(req) as resp, gzip.GzipFile(fileobj=resp) as gz:
        gz.readline()  # en-tete
        for raw in gz:
            total += 1
            line = raw.decode("utf-8", "replace")
            p = line.split(";", 13)   # jusqu'a la colonne ETP (index 12)
            if len(p) < 13: continue
            i = maille_index.get(p[0] + "_" + p[1])
            if i is None: continue
            d = p[2]
            year = int(d[:4])
            if year < YEAR0 or year > YEAR1: continue
            month = int(d[4:6])
            try:
                precip = float(p[3]) + float(p[4])
                etp = float(p[12])
            except ValueError:
                continue
            base = i * SLOTS + (year - YEAR0) * 12 + (month - 1)
            SUM[base] += precip
            SUM_ETP[base] += etp
            CNT[base] += 1
            if total % 10_000_000 == 0:
                print("  ... %d M lignes (%.0fs)" % (total/1e6, time.time()-t0), flush=True)
    print("  termine %s : %d lignes, %.0fs" % (name, total, time.time()-t0), flush=True)

print("Agregation brute terminee en %.0fs. Calcul des normales..." % (time.time()-t_start), flush=True)

# ---------- calcul des normales par maille ----------
def window_stats(cumuls, annees):
    moy, med, p10, p90 = [], [], [], []
    for m in range(1, 13):
        serie = [cumuls[m][a] for a in annees if a in cumuls[m]]
        if len(serie) >= MIN_ANNEES:
            moy.append(r1(mean(serie))); med.append(r1(quantile(serie,0.5)))
            p10.append(r1(quantile(serie,0.10))); p90.append(r1(quantile(serie,0.90)))
        else:
            moy.append(None); med.append(None); p10.append(None); p90.append(None)
    return {"moy": moy, "med": med, "p10": p10, "p90": p90}

def window_etp(cumuls_etp, annees):
    """Moyenne mensuelle de l'ET0 (mm) sur les annees de la fenetre."""
    out = []
    for m in range(1, 13):
        serie = [cumuls_etp[m][a] for a in annees if a in cumuls_etp[m]]
        out.append(r1(mean(serie)) if len(serie) >= MIN_ANNEES else None)
    return out

def annual_stats(cumul_annuel, annees):
    serie = [cumul_annuel[a] for a in annees if a in cumul_annuel]
    if len(serie) < MIN_ANNEES:
        return {"annuel_moyen": None, "annee_seche_p10": None,
                "annee_humide_p90": None, "n_annees": len(serie)}
    return {"annuel_moyen": round(mean(serie)),
            "annee_seche_p10": round(quantile(serie, 0.10)),
            "annee_humide_p90": round(quantile(serie, 0.90)),
            "n_annees": len(serie)}

# nb de jours par mois (cache, annee non bissextile + cas fevrier bissextile)
dim = {}
for y in range(YEAR0, YEAR1+1):
    for m in range(1,13):
        dim[(y,m)] = calendar.monthrange(y, m)[1]

resultat = {}
for i in range(N):
    off = i * SLOTS
    cumuls = {m: {} for m in range(1, 13)}
    cumuls_etp = {m: {} for m in range(1, 13)}
    annees_presentes = set()
    has_any = False
    for yi in range(NYEARS):
        year = YEAR0 + yi
        for m in range(1, 13):
            base = off + yi*12 + (m-1)
            c = CNT[base]
            if c == 0: continue
            has_any = True
            if c >= dim[(year, m)] - MAX_JOURS_MANQUANTS:
                cumuls[m][year] = SUM[base]
                cumuls_etp[m][year] = SUM_ETP[base]
                annees_presentes.add(year)
    if not has_any:
        continue
    cumul_annuel = {}
    for a in annees_presentes:
        if all(a in cumuls[m] for m in range(1, 13)):
            cumul_annuel[a] = sum(cumuls[m][a] for m in range(1, 13))
    toutes = sorted(annees_presentes)
    ref = [a for a in toutes if REF_MIN <= a <= REF_MAX]
    recentes = toutes[-RECENTE_N:]
    tendance = []
    for m in range(1, 13):
        pts = [(a, cumuls[m][a]) for a in toutes if a in cumuls[m]]
        tendance.append(r1(theil_sen_per_decade(pts)))
    mk = meta[i]
    resultat["%d_%d" % (mk["lambx"], mk["lamby"])] = {
        "lambx": mk["lambx"], "lamby": mk["lamby"],
        "lat": mk["lat"], "lon": mk["lon"], "altitude_m": None,
        "annees_disponibles": [toutes[0], toutes[-1]],
        "fenetres": {
            "ref_1995_2020": {**window_stats(cumuls, ref), **annual_stats(cumul_annuel, ref),
                              "et0_moy": window_etp(cumuls_etp, ref)},
            "recente": {**window_stats(cumuls, recentes), **annual_stats(cumul_annuel, recentes),
                        "et0_moy": window_etp(cumuls_etp, recentes)},
        },
        "tendance_mm_decennie": tendance,
    }

with open("data/out/normales_france.json", "w", encoding="utf-8") as out:
    json.dump(resultat, out, ensure_ascii=False)
print("Normales France : %d mailles -> data/out/normales_france.json" % len(resultat), flush=True)

# refresh extrait Ajaccio pour la maquette (coherence)
cible = "11320_16810"
if cible in resultat:
    with open("docs/ajaccio.json", "w", encoding="utf-8") as out:
        json.dump({"maille": cible, **resultat[cible]}, out, ensure_ascii=False, indent=1)
    print("-> maquette/ajaccio.json rafraichi", flush=True)
print("TOTAL %.0fs" % (time.time()-t_start), flush=True)
