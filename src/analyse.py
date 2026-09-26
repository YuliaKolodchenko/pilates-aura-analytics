"""
analyse.py — every metric in the project, computed once, written to docs/metrics.json.

    python src/analyse.py

Reads data/processed/*.csv (produced by clean.py). Writes docs/metrics.json,
which the dashboard reads. No row-level data crosses that boundary — only
aggregates — which is what keeps client data off the public web.

Sections:
  overview     headline numbers
  channels     acquisition channel -> return rate, conversion (the thesis)
  cohorts      monthly first-visit cohorts, with a completeness flag
  instructors  return rate raw vs. trial-only (the confound)
  lapse        days since last visit
  schedule     visits, sessions, fill rate per time slot
  sales        product mix; monthly members/renewals when detail layout present
  classpass    what the channel is worth at the owner's payout rate
"""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import config as C  # noqa: E402

SEGMENT_ORDER = ["ClassPass", "Trial / free", "Paid direct"]


def pct(x, nd=1):
    return None if x is None or (isinstance(x, float) and np.isnan(x)) else round(float(x) * 100, nd)


def rnd(x, nd=1):
    return None if x is None or (isinstance(x, float) and np.isnan(x)) else round(float(x), nd)


def load():
    P = C.PROCESSED_DIR
    fv = pd.read_csv(P / "first_visit.csv", parse_dates=["First Visit"])
    lv = pd.read_csv(P / "last_visit.csv", parse_dates=["Last Visit"])
    sales = pd.read_csv(P / "sales.csv") if (P / "sales.csv").exists() else None
    if sales is not None and "Sale Date" in sales.columns:
        sales["Sale Date"] = pd.to_datetime(sales["Sale Date"])
    att = pd.read_csv(P / "attendance.csv") if (P / "attendance.csv").exists() else None
    log = json.loads((P / "clean_log.json").read_text())
    return fv, lv, sales, att, log


# ---------------------------------------------------------------------------
# Client-level frame: one row per client, first + last visit joined
# ---------------------------------------------------------------------------
def build_clients(fv, lv):
    m = fv[["Client ID", "First Visit", "Pricing Option", "Segment", "Staff",
            "# Visits since First Visit"]].merge(
        lv[["Client ID", "Last Visit", "# Visits", "Pricing Option", "Segment"]],
        on="Client ID", how="inner", suffixes=("", "_now"))
    m = m.rename(columns={"Segment": "Channel", "Segment_now": "Segment now",
                          "Pricing Option_now": "Pricing Option now"})
    m["returned"] = m["# Visits since First Visit"].fillna(0) > 0
    m["converted"] = m["Segment now"] == "Paid direct"
    m["lifespan_days"] = (m["Last Visit"] - m["First Visit"]).dt.days
    m["cohort"] = m["First Visit"].dt.to_period("M").astype(str)
    return m


def overview(m, asof):
    return {
        "clients": int(len(m)),
        "window_start": m["First Visit"].min().date().isoformat(),
        "window_end": asof.date().isoformat(),
        "weeks": rnd((asof - m["First Visit"].min()).days / 7, 1),
        "lifetime_visits": int(m["# Visits"].sum()),
    }


def channels(m):
    out = []
    for seg in SEGMENT_ORDER:
        s = m[m["Channel"] == seg]
        if len(s) == 0:
            continue
        out.append({
            "channel": seg,
            "clients": int(len(s)),
            "share": pct(len(s) / len(m)),
            "return_rate": pct(s["returned"].mean()),
            "conversion_rate": pct(s["converted"].mean()) if seg != "Paid direct" else None,
            "converted": int(s["converted"].sum()) if seg != "Paid direct" else None,
            "mean_visits": rnd(s["# Visits"].mean()),
            "median_lifespan_days": rnd(s["lifespan_days"].median(), 0),
        })
    return out


