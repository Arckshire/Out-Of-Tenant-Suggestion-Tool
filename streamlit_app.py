# carrier_reco_hub.py
# Streamlit multi-product carrier suggestion hub (Last Mile, Parcel, Ocean, etc.)
# - Default: comparative cascading logic (your current LM behavior)
# - Toggle: absolute thresholds mode (select metrics & thresholds, allow equals or not)
# - Config-driven per-product metrics so you can add/modify products easily

import streamlit as st
import pandas as pd
from io import BytesIO

# =========================
# Product Config (EDIT ME)
# =========================
# Define metrics per product. Each metric: (display_name, direction, value_type)
# direction: "higher" or "lower"
# value_type: "percent" or "number" (drives cleaning)
PRODUCTS = {
    "Last Mile": {
        "metrics": [
            ("Data Availability", "higher", "percent"),
            ("Milestone Completeness", "higher", "percent"),
            ("Scheduled Milestone Completeness", "higher", "percent"),
            ("Out for Delivery Milestone Completeness", "higher", "percent"),
            ("In Transit Milestone Completeness", "higher", "percent"),
            ("Delivered Milestone Completeness", "higher", "percent"),
            ("Latency under 1 hr", "lower", "percent"),
            ("Latency under 2 hr", "lower", "percent"),
            ("Latency bw 1-3 hrs", "lower", "percent"),
            ("Latency bw 3-8 hrs", "lower", "percent"),
            ("Latency bw 8-24hrs", "lower", "percent"),
            ("Latency bw 24-72hrs", "lower", "percent"),
            ("Latency over 72hrs", "lower", "percent"),
            ("Avg Latency Mins", "lower", "number"),
        ],
        "volume_col": "Volume",         # optional; used for cleaning & potential sorting
        "carrier_col": "Carrier Name",  # required
    },
    # ==== Fill these when you have the actual schemas ====
    "Parcel": {
        "metrics": [
            # EXAMPLES (replace with real parcel columns):
            # ("On-Time Delivery %", "higher", "percent"),
            # ("First Attempt Delivery %", "higher", "percent"),
            # ("Damages %", "lower", "percent"),
            # ("Avg Transit Days", "lower", "number"),
        ],
        "volume_col": "Volume",
        "carrier_col": "Carrier Name",
    },
    "Ocean": {
        "metrics": [
            # EXAMPLES (replace with real ocean columns):
            # ("On-Time Departure %", "higher", "percent"),
            # ("On-Time Arrival %", "higher", "percent"),
            # ("Roll-Over Rate %", "lower", "percent"),
            # ("Avg Dwell Days", "lower", "number"),
        ],
        "volume_col": "Volume",
        "carrier_col": "Carrier Name",
    },
}


# =========================
# Streamlit App Shell
# =========================
st.set_page_config(page_title="Carrier Suggestion Hub", layout="wide")
st.title("Carrier Recommendation Hub")
st.caption("Pick a product (Last Mile / Parcel / Ocean), upload MASTER and CUSTOMER CSVs, and generate out-of-tenant suggestions.")

# --- Product selection ---
product = st.selectbox("Choose Product", options=list(PRODUCTS.keys()), index=0)
cfg = PRODUCTS[product]
metric_catalog = cfg["metrics"]
carrier_col = cfg["carrier_col"]
volume_col = cfg.get("volume_col", None)

st.markdown(f"**Selected Product:** `{product}`")
if not metric_catalog:
    st.warning("This product has no metrics configured yet. Edit the `PRODUCTS` config at the top to add metrics.")
st.divider()

# =========================
# Uploads
# =========================
st.header("1) Upload Files")
master_file = st.file_uploader("Upload MASTER dataset (all p44 carriers)", type=["csv"], key="master")
customer_file = st.file_uploader("Upload CUSTOMER carrier dataset (already used carriers)", type=["csv"], key="customer")

# =========================
# Parameters
# =========================
st.header("2) Parameters")

# Mode toggle
use_absolute = st.checkbox("Use absolute thresholds mode (override comparative logic)", value=False)
allow_equal_abs = st.checkbox("Absolute mode: allow equals to pass", value=True, help="When ON, ≥ for higher metrics and ≤ for lower metrics.")

num_suggestions = st.number_input("How many top suggestions do you want?", min_value=1, value=10, step=1)

# Comparative (default) UI: metric priority order (like your current tool)
if not use_absolute:
    # Build display list
    metric_labels = [f"{i+1}. {name} ({direction})" for i, (name, direction, _vtype) in enumerate(metric_catalog)]
    st.markdown("**Select metric priority order.** Enter numbers in comma-separated order (e.g., `1,2,14`):")
    st.text("\n".join(metric_labels))
    default_order = ",".join(str(i+1) for i in range(min(3, len(metric_catalog)))) if metric_catalog else ""
    order_input = st.text_input("Metric priority order", value=default_order)
    selected_indices = []
    try:
        selected_indices = [int(x.strip()) - 1 for x in order_input.split(",") if x.strip()]
    except Exception:
        st.error("Invalid metric order input; use numbers like 1,2,14")
    selected_metrics = [(metric_catalog[i][0], metric_catalog[i][1]) for i in selected_indices if 0 <= i < len(metric_catalog)]
else:
    # Absolute mode: select metrics + thresholds
    st.markdown("**Absolute thresholds mode** — select metrics and set required thresholds.")
    abs_selected = []
    abs_thresholds = {}
    if metric_catalog:
        left, right = st.columns(2)
        half = (len(metric_catalog) + 1) // 2
        for i, (name, direction, vtype) in enumerate(metric_catalog):
            container = left if i < half else right
            with container:
                chk = st.checkbox(f"{name} ({'higher' if direction=='higher' else 'lower'} is better)", key=f"abs_{name}")
                if chk:
                    # simple defaults: 95 for percent, 60 for lat mins if name suggests, else 0
                    if vtype == "percent":
                        default_val = 95.0
                    else:
                        default_val = 60.0 if "Latency" in name or "Transit" in name or "Days" in name else 0.0
                    thr = st.number_input(f"Threshold for {name}", value=float(default_val), step=1.0, key=f"thr_{name}")
                    abs_selected.append((name, direction))
                    abs_thresholds[name] = float(thr)
    selected_metrics = abs_selected
    metric_thresholds = abs_thresholds

st.divider()


# =========================
# Helpers
# =========================
def clean_percent(val):
    if pd.isna(val):
        return pd.NA
    try:
        if isinstance(val, str):
            return float(val.replace("%", "").replace(",", "").strip())
        r
