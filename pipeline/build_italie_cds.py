"""Pipeline ITALIE via COPERNICUS CDS (telechargement en bloc) — alternative a
Open-Meteo, sans quota par point.

Idee : au lieu d'interroger l'API point par point (bride par le quota Open-Meteo),
on TELECHARGE en une fois la grille ERA5-Land MENSUELLE sur toute l'Italie, puis on
agrege en local — exactement la logique de build_france.py avec les fichiers SAFRAN.

Source : ERA5-Land monthly averaged reanalysis (Copernicus CDS), 0,1 deg.
  Le jeu JOURNALIER 'derived-era5-land-daily-statistics' EXCLUT les variables
  cumulees (pluie, rayonnement) -> on prend donc le MENSUEL, qui les contient.

Variables telechargees (noms CDS) :
  total_precipitation, 2m_temperature, 2m_dewpoint_temperature,
  10m_u_component_of_wind, 10m_v_component_of_wind, surface_solar_radiation_downwards

ET0 : calculee FAO-56 Penman-Monteith (pas la variable 'potential evaporation'
d'ERA5). Pas de temps MENSUEL (methode FAO pour donnees mensuelles). Simplifications
documentees : pas de Tmax/Tmin separes (mensuel -> T moyenne), altitude=0 (z absent
du produit mensuel) -> a affiner. Validee sur l'exemple FAO-56 n°17 (Bangkok=5,72 mm/j).

Etapes :
  python pipeline/build_italie_cds.py --selftest   # teste la formule ET0 (sans CDS)
  python pipeline/build_italie_cds.py --download    # telecharge le NetCDF depuis CDS
  python pipeline/build_italie_cds.py               # agrege -> docs/it/normales_italie.json

Pre-requis CDS (voir le guide donne par Claude) :
  pip install cdsapi xarray netcdf4 numpy
  compte gratuit + fichier ~/.cdsapirc (cle API)

Sortie : docs/it/normales_italie.json (meme schema que la version Open-Meteo).
"""
import json, math, calendar, os, sys
from datetime import date

# ------------------------------------------------------------------ parametres
YEAR0, YEAR1 = 1991, 2025
REF_MIN, REF_MAX = 1995, 2020
RECENTE_N = 15
MIN_ANNEES = 8
# bbox Italie (memes bornes que la version Open-Meteo)
LAT0, LAT1, LON0, LON1 = 35.40, 47.10, 6.60, 18.60
STEP = 0.1

NC_FILE = "data/raw/era5land_italie_monthly.nc"
GEOJSON_CACHE = "data/raw/italie_regions.geojson"   # deja telecharge par build_italie.py
OUT = "docs/it/normales_italie.json"

CDS_DATASET = "reanalysis-era5-land-monthly-means"
CDS_VARS = ["total_precipitation", "2m_temperature", "2m_dewpoint_temperature",
            "10m_u_component_of_wind", "10m_v_component_of_wind",
            "surface_solar_radiation_downwards"]

# ============================================================ FAO-56 Penman-Monteith
# Jour representatif de chaque mois (FAO-56, ~milieu de mois) pour le rayonnement extraterrestre
MID_DOY = [15, 46, 75, 105, 135, 162, 198, 228, 258, 288, 318, 344]

def _esat(t):               # pression de vapeur saturante (kPa), t en degC
    return 0.6108 * math.exp(17.27 * t / (t + 237.3))

def _ra(lat_deg, doy):      # rayonnement extraterrestre Ra (MJ/m2/jour)
    phi = math.radians(lat_deg)
    dr = 1 + 0.033 * math.cos(2 * math.pi / 365 * doy)
    dec = 0.409 * math.sin(2 * math.pi / 365 * doy - 1.39)
    x = -math.tan(phi) * math.tan(dec)
    ws = math.acos(max(-1.0, min(1.0, x)))
    return 24 * 60 / math.pi * 0.0820 * dr * (
        ws * math.sin(phi) * math.sin(dec) + math.cos(phi) * math.cos(dec) * math.sin(ws))