def cohorts(m, asof):
    rows = []
    for cohort, g in m.groupby("cohort"):
        start = pd.Period(cohort, "M").end_time
        complete = (asof - start).days >= C.COHORT_MIN_OBS_DAYS
        seg = g["Channel"].value_counts()
        rows.append({
            "month": cohort,
            "new": int(len(g)),
            "classpass": int(seg.get("ClassPass", 0)),
            "trial": int(seg.get("Trial / free", 0)),
            "paid": int(seg.get("Paid direct", 0)),
            "return_rate": pct(g["returned"].mean()),
            "trial_return_rate": pct(g.loc[g["Channel"] == "Trial / free", "returned"].mean())
            if seg.get("Trial / free", 0) >= C.MIN_CELL else None,
            "classpass_return_rate": pct(g.loc[g["Channel"] == "ClassPass", "returned"].mean())
            if seg.get("ClassPass", 0) >= C.MIN_CELL else None,
            "complete": bool(complete),
        })
    return rows


def instructors(m):
    def short(name):
        # "Victoria, Instructora" -> Victoria ; "Martinez, Majo" -> Majo
        parts = [p.strip() for p in str(name).split(",")]
        if len(parts) == 2 and "instructor" not in parts[1].lower():
            return parts[1]
        return parts[0]
    raw, trial = [], []
    for staff, g in m.groupby("Staff"):
        if len(g) < C.MIN_CELL:
            continue
        cp_share = (g["Channel"] == "ClassPass").mean()
        raw.append({"instructor": short(staff), "first_visits": int(len(g)),
                    "return_rate": pct(g["returned"].mean()), "classpass_share": pct(cp_share)})
        t = g[g["Channel"] == "Trial / free"]
        if len(t) >= C.MIN_CELL:
            trial.append({"instructor": short(staff), "trial_clients": int(len(t)),
                          "return_rate": pct(t["returned"].mean()),
                          "conversion_rate": pct(t["converted"].mean())})
    raw.sort(key=lambda r: -r["return_rate"])
    trial.sort(key=lambda r: -r["conversion_rate"])
    return {"raw": raw, "trial_only": trial,
            "suppressed_below": C.MIN_CELL}


def lapse(m, asof):
    days = (asof - m["Last Visit"]).dt.days
    return {
        "threshold_days": C.LAPSE_DAYS,
        "share_lapsed": pct((days > C.LAPSE_DAYS).mean()),
        "share_lapsed_45": pct((days > 45).mean()),
        "share_lapsed_90": pct((days > 90).mean()),
        "median_days_since_last_visit": int(days.median()),
        "by_segment_now": [
            {"segment": seg, "share_lapsed": pct((days[m["Segment now"] == seg] > C.LAPSE_DAYS).mean())}
            for seg in SEGMENT_ORDER if (m["Segment now"] == seg).sum() >= C.MIN_CELL
        ],
    }


