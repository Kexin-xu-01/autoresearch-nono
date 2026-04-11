#!/usr/bin/env python3
"""
prepare_ibd.py

Download and prepare IBD-relevant pathology/clinical text for autoresearch.

Data sources (both CC BY 4.0 — commercial and open-source use permitted):
  1. TCGA-Reports (Kefeli et al., 2024)
     9,523 surgical pathology reports; GI tract reports (COAD/READ) included.
     https://data.mendeley.com/datasets/hyg5xkznpx/1
  2. MultiCaRe (Bitterman et al., 2023)
     96,000+ PMC open-access clinical case reports, filtered for IBD.
     https://zenodo.org/records/10079370

Output: ~/.cache/autoresearch/data/ — train + val parquet shards
  shard_00000.parquet  (train)
  shard_06542.parquet  (pinned val — must match VAL_SHARD in prepare.py)

After running this script, run:
  uv run prepare.py   # trains BPE tokenizer on the new data

Usage:
  uv run prepare_ibd.py
"""

import io
import json
import os
import random
import sys
import zipfile
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import requests

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

CACHE_DIR = Path.home() / ".cache" / "autoresearch"
DATA_DIR = CACHE_DIR / "data"
RAW_DIR = CACHE_DIR / "ibd_raw"
VAL_SHARD_IDX = 6542   # must match VAL_SHARD in prepare.py
VAL_FRACTION = 0.10    # 10% held out for validation
DOCS_PER_SHARD = 5000  # max documents per train shard

IBD_KEYWORDS = [
    "inflammatory bowel disease",
    "crohn's disease", "crohn disease", "crohns disease",
    "ulcerative colitis",
    "indeterminate colitis",
    " ibd ",
    "ileocolitis",
    "proctocolitis",
    "pouchitis",
    "ileitis",
    "colitis",
]

# ---------------------------------------------------------------------------
# Download helpers
# ---------------------------------------------------------------------------

def download_file(url, dest, desc=""):
    """Download url → dest, with MB progress. Skip if dest already exists."""
    if dest.exists():
        print(f"  Cached: {dest.name}")
        return
    print(f"  Downloading {desc or dest.name} ...")
    r = requests.get(url, stream=True, timeout=120)
    r.raise_for_status()
    total = int(r.headers.get("content-length", 0))
    downloaded = 0
    tmp = dest.with_suffix(dest.suffix + ".tmp")
    with open(tmp, "wb") as f:
        for chunk in r.iter_content(chunk_size=1024 * 1024):
            if chunk:
                f.write(chunk)
                downloaded += len(chunk)
                if total:
                    pct = 100 * downloaded / total
                    print(f"\r    {downloaded / 1e6:.1f} / {total / 1e6:.1f} MB  ({pct:.0f}%)",
                          end="", flush=True)
    print()
    tmp.rename(dest)


# ---------------------------------------------------------------------------
# Source 1: TCGA-Reports (Mendeley Data, CC BY 4.0)
# ---------------------------------------------------------------------------

MENDELEY_DATASET_ID = "hyg5xkznpx"
MENDELEY_API = f"https://data.mendeley.com/api/datasets/{MENDELEY_DATASET_ID}"

