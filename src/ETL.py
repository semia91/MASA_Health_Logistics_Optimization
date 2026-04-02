"""
ETL pipeline : construction du dataset des infrastructures de sante du Ghana.
Sources : OSM Overpass, HDX Healthsites CSV, HDX HOT GeoJSON.
Croisement, normalisation, scoring de confiance, export.
"""
import sys
import io
import os
import time
import json
import zipfile
import logging
from pathlib import Path

import requests
import numpy as np
import pandas as pd

# Chemin absolu vers la racine du repo
REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_RAW = REPO_ROOT / "data" / "raw"
DATA_PROCESSED = REPO_ROOT / "data" / "processed"

OVERPASS_URL = "https://overpass-api.de/api/interpreter"

# Bbox Ghana (filtrage final)
GH_LAT_MIN, GH_LAT_MAX = 4.5, 11.5
GH_LON_MIN, GH_LON_MAX = -3.5, 1.5

log = logging.getLogger(__name__)


# =========================================================================
# Utilitaires
# =========================================================================

def _haversine_km(lat1, lon1, lat2, lon2):
    import math
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2
         + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2))
         * math.sin(dlon / 2) ** 2)
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _haversine_matrix(lats1, lons1, lats2, lons2):
    R = 6371.0
    lat1 = np.radians(lats1)
    lat2 = np.radians(lats2)
    dlat = lat2 - lat1
    dlon = np.radians(lons2) - np.radians(lons1)
    a = np.sin(dlat / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin(dlon / 2) ** 2
    return R * 2 * np.arctan2(np.sqrt(a), np.sqrt(1 - a))


def _overpass_query(query: str, label: str = "data") -> list:
    for attempt in range(3):
        try:
            print(f"    Overpass ({label}) tentative {attempt + 1}/3...")
            resp = requests.post(OVERPASS_URL, data={"data": query}, timeout=360)
            resp.raise_for_status()
            return resp.json().get("elements", [])
        except Exception as e:
            print(f"    Erreur : {e}")
            if attempt < 2:
                time.sleep(30)
    return []


# =========================================================================
# ETAPE 1 : Extraction OSM Overpass
# =========================================================================

def extract_osm_facilities() -> pd.DataFrame:
    print("\n  [SOURCE 1/3] OSM Overpass API")
    print("  " + "-" * 50)

    query = """
[out:json][timeout:300];
area["ISO3166-1"="GH"]->.ghana;
(
  node["amenity"="hospital"](area.ghana);
  node["amenity"="clinic"](area.ghana);
  node["amenity"="pharmacy"](area.ghana);
  node["amenity"="doctors"](area.ghana);
  node["amenity"="dentist"](area.ghana);
  node["amenity"="health_post"](area.ghana);
  node["healthcare"](area.ghana);
  way["amenity"="hospital"](area.ghana);
  way["amenity"="clinic"](area.ghana);
  way["amenity"="pharmacy"](area.ghana);
  way["healthcare"](area.ghana);
);
out center body;
"""
    elements = _overpass_query(query, "health facilities Ghana")
    print(f"    Elements bruts : {len(elements)}")

    records = []
    seen_coords = set()
    for el in elements:
        lat = el.get("lat") or el.get("center", {}).get("lat")
        lon = el.get("lon") or el.get("center", {}).get("lon")
        if not lat or not lon:
            continue

        coord_key = (round(lat, 5), round(lon, 5))
        if coord_key in seen_coords:
            continue
        seen_coords.add(coord_key)

        tags = el.get("tags", {})
        records.append({
            "osm_id": str(el.get("id", "")),
            "name": tags.get("name", ""),
            "amenity_tag": tags.get("amenity", ""),
            "healthcare_tag": tags.get("healthcare", ""),
            "operator": tags.get("operator", ""),
            "latitude": lat,
            "longitude": lon,
            "source": "OSM",
        })

    df = pd.DataFrame(records)
    print(f"    Apres deduplication coords : {len(df)} facilities")
    print(f"    Avec nom : {(df['name'] != '').sum()}")
    print(f"    Sans nom : {(df['name'] == '').sum()}")
    return df


# =========================================================================
# ETAPE 2 : Extraction HDX Healthsites CSV
# =========================================================================

def extract_healthsites_csv() -> pd.DataFrame:
    print("\n  [SOURCE 2/3] HDX Healthsites CSV")
    print("  " + "-" * 50)

    url = ("https://data.humdata.org/dataset/"
           "364c5aca-7cd7-4248-b394-335113293c7a/resource/"
           "a67daf24-9df4-4df6-b980-def3274d1b70/download/ghana.csv")

    print("    Telechargement...")
    try:
        resp = requests.get(url, timeout=120, allow_redirects=True)
        resp.raise_for_status()
    except Exception as e:
        print(f"    ERREUR telechargement: {e}")
        return pd.DataFrame()

    raw = pd.read_csv(io.StringIO(resp.text))
    print(f"    Lignes brutes : {len(raw)}")
    print(f"    Colonnes : {list(raw.columns)}")

    # Identifier les colonnes de coordonnees
    lat_col = None
    lon_col = None
    for c in raw.columns:
        cl = c.lower().strip()
        if cl in ("y", "lat", "latitude"):
            lat_col = c
        if cl in ("x", "lon", "long", "longitude"):
            lon_col = c

    if lat_col is None or lon_col is None:
        # Chercher dans les colonnes avec "geometry" ou "point"
        print(f"    ATTENTION : colonnes lat/lon non trouvees parmi {list(raw.columns)}")
        print(f"    Tentative avec les 2 premieres colonnes numeriques...")
        num_cols = raw.select_dtypes(include=[np.number]).columns
        if len(num_cols) >= 2:
            lon_col, lat_col = num_cols[0], num_cols[1]
        else:
            print("    ECHEC : impossible d'identifier les coordonnees.")
            return pd.DataFrame()

    print(f"    Colonnes detectees : lat={lat_col}, lon={lon_col}")

    # Mapper vers un schema commun
    records = []
    for _, row in raw.iterrows():
        lat = row.get(lat_col)
        lon = row.get(lon_col)
        if pd.isna(lat) or pd.isna(lon):
            continue

        name = ""
        for nc in ["name", "Name", "NAME", "name_en"]:
            if nc in raw.columns and pd.notna(row.get(nc)):
                name = str(row.get(nc))
                break

        amenity = ""
        for ac in ["amenity", "Amenity", "AMENITY"]:
            if ac in raw.columns and pd.notna(row.get(ac)):
                amenity = str(row.get(ac))
                break

        healthcare = ""
        for hc in ["healthcare", "Healthcare", "HEALTHCARE"]:
            if hc in raw.columns and pd.notna(row.get(hc)):
                healthcare = str(row.get(hc))
                break

        osm_id = ""
        for oc in ["osm_id", "OSM_ID", "osm_ID"]:
            if oc in raw.columns and pd.notna(row.get(oc)):
                osm_id = str(int(row.get(oc))) if isinstance(row.get(oc), float) else str(row.get(oc))
                break

        operator = ""
        for opc in ["operator", "Operator"]:
            if opc in raw.columns and pd.notna(row.get(opc)):
                operator = str(row.get(opc))
                break

        completeness = 0.0
        for cc in ["completeness", "Completeness"]:
            if cc in raw.columns and pd.notna(row.get(cc)):
                try:
                    completeness = float(row.get(cc))
                except (ValueError, TypeError):
                    pass
                break

        records.append({
            "osm_id": osm_id,
            "name": name,
            "amenity_tag": amenity,
            "healthcare_tag": healthcare,
            "operator": operator,
            "latitude": float(lat),
            "longitude": float(lon),
            "completeness": completeness,
            "source": "healthsites",
        })

    df = pd.DataFrame(records)
    # Filtrer hors bbox Ghana
    df = df[(df["latitude"] >= GH_LAT_MIN) & (df["latitude"] <= GH_LAT_MAX) &
            (df["longitude"] >= GH_LON_MIN) & (df["longitude"] <= GH_LON_MAX)]
    print(f"    Apres filtrage bbox Ghana : {len(df)} facilities")
    print(f"    Avec nom : {(df['name'] != '').sum()}")
    return df


# =========================================================================
# ETAPE 3 : Extraction HDX HOT GeoJSON
# =========================================================================

def extract_hdx_hot_geojson() -> pd.DataFrame:
    print("\n  [SOURCE 3/3] HDX HOT GeoJSON Export")
    print("  " + "-" * 50)

    url = ("https://s3.dualstack.us-east-1.amazonaws.com/"
           "production-raw-data-api/ISO3/GHA/health_facilities/"
           "points/hotosm_gha_health_facilities_points_geojson.zip")

    print("    Telechargement du zip GeoJSON...")
    try:
        resp = requests.get(url, timeout=120)
        resp.raise_for_status()
    except Exception as e:
        print(f"    ERREUR telechargement: {e}")
        return pd.DataFrame()

    print(f"    Taille : {len(resp.content) / 1024:.0f} Ko")

    # Extraire et parser le GeoJSON
    try:
        zf = zipfile.ZipFile(io.BytesIO(resp.content))
        geojson_name = [n for n in zf.namelist() if n.endswith(".geojson") or n.endswith(".json")]
        if not geojson_name:
            print(f"    Fichiers dans le zip : {zf.namelist()}")
            print("    Pas de GeoJSON trouve dans le zip.")
            return pd.DataFrame()

        with zf.open(geojson_name[0]) as f:
            data = json.load(f)
    except Exception as e:
        print(f"    ERREUR parsing: {e}")
        return pd.DataFrame()

    features = data.get("features", [])
    print(f"    Features GeoJSON : {len(features)}")

    records = []
    for feat in features:
        geom = feat.get("geometry", {})
        props = feat.get("properties", {})
        coords = geom.get("coordinates", [])
        if not coords or len(coords) < 2:
            continue

        lon, lat = coords[0], coords[1]
        osm_id = str(props.get("osm_id", props.get("@id", "")))

        records.append({
            "osm_id": osm_id,
            "name": props.get("name", "") or "",
            "amenity_tag": props.get("amenity", "") or "",
            "healthcare_tag": props.get("healthcare", "") or "",
            "operator": props.get("operator", "") or "",
            "latitude": lat,
            "longitude": lon,
            "source": "HDX",
        })

    df = pd.DataFrame(records)
    df = df[(df["latitude"] >= GH_LAT_MIN) & (df["latitude"] <= GH_LAT_MAX) &
            (df["longitude"] >= GH_LON_MIN) & (df["longitude"] <= GH_LON_MAX)]
    print(f"    Apres filtrage bbox Ghana : {len(df)} facilities")
    print(f"    Avec nom : {(df['name'] != '').sum()}")
    return df


# =========================================================================
# ETAPE 4 : Normalisation du type de facility
# =========================================================================

TYPE_PRIORITY = [
    "Hospital", "Health_Center", "Clinic", "CHPS",
    "Health_Post", "Pharmacy", "Doctor", "Laboratory", "Other"
]

def standardize_facility_type(amenity: str, healthcare: str, name: str) -> str:
    amenity = (amenity or "").lower().strip()
    healthcare = (healthcare or "").lower().strip()
    name_low = (name or "").lower().strip()

    # Priorite 1 : tags OSM
    if amenity == "hospital":
        return "Hospital"
    if amenity == "clinic":
        return "Clinic"
    if amenity == "pharmacy":
        return "Pharmacy"
    if amenity in ("doctors", "dentist"):
        return "Doctor"
    if amenity == "health_post":
        return "Health_Post"

    if healthcare == "hospital":
        return "Hospital"
    if healthcare in ("centre", "center"):
        return "Health_Center"
    if healthcare == "clinic":
        return "Clinic"
    if healthcare == "pharmacy":
        return "Pharmacy"
    if healthcare == "laboratory":
        return "Laboratory"
    if healthcare in ("health_post", "birthing_centre"):
        return "Health_Post"
    if healthcare in ("doctor", "doctors", "dentist"):
        return "Doctor"

    # Priorite 2 : patterns dans le nom
    if "hospital" in name_low:
        return "Hospital"
    if "health cent" in name_low or "health-cent" in name_low:
        return "Health_Center"
    if "chps" in name_low or "community health" in name_low:
        return "CHPS"
    if "clinic" in name_low or "polyclinic" in name_low:
        return "Clinic"
    if "pharmacy" in name_low or "drug" in name_low or "chemical" in name_low:
        return "Pharmacy"
    if "health post" in name_low:
        return "Health_Post"
    if "lab" in name_low and "laboratory" in name_low:
        return "Laboratory"
    if "maternity" in name_low:
        return "Health_Center"

    # healthcare=yes ou autre
    if healthcare and healthcare != "yes":
        return "Other"

    return "Other"


# =========================================================================
# ETAPE 5 : Croisement par osm_id + proximite
# =========================================================================

def cross_validate_facilities(
    dfs: list[pd.DataFrame],
    threshold_km: float = 0.2,
) -> pd.DataFrame:
    print("\n  CROISEMENT MULTI-SOURCE")
    print("  " + "-" * 50)

    if not dfs:
        return pd.DataFrame()

    # Trier par taille decroissante, la plus grande = base
    dfs_sorted = sorted(dfs, key=len, reverse=True)
    base = dfs_sorted[0].copy()
    base["data_sources"] = base["source"]
    base["nb_sources"] = 1

    if "completeness" not in base.columns:
        base["completeness"] = 0.0

    for i, new_df in enumerate(dfs_sorted[1:], start=2):
        source_name = new_df["source"].iloc[0] if len(new_df) > 0 else f"source_{i}"
        print(f"\n    Croisement avec {source_name} ({len(new_df)} facilities)...")

        if len(new_df) == 0:
            continue

        if "completeness" not in new_df.columns:
            new_df = new_df.copy()
            new_df["completeness"] = 0.0

        # Phase 1 : match par osm_id (le plus fiable)
        base_ids = set(base["osm_id"].dropna().unique()) - {"", "nan"}
        new_ids = set(new_df["osm_id"].dropna().unique()) - {"", "nan"}
        common_ids = base_ids & new_ids
        print(f"      Match osm_id : {len(common_ids)} facilities communes")

        matched_new_idx = set()
        for osm_id in common_ids:
            base_row = base[base["osm_id"] == osm_id].index[0]
            new_row = new_df[new_df["osm_id"] == osm_id].iloc[0]
            matched_new_idx.add(new_df[new_df["osm_id"] == osm_id].index[0])

            # Merger attributs
            _merge_attributes(base, base_row, new_row, source_name)

        # Phase 2 : match par proximite pour les non-matches
        unmatched = new_df[~new_df.index.isin(matched_new_idx)]
        if len(unmatched) > 0 and len(base) > 0:
            print(f"      Match proximite (<{threshold_km*1000:.0f}m) pour {len(unmatched)} restants...")

            base_lats = base["latitude"].values
            base_lons = base["longitude"].values
            new_lats = unmatched["latitude"].values
            new_lons = unmatched["longitude"].values

            # Matrice de distances (N_base x N_new)
            dist_matrix = _haversine_matrix(
                base_lats[:, None], base_lons[:, None],
                new_lats[None, :], new_lons[None, :]
            )

            min_dists = dist_matrix.min(axis=0)
            closest_idx = dist_matrix.argmin(axis=0)
            matched_mask = min_dists < threshold_km

            prox_matched = 0
            prox_added = 0

            for j, (new_idx, row) in enumerate(unmatched.iterrows()):
                if matched_mask[j]:
                    base_idx = base.index[closest_idx[j]]
                    _merge_attributes(base, base_idx, row, source_name)
                    prox_matched += 1
                else:
                    # Nouvelle facility inconnue de la base
                    new_entry = row.to_dict()
                    new_entry["data_sources"] = source_name
                    new_entry["nb_sources"] = 1
                    new_entry.setdefault("completeness", 0.0)
                    base = pd.concat([base, pd.DataFrame([new_entry])], ignore_index=True)
                    prox_added += 1

            print(f"      Proximite : {prox_matched} matches, {prox_added} nouvelles")

    print(f"\n    TOTAL apres croisement : {len(base)} facilities uniques")
    return base


def _merge_attributes(base_df, base_idx, new_row, source_name):
    current_name = base_df.at[base_idx, "name"]
    new_name = new_row.get("name", "")

    # Preferer le nom le plus specifique
    if (not current_name or current_name in ("", "Unknown Facility", "Clinic")) and new_name:
        base_df.at[base_idx, "name"] = new_name

    # Enrichir operator si absent
    if not base_df.at[base_idx, "operator"] and new_row.get("operator"):
        base_df.at[base_idx, "operator"] = new_row["operator"]

    # Enrichir tags si absents
    if not base_df.at[base_idx, "amenity_tag"] and new_row.get("amenity_tag"):
        base_df.at[base_idx, "amenity_tag"] = new_row["amenity_tag"]
    if not base_df.at[base_idx, "healthcare_tag"] and new_row.get("healthcare_tag"):
        base_df.at[base_idx, "healthcare_tag"] = new_row["healthcare_tag"]

    # Completeness : garder le max
    new_compl = new_row.get("completeness", 0.0) or 0.0
    old_compl = base_df.at[base_idx, "completeness"] or 0.0
    base_df.at[base_idx, "completeness"] = max(old_compl, new_compl)

    # Mettre a jour les sources
    sources = str(base_df.at[base_idx, "data_sources"])
    if source_name not in sources:
        base_df.at[base_idx, "data_sources"] = sources + "," + source_name
    base_df.at[base_idx, "nb_sources"] = base_df.at[base_idx, "nb_sources"] + 1


# =========================================================================
# ETAPE 7 : Score de confiance
# =========================================================================

def compute_confidence(row, max_sources: int = 3) -> float:
    nb = min(row.get("nb_sources", 1), max_sources)
    has_name = 1.0 if row.get("name") and row["name"] not in ("", "Unknown Facility") else 0.0
    has_type = 1.0 if row.get("Facility_Type") and row["Facility_Type"] != "Other" else 0.0
    has_operator = 1.0 if row.get("operator") and row["operator"] != "" else 0.0
    completeness = min((row.get("completeness", 0) or 0) / 100.0, 1.0)

    return round(
        0.40 * (nb / max_sources)
        + 0.20 * has_name
        + 0.20 * has_type
        + 0.10 * has_operator
        + 0.10 * completeness,
        2,
    )


# =========================================================================
# ETAPE 8 : Pipeline complet
# =========================================================================

def build_facility_dataset(save_intermediates: bool = True) -> pd.DataFrame:
    print("=" * 65)
    print("CONSTRUCTION DU DATASET INFRASTRUCTURES DE SANTE — GHANA")
    print("=" * 65)

    # Extractions
    df_osm = extract_osm_facilities()
    df_healthsites = extract_healthsites_csv()
    df_hdx = extract_hdx_hot_geojson()

    # Sauvegarder les intermediaires
    if save_intermediates:
        DATA_RAW.mkdir(parents=True, exist_ok=True)
        if len(df_osm) > 0:
            df_osm.to_csv(DATA_RAW / "osm_facilities_raw.csv", index=False)
        if len(df_healthsites) > 0:
            df_healthsites.to_csv(DATA_RAW / "healthsites_facilities_raw.csv", index=False)
        if len(df_hdx) > 0:
            df_hdx.to_csv(DATA_RAW / "hdx_hot_facilities_raw.csv", index=False)
        print("\n  Fichiers intermediaires sauvegardes dans data/raw/")

    # Stats par source
    sources = [
        ("OSM Overpass", df_osm),
        ("HDX Healthsites", df_healthsites),
        ("HDX HOT", df_hdx),
    ]
    print("\n  RECAP PAR SOURCE :")
    for name, df in sources:
        if len(df) > 0:
            named = (df["name"] != "").sum()
            print(f"    {name:20s} : {len(df):5d} facilities ({named} avec nom)")
        else:
            print(f"    {name:20s} : ECHEC ou vide")

    # Croisement
    valid_dfs = [df for _, df in sources if len(df) > 0]
    merged = cross_validate_facilities(valid_dfs, threshold_km=0.2)

    if len(merged) == 0:
        print("  ERREUR : aucune facility extraite.")
        return pd.DataFrame()

    # Normalisation des types
    print("\n  NORMALISATION DES TYPES")
    print("  " + "-" * 50)
    merged["Facility_Type"] = merged.apply(
        lambda r: standardize_facility_type(
            r.get("amenity_tag", ""),
            r.get("healthcare_tag", ""),
            r.get("name", ""),
        ),
        axis=1,
    )
    print("    Distribution des types :")
    type_dist = merged["Facility_Type"].value_counts()
    for t, c in type_dist.items():
        print(f"      {t:>15s} : {c}")

    # Score de confiance
    print("\n  SCORING DE CONFIANCE")
    print("  " + "-" * 50)
    merged["Confidence_Score"] = merged.apply(compute_confidence, axis=1)
    print(f"    Moyenne : {merged['Confidence_Score'].mean():.2f}")
    print(f"    Min     : {merged['Confidence_Score'].min():.2f}")
    print(f"    Max     : {merged['Confidence_Score'].max():.2f}")

    # Nettoyage final
    print("\n  NETTOYAGE FINAL")
    print("  " + "-" * 50)
    before = len(merged)
    # Bbox Ghana
    merged = merged[
        (merged["latitude"] >= GH_LAT_MIN) & (merged["latitude"] <= GH_LAT_MAX) &
        (merged["longitude"] >= GH_LON_MIN) & (merged["longitude"] <= GH_LON_MAX)
    ]
    print(f"    Apres bbox Ghana : {len(merged)} (supprime {before - len(merged)})")

    # Doublons exacts de coordonnees
    before = len(merged)
    merged = merged.drop_duplicates(subset=["latitude", "longitude"], keep="first")
    print(f"    Apres deduplications coords : {len(merged)} (supprime {before - len(merged)})")

    # Renommer / nettoyer les noms
    merged["name"] = merged["name"].fillna("").replace("", "Unnamed Facility")
    mask_unnamed = merged["name"].isin(["", "Unnamed Facility"])
    merged.loc[mask_unnamed, "name"] = (
        "Unnamed " + merged.loc[mask_unnamed, "Facility_Type"]
    )

    # Formater les colonnes finales
    final = merged[[
        "name", "Facility_Type", "latitude", "longitude",
        "data_sources", "Confidence_Score", "osm_id", "operator",
    ]].copy()
    final.columns = [
        "Facility_Name", "Facility_Type", "Latitude", "Longitude",
        "Data_Sources", "Confidence_Score", "OSM_ID", "Operator",
    ]

    # Trier
    final = final.sort_values(["Facility_Type", "Facility_Name"]).reset_index(drop=True)

    # Sauvegarder
    DATA_PROCESSED.mkdir(parents=True, exist_ok=True)
    output_path = DATA_PROCESSED / "ghana_health_facilities.csv"
    final.to_csv(output_path, index=False, encoding="utf-8-sig")

    print(f"\n  CSV FINAL : {output_path}")
    print(f"  {len(final)} infrastructures de sante")

    return final


# =========================================================================
# ETAPE 9 : Verification
# =========================================================================

def verify_dataset(df: pd.DataFrame):
    print("\n" + "=" * 65)
    print("VERIFICATION DU DATASET")
    print("=" * 65)

    print(f"\n  Total facilities : {len(df)}")
    print(f"  Colonnes : {list(df.columns)}")

    # Couverture
    print(f"\n  Couverture des colonnes :")
    for col in df.columns:
        filled = df[col].notna().sum()
        non_empty = (df[col].astype(str) != "").sum()
        print(f"    {col:25s} : {non_empty:5d} / {len(df)}")

    # Distribution types
    print(f"\n  Distribution Facility_Type :")
    for t, c in df["Facility_Type"].value_counts().items():
        pct = 100 * c / len(df)
        print(f"    {t:>15s} : {c:5d} ({pct:.1f}%)")

    # Verification : 0 type "Yes"
    yes_count = (df["Facility_Type"] == "Yes").sum()
    print(f"\n  Facility_Type='Yes' : {yes_count} {'OK' if yes_count == 0 else 'PROBLEME'}")

    # Unnamed
    unnamed = df["Facility_Name"].str.contains("Unnamed", case=False, na=False).sum()
    unnamed_pct = 100 * unnamed / len(df)
    print(f"  Facilities sans nom : {unnamed} ({unnamed_pct:.1f}%) {'OK' if unnamed_pct < 5 else 'ATTENTION'}")

    # Doublons coords
    dupes = df.duplicated(subset=["Latitude", "Longitude"]).sum()
    print(f"  Doublons coordonnees : {dupes} {'OK' if dupes == 0 else 'PROBLEME'}")

    # Distribution confiance
    print(f"\n  Score de confiance :")
    print(f"    Min    : {df['Confidence_Score'].min():.2f}")
    print(f"    Q1     : {df['Confidence_Score'].quantile(0.25):.2f}")
    print(f"    Median : {df['Confidence_Score'].median():.2f}")
    print(f"    Mean   : {df['Confidence_Score'].mean():.2f}")
    print(f"    Q3     : {df['Confidence_Score'].quantile(0.75):.2f}")
    print(f"    Max    : {df['Confidence_Score'].max():.2f}")

    # Sources
    print(f"\n  Provenance :")
    for src in ["OSM", "healthsites", "HDX"]:
        count = df["Data_Sources"].str.contains(src, na=False).sum()
        print(f"    Confirme par {src:>12s} : {count:5d} ({100*count/len(df):.1f}%)")

    multi = (df["Data_Sources"].str.count(",") >= 1).sum()
    print(f"    Multi-source (2+)    : {multi:5d} ({100*multi/len(df):.1f}%)")

    # Comparaison avec l'ancien dataset
    old_csv = (Path(__file__).resolve().parent.parent.parent
               / "ghana_villages_health_dataset.csv")
    if old_csv.exists():
        print(f"\n  Comparaison avec l'ancien dataset villages :")
        old_df = pd.read_csv(old_csv)
        old_facilities = old_df.drop_duplicates(
            subset=["Facility_Latitude", "Facility_Longitude"]
        )
        print(f"    Ancien : {len(old_facilities)} facilities uniques")

        # Pour chaque ancienne facility, trouver la plus proche dans le nouveau
        matched = 0
        for _, row in old_facilities.iterrows():
            olat = row["Facility_Latitude"]
            olon = row["Facility_Longitude"]
            dists = df.apply(
                lambda r: _haversine_km(olat, olon, r["Latitude"], r["Longitude"]),
                axis=1,
            )
            if dists.min() < 0.2:
                matched += 1

        print(f"    Retrouvees dans nouveau dataset (<200m) : {matched} / {len(old_facilities)}")
        print(f"    Taux : {100*matched/len(old_facilities):.1f}%")

    # Apercu
    print(f"\n  TOP 20 hopitaux (par confiance) :")
    hospitals = df[df["Facility_Type"] == "Hospital"].nlargest(20, "Confidence_Score")
    print(hospitals[["Facility_Name", "Latitude", "Longitude",
                     "Confidence_Score", "Data_Sources"]].to_string(index=False))


# =========================================================================
# Point d'entree
# =========================================================================

if __name__ == "__main__":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    df = build_facility_dataset()
    if len(df) > 0:
        verify_dataset(df)