# ---------------------------------------------------------------------------
# Schedule
# ---------------------------------------------------------------------------
def schedule(att, weeks, layout):
    if att is None:
        return None
    att = att.copy()
    att["Total Visits"] = att["Total Visits"].fillna(0)
    has_sessions = "Total Sessions" in att.columns and att["Total Sessions"].notna().any()

    def band(t):
        h = int(t.split(":")[0])
        return "Morning" if h < 12 else ("Afternoon" if h < 17 else "Evening")

    rows = []
    for _, r in att.iterrows():
        t = r["Time"]
        sessions = float(r["Total Sessions"]) if has_sessions else weeks
        avg = r["Total Visits"] / sessions if sessions else None
        new_slot = (t in C.SLOTS_OPENED_LATE) or (str(r.get("Day")) in C.DAYS_OPENED_LATE)
        rows.append({
            "day": None if pd.isna(r.get("Day")) else r.get("Day"),
            "time": t, "band": band(t),
            "visits": int(r["Total Visits"]),
            "unique_clients": int(r["Unique Clients"]) if not pd.isna(r.get("Unique Clients")) else None,
            "sessions": int(sessions) if has_sessions else None,
            "avg_per_session": rnd(avg, 2),
            "fill_rate": pct(avg / C.CAPACITY_PER_CLASS) if avg is not None else None,
            "visits_per_client": rnd(r["Total Visits"] / r["Unique Clients"], 2)
            if r.get("Unique Clients") else None,
            "new_slot": bool(new_slot),
        })

    core = [r for r in rows if not r["new_slot"]]
    tot_visits = sum(r["visits"] for r in core)
    tot_sessions = sum(r["sessions"] or 0 for r in core) if has_sessions else len(core) * weeks
    fill_overall = tot_visits / (tot_sessions * C.CAPACITY_PER_CLASS) if tot_sessions else None
    empty_seats_week = None
    if tot_sessions:
        empty_seats_week = round((tot_sessions * C.CAPACITY_PER_CLASS - tot_visits) / weeks)

    bands = []
    for b in ("Morning", "Afternoon", "Evening"):
        rs = [r for r in rows if r["band"] == b]
        if not rs:
            continue
        v = sum(r["visits"] for r in rs)
        s = sum(r["sessions"] or 0 for r in rs) if has_sessions else len(rs) * weeks
        bands.append({"band": b, "slots": len(rs), "visits": v,
                      "share": pct(v / sum(r["visits"] for r in rows)),
                      "avg_per_session": rnd(v / s, 2) if s else None,
                      "fill_rate": pct(v / s / C.CAPACITY_PER_CLASS) if s else None})

    return {
        "layout": layout,
        "capacity": C.CAPACITY_PER_CLASS,
        "sessions_known": has_sessions,
        "total_visits": int(sum(r["visits"] for r in rows)),
        "fill_rate_overall": pct(fill_overall),
        "empty_seats_per_week": empty_seats_week,
        "slots": rows,
        "bands": bands,
    }


# ---------------------------------------------------------------------------
# Sales
# ---------------------------------------------------------------------------
def sales_block(sales, layout, m):
    if sales is None:
        return None
    total = float(sales["Total amount"].sum())
    fam = (sales.groupby("Family")["Total amount"].agg(["sum", "count"])
           .sort_values("sum", ascending=False))
    families = [{"family": f, "revenue": rnd(r["sum"], 0), "lines": int(r["count"]),
                 "share": pct(r["sum"] / total)} for f, r in fam.iterrows()]
    prod = (sales.groupby(["Family", "Product"])["Total amount"].agg(["sum", "count"])
            .sort_values("sum", ascending=False).head(12))
    products = [{"family": f, "product": p, "revenue": rnd(r["sum"], 0), "lines": int(r["count"])}
                for (f, p), r in prod.iterrows()]

    out = {"layout": layout, "direct_revenue": rnd(total, 0), "families": families,
           "products": products, "monthly": None, "renewal": None}

    if layout != "detail":
        return out

    # ---- monthly members, new vs renewal, renewal rate (detail only) -------
    s = sales.copy()
    s["month"] = s["Sale Date"].dt.to_period("M")
    mp = s[s["Family"] == "Monthly plan"].sort_values("Sale Date")
    mp["first_plan_month"] = mp.groupby("Client ID")["month"].transform("min")
    mp["kind"] = np.where(mp["month"] == mp["first_plan_month"], "new", "renewal")
    months = sorted(s["month"].unique())
    buyers = {p: set(mp.loc[mp["month"] == p, "Client ID"]) for p in months}
    monthly, renewal = [], []
    for p in months:
        sm = s[s["month"] == p]
        pm = mp[mp["month"] == p]
        monthly.append({
            "month": str(p), "revenue": rnd(sm["Total amount"].sum(), 0),
            "plans_sold": int(len(pm)), "plan_buyers": int(pm["Client ID"].nunique()),
            "new_members": int((pm["kind"] == "new").sum()),
            "renewals": int((pm["kind"] == "renewal").sum()),
            "trials_sold": int((sm["Family"] == "Trial pack").sum()),
        })
        b = buyers[p]
        nxt, nxt2 = p + 1, p + 2
        renewal.append({
            "month": str(p), "members": len(b),
            "renewed_next_month": pct(len(b & buyers.get(nxt, set())) / len(b)) if b and nxt in buyers else None,
            "renewed_within_2": pct(len(b & (buyers.get(nxt, set()) | buyers.get(nxt2, set()))) / len(b))
            if b and nxt2 in buyers else None,
        })
    out["monthly"], out["renewal"] = monthly, renewal

    trial_buyers = set(s.loc[s["Family"] == "Trial pack", "Client ID"])
    plan_buyers = set(mp["Client ID"])
    out["trial_to_plan_via_sales"] = {
        "trial_buyers": len(trial_buyers),
        "bought_plan": len(trial_buyers & plan_buyers),
        "rate": pct(len(trial_buyers & plan_buyers) / len(trial_buyers)) if trial_buyers else None,
    }
    return out