def et0_fao56(lat, elev, month, Tmax, Tmin, ea, u2, Rs, G=0.0):
    """ET0 de reference (mm/jour), FAO-56 Penman-Monteith.
    Tmax/Tmin/Tmean en degC ; ea en kPa ; u2 vent a 2 m (m/s) ; Rs rayonnement
    solaire incident (MJ/m2/jour) ; elev altitude (m). En mensuel : Tmax=Tmin=Tmoy."""
    doy = MID_DOY[month - 1]
    Tmean = (Tmax + Tmin) / 2.0
    es = (_esat(Tmax) + _esat(Tmin)) / 2.0
    delta = 4098 * _esat(Tmean) / (Tmean + 237.3) ** 2
    P = 101.3 * ((293 - 0.0065 * elev) / 293) ** 5.26
    gamma = 0.000665 * P
    Ra = _ra(lat, doy)
    Rso = (0.75 + 2e-5 * elev) * Ra
    Rns = (1 - 0.23) * Rs                              # albedo gazon 0,23
    rel = min(Rs / Rso, 1.0) if Rso > 0 else 0.0
    sb = 4.903e-9                                      # Stefan-Boltzmann (MJ/K4/m2/jour)
    Rnl = sb * ((( Tmax + 273.16) ** 4 + (Tmin + 273.16) ** 4) / 2) \
          * (0.34 - 0.14 * math.sqrt(max(ea, 0))) * (1.35 * rel - 0.35)
    Rn = Rns - Rnl
    num = 0.408 * delta * (Rn - G) + gamma * (900 / (Tmean + 273)) * u2 * (es - ea)
    den = delta + gamma * (1 + 0.34 * u2)
    return num / den

def selftest():
    """Reproduit l'exemple FAO-56 n°17 (Bangkok, avril) -> ET0 attendue ~5,72 mm/jour."""
    lat, elev, month = 13.733, 2.0, 4
    Tmax, Tmin, ea, u2 = 34.8, 25.6, 2.85, 2.0
    # Rs reconstitue depuis la duree d'insolation n=8,5 h (relation d'Angstrom)
    doy = MID_DOY[month - 1]
    Ra = _ra(lat, doy)
    phi = math.radians(lat); dec = 0.409 * math.sin(2 * math.pi / 365 * doy - 1.39)
    ws = math.acos(max(-1, min(1, -math.tan(phi) * math.tan(dec))))
    N = 24 / math.pi * ws
    Rs = (0.25 + 0.50 * 8.5 / N) * Ra
    G = 0.14 * (30.2 - 29.2)                            # eq. 43 (mensuel)
    et0 = et0_fao56(lat, elev, month, Tmax, Tmin, ea, u2, Rs, G)
    print("Ra=%.1f MJ/m2/j  N=%.1f h  Rs=%.1f MJ/m2/j" % (Ra, N, Rs))
    print("ET0 calcule = %.2f mm/jour   (attendu FAO-56 ex.17 : 5,72)" % et0)
    ok = abs(et0 - 5.72) < 0.2
    print("AUTO-TEST FAO-56 :", "OK ✓" if ok else "ECART TROP GRAND ✗")
    return ok

# ============================================================ stats (= build_france.py)
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

# ============================================================ telechargement CDS
def download():
    import cdsapi
    os.makedirs(os.path.dirname(NC_FILE), exist_ok=True)
    if os.path.exists(NC_FILE):
        print("Deja present : %s (supprime-le pour re-telecharger)" % NC_FILE); return
    print("Telechargement ERA5-Land mensuel (peut etre mis en file d'attente cote CDS)...")
    c = cdsapi.Client()
    c.retrieve(CDS_DATASET, {
        "product_type": "monthly_averaged_reanalysis",
        "variable": CDS_VARS,
        "year": [str(y) for y in range(YEAR0, YEAR1 + 1)],
        "month": ["%02d" % m for m in range(1, 13)],
        "time": "00:00",
        "area": [LAT1, LON0, LAT0, LON1],   # Nord, Ouest, Sud, Est
        "data_format": "netcdf",
        "download_format": "unarchived",
    }, NC_FILE)
    print("Ecrit %s" % NC_FILE)