def fetch_tcga_reports():
    print("\n=== Source 1: TCGA-Reports (Mendeley Data, CC BY 4.0) ===")
    dest_dir = RAW_DIR / "tcga"
    dest_dir.mkdir(parents=True, exist_ok=True)

    # Discover files via Mendeley Data public API
    print("  Querying Mendeley Data API ...")
    try:
        r = requests.get(MENDELEY_API, timeout=30)
        r.raise_for_status()
        meta = r.json()
    except Exception as e:
        print(f"  ERROR: could not reach Mendeley API: {e}")
        print("  Manual fallback: download the dataset from")
        print(f"  https://data.mendeley.com/datasets/{MENDELEY_DATASET_ID}/1")
        print(f"  and place CSV/ZIP files in {dest_dir}")
        return _load_tcga_from_dir(dest_dir)

    # Mendeley Data API v2: top-level "data" list, or nested under "versions"
    files = (meta.get("data")
             or meta.get("files")
             or next((v.get("files", []) for v in reversed(meta.get("versions", []))), []))

    if not files:
        print("  WARNING: no files found in Mendeley API response.")
        print(f"  Keys in response: {list(meta.keys())}")
        return _load_tcga_from_dir(dest_dir)

    print(f"  Found {len(files)} file(s)")
    for f in files:
        fname = f.get("filename", f.get("name", ""))
        if not fname:
            continue
        # Only download data files, skip images/READMEs
        if not any(fname.lower().endswith(ext) for ext in (".csv", ".tsv", ".zip", ".json")):
            print(f"  Skipping: {fname}")
            continue
        # Extract download URL from various possible API key names
        url = (f.get("content_details", {}).get("download_url")
               or f.get("download_url")
               or f.get("links", {}).get("download")
               or "")
        if not url:
            print(f"  WARNING: no download URL for {fname}, skipping")
            continue
        download_file(url, dest_dir / fname, desc=fname)

    return _load_tcga_from_dir(dest_dir)


def _load_tcga_from_dir(directory):
    """Load all CSV/TSV/ZIP/parquet files in directory and extract pathology report text."""
    docs = []
    paths = (list(directory.glob("*.csv")) + list(directory.glob("*.tsv"))
             + list(directory.glob("*.zip")) + list(directory.glob("*.parquet")))
    if not paths:
        print(f"  No data files found in {directory}. Skipping TCGA-Reports.")
        return docs
    for path in paths:
        docs.extend(_read_tabular_file(path, source="TCGA"))
    print(f"  TCGA-Reports: {len(docs)} documents loaded")
    return docs


def _read_tabular_file(path, source=""):
    """Read a CSV/TSV/ZIP/parquet and extract free-text strings from the best text column."""
    docs = []
    try:
        if path.suffix == ".parquet":
            import pyarrow.parquet as pq
            df = pq.read_table(path).to_pandas()
            docs.extend(_df_to_texts(df, source))
            return docs
        elif path.suffix == ".zip":
            with zipfile.ZipFile(path) as zf:
                for name in zf.namelist():
                    if name.endswith((".csv", ".tsv")):
                        with zf.open(name) as fh:
                            df = _read_df(fh, name)
                            docs.extend(_df_to_texts(df, source))
        else:
            df = _read_df(path, str(path))
            docs.extend(_df_to_texts(df, source))
    except Exception as e:
        print(f"  WARNING: could not read {path.name}: {e}")
    return docs


def _read_df(path_or_fh, name):
    sep = "\t" if str(name).endswith(".tsv") else ","
    return pd.read_csv(path_or_fh, sep=sep, low_memory=False)


def _df_to_texts(df, source=""):
    """Find the richest text column and return non-empty strings."""
    # Priority list of column names likely to hold free-text reports
    candidates = [
        "report_text", "text", "path_report", "pathology_report",
        "report", "narrative", "diagnosis", "findings", "abstract",
        "case_text", "clinical_text",
    ]
    col = next((c for c in candidates if c in df.columns), None)
    if col is None:
        # Fall back: pick the object column with the longest average text
        str_cols = df.select_dtypes(include="object").columns.tolist()
        if not str_cols:
            return []
        col = max(str_cols, key=lambda c: df[c].dropna().str.len().mean())
        print(f"  Auto-selected column '{col}' in {source}")
    texts = df[col].dropna().astype(str).str.strip().tolist()
    return [t for t in texts if len(t) > 80]


# ---------------------------------------------------------------------------
# Source 2: MultiCaRe (Zenodo, CC BY 4.0) — IBD-filtered
# ---------------------------------------------------------------------------

ZENODO_RECORD_ID = "10079370"
ZENODO_API = f"https://zenodo.org/api/records/{ZENODO_RECORD_ID}"