def classpass_block(m, sales_out, sched):
    cp = m[m["Channel"] == "ClassPass"]
    cp_visits = float(cp["# Visits"].sum())
    total_visits = float(m["# Visits"].sum())
    direct_visits = total_visits - cp_visits
    direct_rev = sales_out["direct_revenue"] if sales_out else None
    cp_rev = cp_visits * C.CLASSPASS_PAYOUT_EUR
    return {
        "payout_per_visit": C.CLASSPASS_PAYOUT_EUR,
        "visits": int(cp_visits),
        "share_of_visits": pct(cp_visits / total_visits),
        "revenue": rnd(cp_rev, 0),
        "share_of_combined_revenue": pct(cp_rev / (cp_rev + direct_rev)) if direct_rev else None,
        "direct_revenue_per_visit": rnd(direct_rev / direct_visits, 2) if direct_rev and direct_visits else None,
        "value_per_client": {
            "classpass": rnd(cp["# Visits"].mean() * C.CLASSPASS_PAYOUT_EUR, 1),
        },
    }


# ---------------------------------------------------------------------------
def main():
    fv, lv, sales, att, log = load()
    m = build_clients(fv, lv)
    asof = max(m["Last Visit"].max(), pd.Timestamp(sales["Sale Date"].max()) if sales is not None
               and "Sale Date" in sales.columns else m["Last Visit"].max())
    weeks = (asof - m["First Visit"].min()).days / 7

    sales_out = sales_block(sales, log.get("sales_layout"), m)
    sched = schedule(att, weeks, log.get("attendance_layout"))

    metrics = {
        "meta": {
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "as_of": asof.date().isoformat(),
            "sources": {k: v["file"] for k, v in log["files"].items()},
            "warnings": log.get("warnings", []),
            "assumptions": {
                "capacity_per_class": C.CAPACITY_PER_CLASS,
                "classpass_payout_eur": C.CLASSPASS_PAYOUT_EUR,
                "lapse_days": C.LAPSE_DAYS,
                "cohort_min_obs_days": C.COHORT_MIN_OBS_DAYS,
                "min_cell": C.MIN_CELL,
                "slots_opened_late": sorted(C.SLOTS_OPENED_LATE | C.DAYS_OPENED_LATE),
            },
        },
        "overview": overview(m, asof),
        "channels": channels(m),
        "cohorts": cohorts(m, asof),
        "instructors": instructors(m),
        "lapse": lapse(m, asof),
        "schedule": sched,
        "sales": sales_out,
        "classpass": classpass_block(m, sales_out, sched),
    }
    C.DOCS_DIR.mkdir(exist_ok=True)

    def _default(o):  # numpy scalars -> plain Python
        if isinstance(o, (np.bool_,)):
            return bool(o)
        if isinstance(o, (np.integer,)):
            return int(o)
        if isinstance(o, (np.floating,)):
            return float(o)
        raise TypeError(f"not serialisable: {type(o)}")

    C.METRICS_JSON.write_text(json.dumps(metrics, indent=2, ensure_ascii=False, default=_default))
    print(f"wrote {C.METRICS_JSON} — {len(m)} clients, as of {asof.date()}")


if __name__ == "__main__":
    main()
