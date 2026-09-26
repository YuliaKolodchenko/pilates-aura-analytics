"""
clean.py — load the Mindbody exports, make them consistent, remove personal data.

    python src/clean.py

Reads every .xlsx in data/raw/, writes one CSV per report to data/processed/,
and prints a log of what was dropped and why. Nothing here calculates a metric;
that is analyse.py's job. This script's only promise is: what comes out is
tidy, in English, de-duplicated, and contains no names, phones or emails.
"""

import hashlib
import json
import os
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import config as C  # noqa: E402

LOG = {"files": {}, "warnings": []}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def find_raw_files() -> dict:
    """Map report key -> path, by matching filename patterns. Newest file wins."""
    found = {}
    for path in sorted(C.RAW_DIR.glob("*.xlsx"), key=lambda p: p.stat().st_mtime):
        name = path.name.lower()
        for key, pattern in C.FILE_PATTERNS.items():
            if pattern in name:
                found[key] = path
    return found


def hash_id(value, salt: str) -> str:
    """Pseudonymise a client ID. Same input -> same output, so joins still work."""
    if pd.isna(value):
        return None
    raw = f"{salt}:{str(value).strip()}"
    return hashlib.sha256(raw.encode()).hexdigest()[:12]


def strip_text(df: pd.DataFrame) -> pd.DataFrame:
    text_cols = [c for c in df.columns if df[c].dtype.kind == "O" or str(df[c].dtype).startswith("str")]
    for col in text_cols:
        df[col] = df[col].astype(str).str.strip().replace({"nan": None, "": None, "None": None})
    return df


def rename_and_translate(df: pd.DataFrame) -> pd.DataFrame:
    df.columns = [str(c).strip() for c in df.columns]
    df = df.rename(columns=C.COLUMN_MAP)
    df = df.loc[:, [c for c in df.columns if c and not c.startswith("Unnamed")]]
    for col in ("Booking Method", "Referral Type"):
        if col in df.columns:
            df[col] = df[col].replace(C.VALUE_MAP)
    return df


def drop_pii(df: pd.DataFrame) -> pd.DataFrame:
    return df.drop(columns=[c for c in C.PII_COLUMNS if c in df.columns])


def log(key, path, before, after, notes):
    LOG["files"][key] = {"file": path.name, "rows_in": int(before), "rows_out": int(after), "notes": notes}


# ---------------------------------------------------------------------------
# Per-report cleaners
# ---------------------------------------------------------------------------
def clean_visits(path: Path, date_col: str, salt: str) -> pd.DataFrame:
    """First Visit and Last Visit share the same shape: one row per client."""
    df = pd.read_excel(path)
    n0 = len(df)
    df = rename_and_translate(strip_text(df))
    notes = []

    # 1. The export ends with a "Total ... visits" footer that is not a date.
    df[date_col] = pd.to_datetime(df[date_col], errors="coerce")
    footer = df[date_col].isna().sum()
    df = df.dropna(subset=[date_col])
    if footer:
        notes.append(f"dropped {footer} non-date row(s) (totals footer)")

    # 2. Duplicate client IDs — keep the most recent.
    dups = df.duplicated("Client ID").sum()
    if dups:
        df = df.sort_values(date_col).drop_duplicates("Client ID", keep="last")
        notes.append(f"dropped {dups} duplicate Client ID(s)")

    # 3. Derived fields, before we lose the raw pricing option to trimming.
    df["Pricing Option"] = df["Pricing Option"].fillna("").str.strip()
    df["Segment"] = df["Pricing Option"].map(C.segment_of)

    # 4. Pseudonymise and drop personal data.
    df["Client ID"] = df["Client ID"].map(lambda v: hash_id(v, salt))
    df = drop_pii(df)

    for col in df.columns:
        if "Visit" in col and df[col].dtype == object:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    log(path.stem, path, n0, len(df), notes)
    return df


