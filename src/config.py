"""
config.py — every tunable in one place.

If a number in the analysis needs to change (class capacity, the ClassPass
payout, the churn threshold), it changes here and nowhere else. Nothing in
clean.py or analyse.py hard-codes a business assumption.
"""

from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = ROOT / "data" / "raw"            # Mindbody exports go here. Gitignored.
PROCESSED_DIR = ROOT / "data" / "processed"  # Cleaned, anonymised. Gitignored.
DOCS_DIR = ROOT / "docs"                   # Published by GitHub Pages.
METRICS_JSON = DOCS_DIR / "metrics.json"   # The only data that reaches the web.

# ---------------------------------------------------------------------------
# Facts supplied by the studio owner (not derivable from the exports)
# ---------------------------------------------------------------------------
CAPACITY_PER_CLASS = 10          # reformers per class
CLASSPASS_PAYOUT_EUR = 5.0       # what ClassPass pays the studio per visit
SLOTS_OPENED_LATE = {"16:00"}    # time slots opened in Sept 2026 — too new to judge
DAYS_OPENED_LATE = {"Saturday"}  # same, for day-level data

# ---------------------------------------------------------------------------
# Analytical choices (state these in the README — they are judgement calls)
# ---------------------------------------------------------------------------
LAPSE_DAYS = 60            # no visit for > 60 days = lapsed
COHORT_MIN_OBS_DAYS = 60   # a cohort is "complete" once every member had 60 days to return
MIN_CELL = 10              # suppress any published breakdown with fewer observations

# ---------------------------------------------------------------------------
# How raw files are recognised (substring of filename, case-insensitive)
# ---------------------------------------------------------------------------
FILE_PATTERNS = {
    "first_visit": "first visit",
    "last_visit": "last visit",
    "sales": "salesbyservice",
    "attendance": "attendanceanalysis",
}

# ---------------------------------------------------------------------------
# Segment mapping: pricing option -> acquisition channel
# The first-visit pricing option is the channel; the current one is the outcome.
# ---------------------------------------------------------------------------
def segment_of(pricing_option: str) -> str:
    p = (pricing_option or "").strip().lower()
    if "classpass" in p:
        return "ClassPass"
    if any(k in p for k in ("prueba", "gratuita", "unpaid")):
        return "Trial / free"
    return "Paid direct"


# Product family for sales lines
def family_of(product: str) -> str:
    p = (product or "").strip().lower()
    if "enrollment" in p or "inscripci" in p:
        return "Enrollment fee"
    if "clases" in p and ("mes" in p or "trimestre" in p):
        return "Monthly plan"
    if "prueba" in p:
        return "Trial pack"
    if "gratuita" in p:
        return "Free class"
    if "classpass" in p:
        return "ClassPass"
    return "Drop-in / pack"


# Mindbody localises some exports to Spanish and others to English.
# Normalise everything to English before analysis.
VALUE_MAP = {
    "Modo negocio": "Business Mode",
    "Modo Consumidor": "Consumer Mode",
    "Otro": "Other",
    "Sin asignar": "Unassigned",
    "Otro - ClassPass": "Other - ClassPass",
    "Otro - Other": "Other - Other",
    "Otro - Another Client": "Other - Another Client",
    "Otro Cliente": "Other - Another Client",
    "Otro - 0": "Other - 0",
    "Otro - Amiga": "Other - Amiga",
    "Mindbody App": "MINDBODY app",
}

COLUMN_MAP = {
    # Sales by Service (Spanish -> English), both detail and summary layouts
    "Nombre": "Product",
    "ID del Cliente": "Client ID",
    "Cliente": "Client",
    "Categoría": "Category Name",
    "Teléfono particular": "Phone",
    "Fecha de Venta": "Sale Date",
    "Fecha de activación": "Activation Date",
    "Días de activación de compensación": "Activation Offset Days",
    "Fecha de Expiración": "Expiration Date",
    "Cantidad total": "Total amount",
    "Equivalente en efectivo": "Cash equivalent",
    "No equivalente de efectivo": "Non-cash equivalent",
    "Cantidad": "Quantity",
    # Attendance Analysis (Spanish -> English)
    "Día y Hora": "Service Time",
    "Visitas Pagadas": "Paid Visits",
    "Porcentaje del Total de Visitas*": "Percent of Total Visits*",
    "Clientes Únicos": "Unique Clients",
    "Visitas de cortesia/invitado": "Comp/Guest Visits",
    "Visitas de cortesía/invitado": "Comp/Guest Visits",
    "Total de Visitas": "Total Visits",
}

DAY_MAP = {
    "Lunes": "Monday", "Martes": "Tuesday", "Miércoles": "Wednesday",
    "Jueves": "Thursday", "Viernes": "Friday", "Sábado": "Saturday", "Domingo": "Sunday",
}

# Columns that must never reach data/processed
PII_COLUMNS = ["Client", "Phone", "Email", "Rep 1", "Teléfono particular", "Cliente"]
