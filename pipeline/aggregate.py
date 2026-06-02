"""Pipeline d'agregation SAFRAN -> normales mensuelles par maille (JSON).

Entree : un ou plusieurs CSV extraits (corse_*.csv), colonnes
         LAMBX;LAMBY;DATE;PRENEI;PRELIQ  (decimale point, DATE=YYYYMMDD).
Sortie : data/out/normales_corse.json

Calculs (conformes aux decisions du projet) :
  - precipitation totale quotidienne = PRELIQ + PRENEI (neige incluse).
  - cumul mensuel d'une (annee, mois) seulement si le mois est quasi complet.
  - 3 fenetres : historique (tout) / reference 1995-2020 / recente (15 dern. annees).
  - par mois : moyenne, mediane, P10, P90 sur les cumuls mensuels des annees.
  - cumul annuel moyen + ANNEE SECHE = P10 des cumuls ANNUELS reels
    (PAS la somme des P10 mensuels -> piege evite).
  - tendance mm/decennie par mois : pente de Theil-Sen (robuste) sur l'historique.
Aucune dependance externe.
"""
import sys, csv, json, calendar, math
from collections import defaultdict

REF_MIN, REF_MAX = 1995, 2020   # fenetre de reference (defaut appli)
RECENTE_N = 15                  # nb d'annees de la fenetre "climat recent"
MIN_ANNEES = 8                  # sous ce nb d'annees, on ne publie pas la stat
MAX_JOURS_MANQUANTS = 2         # tolerance par mois pour le juger "complet"

# ---------- statistiques maison ----------
def quantile(vals, q):
    """Quantile par interpolation lineaire (equiv. numpy 'linear'/type 7)."""
    s = sorted(vals)
    n = len(s)
    if n == 0:
        return None
    if n == 1:
        return s[0]
    pos = q * (n - 1)
    lo = int(math.floor(pos))
    frac = pos - lo
    if lo + 1 < n:
        return s[lo] + frac * (s[lo + 1] - s[lo])
    return s[lo]

def mean(vals):
    return sum(vals) / len(vals) if vals else None

def theil_sen_per_decade(points):
    """points = [(annee, valeur)]. Pente robuste (mediane des pentes), x10 -> /decennie."""
    pts = [p for p in points if p[1] is not None]
    if len(pts) < 3:
        return None
    slopes = []
    for i in range(len(pts)):
        for j in range(i + 1, len(pts)):
            dx = pts[j][0] - pts[i][0]
            if dx != 0:
                slopes.append((pts[j][1] - pts[i][1]) / dx)
    if not slopes:
        return None
    return quantile(slopes, 0.5) * 10.0

def r1(x):
    return None if x is None else round(x, 1)

# ---------- lecture ----------
# monthly[maille][(annee, mois)] = [somme_precip, nb_jours]
monthly = defaultdict(lambda: defaultdict(lambda: [0.0, 0]))

files = sys.argv[1:]
if not files:
    print("Usage: python pipeline/aggregate.py <corse_xxxx.csv> [autres.csv ...]")
    sys.exit(1)

for path in files:
    with open(path, encoding="utf-8") as fh:
        r = csv.reader(fh, delimiter=";")
        next(r, None)  # en-tete
        for row in r:
            if len(row) < 5:
                continue
            maille = row[0] + "_" + row[1]
            d = row[2]
            year, month = int(d[:4]), int(d[4:6])
            try:
                precip = float(row[3]) + float(row[4])  # PRENEI + PRELIQ
            except ValueError:
                continue
            cell = monthly[maille][(year, month)]
            cell[0] += precip
            cell[1] += 1

# ---------- agregation par maille ----------
with open("data/out/mailles_corse.json", encoding="utf-8") as fh:
    meta_mailles = json.load(fh)

