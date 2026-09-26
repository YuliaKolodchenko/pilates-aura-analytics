# Pilates Aura — Studio Analytics

**Live dashboard → https://yuliakolodchenko.github.io/pilates-aura-analytics/**

A boutique Pilates studio in Barcelona gets half its first-time visitors through ClassPass and the other half through its own trial classes. The two channels are the same size. One of them produces almost all of the studio's paying members; the other produces almost none. Nobody at the studio could see this, because the numbers that show it live in different reports that the booking platform cannot join.

This repository joins them.

## The problem

The studio runs on Mindbody, which offers about fifteen reports. Each answers one narrow question — who visited last, who visited first, what was sold, which hours are busy. None of them talk to each other. The question the owner actually has — *which of my marketing channels is worth the money?* — needs the First Visit report joined to the Last Visit report, with revenue and attendance alongside. Mindbody has no way to do that.

So the project is not "analytics for a studio that has none". It is turning fifteen disconnected exports into one answer, and being honest about what that answer can and cannot support.

## What it found

Over seven months (February–September 2026, 751 clients):

| First visit via | Clients | Came back | Bought a monthly plan |
|---|---|---|---|
| ClassPass | 346 | 19% | **6 (1.7%)** |
| A trial or free class | 370 | 74% | **138 (37%)** |

Two channels of equal size; a twenty-fold difference in members produced.

Three more things the joined data shows, none visible in any single report:

- **The instructor ranking reverses.** On raw return rate, Rodolfo ranks fourth of five. But 60% of his first-timers arrive via ClassPass, the channel that returns to nobody. Compared on trial clients only, he is the best converter in the studio (51%). Ranking staff on the unadjusted number would have been wrong.
- **The studio runs at 30% of capacity.** With 10 reformers per class and real session counts from the attendance export, that is about 256 empty places a week. A ClassPass visit at €5 into an otherwise empty class displaces nobody — so the recommendation is *not* to drop ClassPass, but to convert its visitors.
- **ClassPass is 46% of the client list, 17% of visits, and about 6% of revenue.** Its revenue is not recorded in Mindbody at all; it is computed from visits × the €5 payout the owner reports.

The full argument, with the numbers that would change each recommendation, is on the dashboard.

## How it works

```
data/raw/*.xlsx        Mindbody exports — never committed (see .gitignore)
        │
        ▼
src/clean.py           normalise, de-duplicate, translate ES→EN, hash IDs, drop names/contacts
        │
        ▼
data/processed/*.csv   tidy and pseudonymised — never committed
        │
        ▼
src/analyse.py         every metric, computed once
        │
        ▼
docs/metrics.json      aggregates only — the single file the web sees
        │
        ▼
docs/index.html        the dashboard; reads the JSON, draws the charts
```

The `metrics.json` boundary is the design decision worth defending. Python owns the numbers, so a metric can only be defined in one place. JavaScript owns the picture, so the dashboard can be redesigned without touching analysis. Next month's exports re-run the pipeline without touching the interface. And because nothing row-level crosses the boundary, the privacy guarantee is structural rather than a matter of remembering.

All tunable assumptions — class capacity, the ClassPass payout, the churn threshold, the minimum group size for publication — live in `src/config.py` and nowhere else.

## Reproducing it

```bash
pip install -r requirements.txt

# 1. Export from Mindbody (Insights → Reports) into data/raw/:
#    Clients → First Visit, Clients → Last Visit,
#    Sales → Sales by Service, Clients → Attendance Analysis
# 2. Run the pipeline
python src/clean.py       # prints what was dropped and why
python src/analyse.py     # writes docs/metrics.json
# 3. View
cd docs && python -m http.server   # then open http://localhost:8000
```

`clean.py` detects which layout of each export it received. Sales by Service comes as either a per-transaction *detail* or a per-product *summary*; Attendance Analysis is grouped either by time of day or by weekday and time. The detail and day-level layouts unlock more of the dashboard; the pipeline says so in its warnings rather than failing.

## What the data cannot say

- **Right-censoring.** Clients who first visited in the last 60 days have not had time to return. Their cohorts are marked incomplete and hatched on the dashboard; their return rates are understated by construction and must not be read as a downward trend.
- **Short history.** The studio's Mindbody data starts in February 2026. Eight monthly cohorts support a first-visit-to-second-visit funnel; they do not support claims about seasonality or long-run retention.
- **ClassPass revenue is calculated, not recorded.** It settles outside Mindbody. The figure here is visits × €5, the rate the owner reports.
- **Attribution is inferred.** The acquisition channel is the pricing option on the first visit, not a recorded source field.
- **Attendance has no capacity column.** The 10-reformer figure comes from the owner. The export received is grouped by time of day only, so weekday patterns are not visible.
- **Sales export is the summary layout.** Month-by-month revenue, renewals and per-client value need the detail layout and are not shown.
- **Channel mix confounds every breakdown.** The instructor example shows it reversing a ranking. Any comparison by slot, day or staff must be checked for channel composition before a conclusion is drawn.

## Handling of personal data

The exports contain real names, phone numbers and email addresses. The repository is public, and git keeps history, so a file committed once is retrievable forever. Three rules:

1. `data/raw/` and `data/processed/` are excluded in `.gitignore` before any data touches the repo. `*.xlsx` is excluded globally.
2. `clean.py` replaces every Client ID with a salted SHA-256 hash and drops name, phone and email. It asserts at the end that no such column survived.
3. Only aggregates reach `metrics.json`. Any group with fewer than 10 people is suppressed.

This is pseudonymisation, not anonymisation — the studio can still re-identify its own clients from its own records. What protects individuals is that nothing about any individual is published.

## Data dictionary

Column names as received; both visit reports share a shape.

| Export | Key columns used |
|---|---|
| First Visit | Client ID · First Visit · Pricing Option · Staff · # Visits since First Visit |
| Last Visit | Client ID · Last Visit · # Visits · Pricing Option |
| Sales by Service (summary) | Category Name · Pricing Option · Total amount · Quantity |
| Sales by Service (detail) | + Client ID · Sale Date — enables the monthly panel |
| Attendance Analysis (by time) | Service Time · Total Visits · Unique Clients · Total Sessions |

Quirks the cleaner handles: a totals footer row that breaks date parsing; Spanish values in one export and English in another for the same field; leading spaces that split one product into two; three spellings of "clases al mes"; refunds as negative amounts; duplicate client IDs.

## Stack

Python 3, pandas, openpyxl. The dashboard is a single HTML file with inline SVG — no framework, no build step, no external dependencies.

## Licence

MIT.