# ============================================================ point-dans-polygone
def _ray(lat, lon, ring):
    inside = False; n = len(ring); j = n - 1
    for i in range(n):
        xi, yi = ring[i][0], ring[i][1]; xj, yj = ring[j][0], ring[j][1]
        if ((yi > lat) != (yj > lat)) and (lon < (xj - xi) * (lat - yi) / (yj - yi) + xi):
            inside = not inside
        j = i
    return inside

def in_polygon(lat, lon, polys):
    for rings in polys:
        if _ray(lat, lon, rings[0]) and not any(_ray(lat, lon, h) for h in rings[1:]):
            return True
    return False

def load_italy_polys():
    gj = json.load(open(GEOJSON_CACHE, encoding="utf-8"))
    polys = []
    for feat in gj.get("features", []):
        g = feat.get("geometry") or {}
        if g.get("type") == "Polygon": polys.append(g["coordinates"])
        elif g.get("type") == "MultiPolygon": polys.extend(g["coordinates"])
    return polys

# ============================================================ agregation
def aggregate():
    import numpy as np, xarray as xr
    if not os.path.exists(NC_FILE):
        print("Manque %s : lance d'abord --download" % NC_FILE); sys.exit(1)
    polys = load_italy_polys()
    ds = xr.open_dataset(NC_FILE)

    # noms possibles selon la version du produit
    def pick(*names):
        for n in names:
            if n in ds: return ds[n]
        raise KeyError("variable absente : " + "/".join(names))
    tp  = pick("tp")                       # m (cumul journalier moyen du mois)
    t2m = pick("t2m"); d2m = pick("d2m")   # K
    u10 = pick("u10"); v10 = pick("v10")   # m/s
    ssrd = pick("ssrd")                    # J/m2 (cumul journalier moyen du mois)
    latname = "latitude" if "latitude" in ds.coords else "lat"
    lonname = "longitude" if "longitude" in ds.coords else "lon"
    timename = [c for c in ("valid_time", "time") if c in ds.coords][0]
    lats = ds[latname].values; lons = ds[lonname].values
    times = ds[timename].values
    years = np.array([int(str(t)[:4]) for t in np.datetime_as_string(times)])
    months = np.array([int(str(t)[5:7]) for t in np.datetime_as_string(times)])

    # pre-charge les cubes en numpy (time, lat, lon)
    TP, T2, D2, U, V, SS = (v.values for v in (tp, t2m, d2m, u10, v10, ssrd))

    resultat = {}
    n_cells = 0
    for iy, la in enumerate(lats):
        for ix, lo in enumerate(lons):
            if not in_polygon(float(la), float(lo), polys):
                continue
            n_cells += 1
            # series mensuelles par annee
            cumuls = {m: {} for m in range(1, 13)}       # precip mensuelle (mm)
            cumuls_et0 = {m: {} for m in range(1, 13)}   # ET0 mensuelle (mm)
            for k in range(len(times)):
                y = int(years[k]); m = int(months[k])
                if y < YEAR0 or y > YEAR1: continue
                tp_k, t2_k = float(TP[k, iy, ix]), float(T2[k, iy, ix])
                d2_k, u_k, v_k, ss_k = (float(D2[k, iy, ix]), float(U[k, iy, ix]),
                                        float(V[k, iy, ix]), float(SS[k, iy, ix]))
                # ERA5-Land est masque en mer -> NaN : on ignore le mois sans donnee
                if any(math.isnan(x) for x in (tp_k, t2_k, d2_k, u_k, v_k, ss_k)):
                    continue
                ndays = calendar.monthrange(y, m)[1]
                precip_mm = tp_k * 1000.0 * ndays                    # m/j -> mm/mois
                Tmean = t2_k - 273.15
                ea = _esat(d2_k - 273.15)
                u2 = math.hypot(u_k, v_k) * 0.748                    # 10 m -> 2 m
                Rs = ss_k / 1e6                                      # J/m2/j -> MJ/m2/j
                et0_day = et0_fao56(float(la), 0.0, m, Tmean, Tmean, ea, u2, Rs)
                cumuls[m][y] = precip_mm
                cumuls_et0[m][y] = max(0.0, et0_day) * ndays

            annees = sorted({y for m in range(1, 13) for y in cumuls[m]})
            if len([a for a in annees if all(a in cumuls[m] for m in range(1, 13))]) < MIN_ANNEES:
                continue
            cumul_annuel = {a: sum(cumuls[m][a] for m in range(1, 13))
                            for a in annees if all(a in cumuls[m] for m in range(1, 13))}
            ref = [a for a in annees if REF_MIN <= a <= REF_MAX]
            recentes = annees[-RECENTE_N:]

            def wstats(yrs):
                moy, med, p10, p90 = [], [], [], []
                for m in range(1, 13):
                    s = [cumuls[m][a] for a in yrs if a in cumuls[m]]
                    if len(s) >= MIN_ANNEES:
                        moy.append(r1(mean(s))); med.append(r1(quantile(s, 0.5)))
                        p10.append(r1(quantile(s, 0.10))); p90.append(r1(quantile(s, 0.90)))
                    else:
                        moy.append(None); med.append(None); p10.append(None); p90.append(None)
                return {"moy": moy, "med": med, "p10": p10, "p90": p90}

            def wet0(yrs):
                out = []
                for m in range(1, 13):
                    s = [cumuls_et0[m][a] for a in yrs if a in cumuls_et0[m]]
                    out.append(r1(mean(s)) if len(s) >= MIN_ANNEES else None)
                return out

            def astats(yrs):
                s = [cumul_annuel[a] for a in yrs if a in cumul_annuel]
                if len(s) < MIN_ANNEES:
                    return {"annuel_moyen": None, "annee_seche_p10": None,
                            "annee_humide_p90": None, "n_annees": len(s)}
                return {"annuel_moyen": round(mean(s)),
                        "annee_seche_p10": round(quantile(s, 0.10)),
                        "annee_humide_p90": round(quantile(s, 0.90)), "n_annees": len(s)}

            tendance = []
            for m in range(1, 13):
                pts = [(a, cumuls[m][a]) for a in annees if a in cumuls[m]]
                tendance.append(r1(theil_sen_per_decade(pts)))

            key = "%d_%d" % (round(float(la) * 1000), round(float(lo) * 1000))
            resultat[key] = {
                "lat": round(float(la), 3), "lon": round(float(lo), 3), "altitude_m": None,
                "commune": None, "departement": None, "insee": None,
                "annees_disponibles": [annees[0], annees[-1]],
                "fenetres": {
                    "ref_1995_2020": {**wstats(ref), **astats(ref), "et0_moy": wet0(ref)},
                    "recente": {**wstats(recentes), **astats(recentes), "et0_moy": wet0(recentes)},
                },
                "tendance_mm_decennie": tendance,
            }

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump(resultat, open(OUT, "w", encoding="utf-8"), ensure_ascii=False)
    print("Cellules dans la grille bbox : (terrestres Italie) %d" % n_cells)
    print("Ecrit %s : %d points" % (OUT, len(resultat)))
    # controle de bon sens sur quelques villes
    for nom, key in (("Roma", "41900_12500"), ("Milano", "45500_9200"), ("Palermo", "38100_13400")):
        if key in resultat:
            f = resultat[key]["fenetres"]["ref_1995_2020"]
            print("  %-8s pluie/an=%s mm  ET0 juil=%s mm" % (nom, f["annuel_moyen"], f["et0_moy"][6]))

# ============================================================ programme
if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(0 if selftest() else 1)
    elif "--download" in sys.argv:
        download()
    else:
        aggregate()