def window_stats(cumuls_par_mois, annees_cibles):
    """cumuls_par_mois[mois] = {annee: cumul}. Retourne stats par mois sur annees_cibles."""
    moy, med, p10, p90 = [], [], [], []
    for m in range(1, 13):
        serie = [cumuls_par_mois[m][a] for a in annees_cibles if a in cumuls_par_mois[m]]
        if len(serie) >= MIN_ANNEES:
            moy.append(r1(mean(serie)))
            med.append(r1(quantile(serie, 0.5)))
            p10.append(r1(quantile(serie, 0.10)))
            p90.append(r1(quantile(serie, 0.90)))
        else:
            moy.append(None); med.append(None); p10.append(None); p90.append(None)
    return {"moy": moy, "med": med, "p10": p10, "p90": p90}

def annual_stats(cumul_annuel, annees_cibles):
    serie = [cumul_annuel[a] for a in annees_cibles if a in cumul_annuel]
    if len(serie) < MIN_ANNEES:
        return {"annuel_moyen": None, "annee_seche_p10": None, "n_annees": len(serie)}
    return {
        "annuel_moyen": round(mean(serie)),
        "annee_seche_p10": round(quantile(serie, 0.10)),   # P10 ANNUEL reel
        "annee_humide_p90": round(quantile(serie, 0.90)),  # P90 ANNUEL reel
        "n_annees": len(serie),
    }

resultat = {}
for maille, mdata in monthly.items():
    # cumuls mensuels valides (mois quasi complet)
    cumuls = {m: {} for m in range(1, 13)}       # cumuls[mois][annee] = mm
    annees_presentes = set()
    for (year, month), (somme, nb) in mdata.items():
        jours_attendus = calendar.monthrange(year, month)[1]
        if nb >= jours_attendus - MAX_JOURS_MANQUANTS:
            cumuls[month][year] = somme
            annees_presentes.add(year)

    # cumul annuel : seulement les annees dont les 12 mois sont valides
    cumul_annuel = {}
    for a in sorted(annees_presentes):
        if all(a in cumuls[m] for m in range(1, 13)):
            cumul_annuel[a] = sum(cumuls[m][a] for m in range(1, 13))

    toutes = sorted(annees_presentes)
    if not toutes:
        continue
    ref = [a for a in toutes if REF_MIN <= a <= REF_MAX]
    recentes = toutes[-RECENTE_N:]

    # tendance mensuelle (mm/decennie) sur l'historique complet
    tendance = []
    for m in range(1, 13):
        pts = [(a, cumuls[m][a]) for a in toutes if a in cumuls[m]]
        t = theil_sen_per_decade(pts)
        tendance.append(r1(t))

    info = meta_mailles.get(maille, {})
    resultat[maille] = {
        "lambx": info.get("lambx"), "lamby": info.get("lamby"),
        "lat": info.get("lat"), "lon": info.get("lon"),
        "altitude_m": None,  # a renseigner ulterieurement
        "annees_disponibles": [toutes[0], toutes[-1]],
        "fenetres": {
            "historique": {**window_stats(cumuls, toutes), **annual_stats(cumul_annuel, toutes)},
            "ref_1995_2020": {**window_stats(cumuls, ref), **annual_stats(cumul_annuel, ref)},
            "recente": {**window_stats(cumuls, recentes), **annual_stats(cumul_annuel, recentes)},
        },
        "tendance_mm_decennie": tendance,
    }

with open("data/out/normales_corse.json", "w", encoding="utf-8") as out:
    json.dump(resultat, out, ensure_ascii=False)

print("Mailles agregees : %d -> data/out/normales_corse.json" % len(resultat))

# extrait de la maille d'Ajaccio pour la maquette
cible = "11320_16810"
if cible in resultat:
    extrait = {"maille": cible, **resultat[cible]}
    with open("docs/ajaccio.json", "w", encoding="utf-8") as out:
        json.dump(extrait, out, ensure_ascii=False, indent=1)
    print("-> maquette/ajaccio.json ecrit")

if cible in resultat:
    h = resultat[cible]["fenetres"]["historique"]
    print("\nAjaccio (%s) - fenetre historique :" % cible)
    print("  annees     :", resultat[cible]["annees_disponibles"])
    print("  moy mens.  :", h["moy"])
    print("  annuel moy :", h["annuel_moyen"], "mm   annee seche P10 :", h["annee_seche_p10"],
          "  (n=%d ans)" % h["n_annees"])