def clean_sales(path: Path, salt: str) -> tuple[pd.DataFrame, str]:
    """
    Sales by Service comes in two layouts depending on how it was exported:
      * detail  — one row per transaction, with Client ID and Sale Date
      * summary — one row per pricing option, totals only
    Detect which we got. Detail enables monthly analysis; summary does not.
    """
    df = pd.read_excel(path)
    n0 = len(df)
    df = rename_and_translate(strip_text(df))
    notes = []

    mode = "detail" if "Sale Date" in df.columns else "summary"
    notes.append(f"layout: {mode}")

    if mode == "detail":
        df["Sale Date"] = pd.to_datetime(df["Sale Date"], errors="coerce")
        footer = df["Sale Date"].isna().sum()
        df = df.dropna(subset=["Sale Date"])
        if footer:
            notes.append(f"dropped {footer} non-date row(s)")
        df["Client ID"] = df["Client ID"].map(lambda v: hash_id(v, salt))
    else:
        df = df.dropna(subset=["Pricing Option"])
        df = df.rename(columns={"Pricing Option": "Product"})
        LOG["warnings"].append(
            "Sales export is the SUMMARY layout (one row per product). Monthly revenue, "
            "new-vs-renewal and per-client value need the DETAIL layout — re-export with "
            "client detail enabled."
        )

    df["Product"] = df["Product"].fillna("").str.strip()
    df["Family"] = df["Product"].map(C.family_of)
    for col in ("Total amount", "Cash equivalent", "Non-cash equivalent", "Quantity"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    refunds = int((df["Total amount"] < 0).sum()) if "Total amount" in df else 0
    if refunds:
        notes.append(f"{refunds} negative line(s) kept as refunds")

    df = drop_pii(df)
    log(path.stem, path, n0, len(df), notes)
    return df, mode


def clean_attendance(path: Path) -> tuple[pd.DataFrame, str]:
    """
    Attendance Analysis also has two layouts:
      * time     — grouped by time of day only ("07:30:00"), with Total Sessions
      * day_time — grouped by weekday and time ("Lunes 7:30"), no session count
    """
    df = pd.read_excel(path)
    n0 = len(df)
    df = rename_and_translate(strip_text(df))
    notes = []

    df = df.dropna(subset=["Service Time"])
    df = df[df["Service Time"].astype(str).str.contains(r"\d")]  # drop any totals row

    st = df["Service Time"].astype(str)
    if st.str.match(r"^\d{1,2}:\d{2}(:\d{2})?$").all():
        mode = "time"
        df["Time"] = st.str.slice(0, 5)
        df["Day"] = None
    else:
        mode = "day_time"
        parts = st.str.extract(r"^(\S+)\s+(\d{1,2}:\d{2})$")
        df["Day"] = parts[0].replace(C.DAY_MAP)
        df["Time"] = parts[1].map(lambda t: t if len(t) == 5 else "0" + t)
    notes.append(f"layout: {mode}")

    for col in ("Paid Visits", "Unique Clients", "Comp/Guest Visits", "Total Visits",
                "Total Sessions", "Average"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    if "Total Sessions" not in df.columns:
        LOG["warnings"].append(
            "Attendance export has no 'Total Sessions' column (day+time layout). "
            "Per-session averages will assume every slot ran weekly for the whole window."
        )

    log(path.stem, path, n0, len(df), notes)
    return df, mode


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    salt = os.environ.get("AURA_HASH_SALT", "pilates-aura-2026")
    C.PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    files = find_raw_files()

    missing = [k for k in C.FILE_PATTERNS if k not in files]
    if missing:
        LOG["warnings"].append(f"missing exports: {', '.join(missing)}")

    if "first_visit" in files:
        clean_visits(files["first_visit"], "First Visit", salt).to_csv(
            C.PROCESSED_DIR / "first_visit.csv", index=False)
    if "last_visit" in files:
        clean_visits(files["last_visit"], "Last Visit", salt).to_csv(
            C.PROCESSED_DIR / "last_visit.csv", index=False)
    if "sales" in files:
        df, mode = clean_sales(files["sales"], salt)
        df.to_csv(C.PROCESSED_DIR / "sales.csv", index=False)
        LOG["sales_layout"] = mode
    if "attendance" in files:
        df, mode = clean_attendance(files["attendance"])
        df.to_csv(C.PROCESSED_DIR / "attendance.csv", index=False)
        LOG["attendance_layout"] = mode

    # Belt and braces: assert no PII column survived.
    for csv in C.PROCESSED_DIR.glob("*.csv"):
        cols = pd.read_csv(csv, nrows=0).columns
        leaked = [c for c in C.PII_COLUMNS if c in cols]
        assert not leaked, f"PII column {leaked} survived in {csv.name}"

    (C.PROCESSED_DIR / "clean_log.json").write_text(json.dumps(LOG, indent=2, ensure_ascii=False))
    print(json.dumps(LOG, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