# Text columns in MultiCaRe that contain clinical narrative
MULTICARE_TEXT_COLS = [
    "abstract", "background", "case_presentation", "case presentation",
    "clinical presentation", "discussion", "conclusion", "text",
    "body", "history", "findings", "report",
]


def fetch_multicare_ibd():
    print("\n=== Source 2: MultiCaRe (Zenodo, CC BY 4.0) — IBD filter ===")
    dest_dir = RAW_DIR / "multicare"
    dest_dir.mkdir(parents=True, exist_ok=True)

    print("  Querying Zenodo API ...")
    try:
        r = requests.get(ZENODO_API, timeout=30)
        r.raise_for_status()
        record = r.json()
    except Exception as e:
        print(f"  ERROR: could not reach Zenodo API: {e}")
        print(f"  Manual fallback: download from https://zenodo.org/records/{ZENODO_RECORD_ID}")
        print(f"  and place files in {dest_dir}")
        return _load_multicare_ibd_from_dir(dest_dir)

    # Zenodo API v1 format: record["files"] list
    # Zenodo API v2 format: record["entries"] list (newer deposits)
    files = record.get("files") or record.get("entries", [])
    print(f"  Found {len(files)} file(s) in Zenodo record {ZENODO_RECORD_ID}")

    for f in files:
        # Support both Zenodo v1 and v2 key naming
        fname = f.get("filename") or f.get("key", "")
        size_bytes = f.get("filesize") or f.get("size", 0)
        size_mb = size_bytes / 1e6

        # Skip non-tabular files (images, PDFs etc)
        if not any(fname.lower().endswith(ext) for ext in (".csv", ".tsv", ".zip", ".json", ".parquet")):
            print(f"  Skipping non-text file: {fname} ({size_mb:.0f} MB)")
            continue

        # Build download URL (v1: links.download, v2: links.content)
        links = f.get("links", {})
        url = (links.get("download")
               or links.get("content")
               or links.get("self")
               or f.get("download_url", ""))
        if not url:
            print(f"  WARNING: no download URL for {fname}")
            continue

        print(f"  {fname}  ({size_mb:.0f} MB)")
        download_file(url, dest_dir / fname, desc=fname)

    return _load_multicare_ibd_from_dir(dest_dir)


def _load_multicare_ibd_from_dir(directory):
    """Load MultiCaRe files, combine text columns per case, filter for IBD."""
    all_docs = []
    paths = (list(directory.glob("*.csv")) + list(directory.glob("*.tsv"))
             + list(directory.glob("*.zip")) + list(directory.glob("*.json"))
             + list(directory.glob("*.parquet")))
    if not paths:
        print(f"  No data files found in {directory}. Skipping MultiCaRe.")
        return []

    for path in paths:
        all_docs.extend(_parse_multicare_file(path))

    ibd_docs = [d for d in all_docs if _is_ibd(d)]
    print(f"  MultiCaRe total cases loaded: {len(all_docs)}")
    print(f"  MultiCaRe IBD-relevant after filter: {len(ibd_docs)}")
    return ibd_docs


def _parse_multicare_file(path):
    """Parse one MultiCaRe file → list of combined case-text strings."""
    docs = []
    try:
        if path.suffix == ".parquet":
            import pyarrow.parquet as pq
            df = pq.read_table(path).to_pandas()
            text_cols = [c for c in df.columns
                         if any(kw in c.lower() for kw in MULTICARE_TEXT_COLS)]
            if not text_cols:
                text_cols = df.select_dtypes(include="object").columns.tolist()
            for _, row in df.iterrows():
                parts = [str(row[c]).strip() for c in text_cols
                         if pd.notna(row[c]) and str(row[c]).strip() not in ("nan", "")]
                combined = "\n\n".join(parts)
                if len(combined) > 100:
                    docs.append(combined)
        elif path.suffix == ".zip":
            with zipfile.ZipFile(path) as zf:
                for name in zf.namelist():
                    if name.endswith((".csv", ".tsv", ".json")):
                        with zf.open(name) as fh:
                            docs.extend(_parse_multicare_buffer(fh, name))
        elif path.suffix == ".json":
            with open(path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            if isinstance(data, list):
                for item in data:
                    text = _combine_case_fields(item)
                    if len(text) > 100:
                        docs.append(text)
        else:
            with open(path, "rb") as fh:
                docs.extend(_parse_multicare_buffer(fh, str(path)))
    except Exception as e:
        print(f"  WARNING: failed to parse {path.name}: {e}")
    return docs


def _parse_multicare_buffer(fh, name):
    """Read a CSV/TSV buffer, merge relevant text columns per row."""
    try:
        sep = "\t" if str(name).endswith(".tsv") else ","
        df = pd.read_csv(fh, sep=sep, low_memory=False)
        # Find text-rich columns
        text_cols = [c for c in df.columns
                     if any(kw in c.lower() for kw in MULTICARE_TEXT_COLS)]
        if not text_cols:
            text_cols = df.select_dtypes(include="object").columns.tolist()
        docs = []
        for _, row in df.iterrows():
            parts = [str(row[c]).strip() for c in text_cols
                     if pd.notna(row[c]) and str(row[c]).strip() not in ("nan", "")]
            combined = "\n\n".join(parts)
            if len(combined) > 100:
                docs.append(combined)
        return docs
    except Exception as e:
        print(f"  WARNING: parse error in {name}: {e}")
        return []


def _combine_case_fields(item):
    """Merge relevant fields from a JSON case dict into one string."""
    parts = []
    for key in ["abstract", "background", "case_presentation", "discussion",
                "conclusion", "text", "body", "clinical_presentation"]:
        val = item.get(key, "")
        if val and isinstance(val, str) and len(val.strip()) > 20:
            parts.append(val.strip())
    return "\n\n".join(parts)


def _is_ibd(text):
    t = text.lower()
    return any(kw in t for kw in IBD_KEYWORDS)


# ---------------------------------------------------------------------------
# Build shards
# ---------------------------------------------------------------------------

def build_shards(docs):
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    random.seed(42)
    random.shuffle(docs)

    n_val = max(50, int(len(docs) * VAL_FRACTION))
    val_docs = docs[:n_val]
    train_docs = docs[n_val:]

    print(f"\n=== Building shards ===")
    print(f"  Total: {len(docs)}  Train: {len(train_docs)}  Val: {len(val_docs)}")

    def write_shard(shard_docs, idx):
        path = DATA_DIR / f"shard_{idx:05d}.parquet"
        df = pd.DataFrame({"text": shard_docs})
        pq.write_table(pa.Table.from_pandas(df, preserve_index=False), path)
        kb = path.stat().st_size / 1024
        print(f"  Wrote {path.name}  ({len(shard_docs)} docs, {kb:.0f} KB)")

    # Pinned val shard
    write_shard(val_docs, VAL_SHARD_IDX)

    # Train shards (chunked)
    shard_idx = 0
    for i in range(0, len(train_docs), DOCS_PER_SHARD):
        write_shard(train_docs[i:i + DOCS_PER_SHARD], shard_idx)
        shard_idx += 1


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("IBD Pathology Text — Data Preparation")
    print("=" * 40)
    print(f"Output: {DATA_DIR}")
    print()
    print("Licenses: CC BY 4.0 (both sources) — commercial and open-source use permitted.")
    print()

    RAW_DIR.mkdir(parents=True, exist_ok=True)

    docs = []
    docs.extend(fetch_tcga_reports())
    docs.extend(fetch_multicare_ibd())

    if not docs:
        print("\nERROR: No documents collected. Check the download errors above.")
        print("You may need to manually download the files:")
        print(f"  TCGA-Reports: https://data.mendeley.com/datasets/{MENDELEY_DATASET_ID}/1")
        print(f"  MultiCaRe:    https://zenodo.org/records/{ZENODO_RECORD_ID}")
        sys.exit(1)

    build_shards(docs)

    print()
    print("Done! Next step:")
    print("  uv run prepare.py   # trains BPE tokenizer on your IBD text corpus")
