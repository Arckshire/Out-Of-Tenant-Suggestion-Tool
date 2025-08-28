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

auto_run = st.checkbox("Auto-run on changes", value=True)
run_clicked = st.button("Run")

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
                    # simple defaults: 95 for percent, 60 for latency/transit/days, else 0
                    if vtype == "percent":
                        default_val = 95.0
                    else:
                        default_val = 60.0 if any(k in name for k in ("Latency", "Transit", "Days")) else 0.0
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
        return float(val)
    except Exception:
        return pd.NA

def prep(df: pd.DataFrame, product_cfg: dict) -> pd.DataFrame:
    """Standardize columns, strip %, coerce numerics based on value_type."""
    df = df.copy()
    df.columns = df.columns.str.strip()
    # Normalize carrier/volume columns if present
    if product_cfg["carrier_col"] in df.columns:
        df[product_cfg["carrier_col"]] = df[product_cfg["carrier_col"]].astype(str).str.strip()
    if product_cfg.get("volume_col") and product_cfg["volume_col"] in df.columns:
        c = product_cfg["volume_col"]
        df[c] = (
            df[c].astype(str).str.replace(",", "", regex=False)
            .str.extract(r"(\d+\.?\d*)")[0].astype(float)
        )

    # Clean metric columns based on their configured value_type
    for name, _direction, vtype in product_cfg["metrics"]:
        if name in df.columns:
            if vtype == "percent":
                df[name] = df[name].apply(clean_percent)
            else:
                df[name] = pd.to_numeric(df[name], errors="coerce")
    return df

def to_excel_bytes(suggestions_df: pd.DataFrame, legend_df: pd.DataFrame) -> bytes:
    output = BytesIO()
    with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
        suggestions_df.to_excel(writer, index=False, sheet_name="Suggestions")
        legend_df.to_excel(writer, index=False, sheet_name="Legend")
    return output.getvalue()

# ===== Comparative mode (your original ANY-per-metric pass with cascading order) =====
def make_output_comparative(master_df, customer_df, metrics, suggestion_count, carrier_col_name):
    """
    metrics: list[(col, direction)] in priority order
    Logic: For each suggested (master-not-in-customer) row, it must pass each metric by
           being >= (or <=) at least one customer carrier on that metric (ANY). This matches your current code.
    """
    if not metrics:
        return pd.DataFrame()

    unused = master_df[~master_df[carrier_col_name].str.lower().isin(customer_df[carrier_col_name].str.lower())].copy()
    suggested = []

    for _, sugg in unused.iterrows():
        passes = True
        carrier_to_metrics = {}

        for col, direction in metrics:
            if col not in customer_df.columns or pd.isna(sugg.get(col)):
                passes = False
                break

            cust_vals = pd.to_numeric(customer_df[col], errors="coerce")
            sugg_val = pd.to_numeric(sugg[col], errors="coerce")

            if pd.isna(sugg_val):
                passes = False
                break

            if direction == "higher":
                mask = sugg_val >= cust_vals
            else:
                mask = sugg_val <= cust_vals

            if mask.any():
                for ci in customer_df[mask].index:
                    cust_name = customer_df.loc[ci, carrier_col_name]
                    cust_val = pd.to_numeric(customer_df.loc[ci, col], errors="coerce")
                    if pd.isna(cust_val) or pd.isna(sugg_val):
                        continue
                    tag = "(E)" if abs(sugg_val - cust_val) < 1e-6 else ("(B)" if ((sugg_val > cust_val) if direction=="higher" else (sugg_val < cust_val)) else "(E)")
                    metric_label = f"{col} {tag}"
                    carrier_to_metrics.setdefault(str(cust_name).title(), []).append(metric_label)
            else:
                passes = False
                break

        if passes and carrier_to_metrics:
            row = sugg.to_dict()
            i = 1
            for cust_carrier, labeled_metrics in carrier_to_metrics.items():
                row[f"Carrier {i}"] = cust_carrier
                row[f"Reason {i}"] = ", ".join(labeled_metrics)
                i += 1
            suggested.append(row)

    if not suggested:
        return pd.DataFrame()

    df = pd.DataFrame(suggested).head(suggestion_count)
    df.insert(0, "SL No", range(1, len(df)+1))
    for col in df.columns:
        if col.lower().startswith("carrier"):
            df[col] = df[col].astype(str).str.title()
    return df

# ===== Absolute thresholds mode =====
def make_output_absolute_thresholds(master_df, customer_df, metrics_with_dir, thresholds, allow_equal, suggestion_count, carrier_col_name):
    """
    - Keep only master carriers not already in customer.
    - Suggested carriers must pass ALL selected thresholds.
    - Bad customers = those that fail ANY selected threshold.
    - Reasons show (B)/(E) vs bad customers, with Δ improvement.
    """
    if not metrics_with_dir:
        return pd.DataFrame()

    def pass_threshold(val, thr, direction, allow_eq):
        if pd.isna(val) or pd.isna(thr):
            return False
        if direction == "higher":
            return (val > thr) or (allow_eq and val >= thr)
        else:
            return (val < thr) or (allow_eq and val <= thr)

    # Identify unused master carriers
    unused = master_df[~master_df[carrier_col_name].str.lower().isin(customer_df[carrier_col_name].str.lower())].copy()

    # Determine bad customer carriers (fail ANY threshold)
    bad_rows = []
    for _, crow in customer_df.iterrows():
        fail = False
        for col, direction in metrics_with_dir:
            if col not in customer_df.columns:
                continue
            thr = thresholds.get(col)
            cval = pd.to_numeric(crow.get(col), errors="coerce")
            if thr is None or pd.isna(cval):
                fail = True
                break
            if direction == "higher":
                if not ((cval > thr) or (allow_equal and cval >= thr)):
                    fail = True
                    break
            else:
                if not ((cval < thr) or (allow_equal and cval <= thr)):
                    fail = True
                    break
        if fail:
            bad_rows.append(crow)
    bad_customers = pd.DataFrame(bad_rows) if bad_rows else pd.DataFrame(columns=customer_df.columns)

    suggested_rows = []
    eps = 1e-9

    for _, srow in unused.iterrows():
        # must pass ALL thresholds
        ok = True
        for col, direction in metrics_with_dir:
            if col not in srow or col not in thresholds:
                ok = False
                break
            sval = pd.to_numeric(srow[col], errors="coerce")
            thr = thresholds[col]
            if not pass_threshold(sval, thr, direction, allow_equal):
                ok = False
                break
        if not ok:
            continue

        # Build Reason columns vs bad customers
        carrier_to_reasons = {}
        if not bad_customers.empty:
            for _, brow in bad_customers.iterrows():
                reasons = []
                for col, direction in metrics_with_dir:
                    sval = pd.to_numeric(srow.get(col), errors="coerce")
                    bval = pd.to_numeric(brow.get(col), errors="coerce")
                    if pd.isna(sval) or pd.isna(bval):
                        continue
                    is_better = (sval > bval) if direction == "higher" else (sval < bval)
                    is_equal  = abs((sval if pd.notna(sval) else 0) - (bval if pd.notna(bval) else 0)) < eps
                    tag = "(B)" if is_better else ("(E)" if is_equal else "")
                    if direction == "higher":
                        delta = sval - bval
                    else:
                        delta = bval - sval
                    if tag:
                        reasons.append(f"{col} {tag} (Δ {round(float(delta), 2)})")
                if reasons:
                    cust_name = str(brow.get(carrier_col_name, "")).title()
                    carrier_to_reasons[cust_name] = ", ".join(reasons)

        out_row = srow.to_dict()
        if carrier_to_reasons:
            i = 1
            for cust, reason in carrier_to_reasons.items():
                out_row[f"Carrier {i}"] = cust
                out_row[f"Reason {i}"] = reason
                i += 1
        else:
            out_row["Carrier 1"] = "—"
            out_row["Reason 1"] = "Meets all thresholds"
        suggested_rows.append(out_row)

    if not suggested_rows:
        return pd.DataFrame()

    df = pd.DataFrame(suggested_rows).head(suggestion_count)
    df.insert(0, "SL No", range(1, len(df)+1))
    for col in df.columns:
        if col.lower().startswith("carrier"):
            df[col] = df[col].astype(str).str.title()
    return df


# =========================
# Run
# =========================
st.header("3) Generate Suggestions")

ready = master_file is not None and customer_file is not None and metric_catalog is not None

def compute_and_show():
    if master_file is None or customer_file is None:
        st.info("Upload both files to continue.")
        return

    # need selected metrics
    if use_absolute and len(selected_metrics) == 0:
        st.info("Select at least one metric and set thresholds in Absolute mode.")
        return
    if (not use_absolute) and len(selected_metrics) == 0:
        st.info("Enter a valid metric priority order with at least one metric.")
        return

    master_df = prep(pd.read_csv(master_file), cfg)
    customer_df = prep(pd.read_csv(customer_file), cfg)

    # sanity checks
    if carrier_col not in master_df.columns or carrier_col not in customer_df.columns:
        st.error(f"Both files must include a `{carrier_col}` column.")
        return

    missing_in_master = [m[0] for m in metric_catalog if (m[0] not in master_df.columns)]
    missing_in_customer = [m[0] for m in metric_catalog if (m[0] not in customer_df.columns)]
    if missing_in_master:
        st.warning(f"MASTER missing columns (not fatal if not selected): {', '.join(missing_in_master)}")
    if missing_in_customer:
        st.warning(f"CUSTOMER missing columns (not fatal if not selected): {', '.join(missing_in_customer)}")

    # compute
    with st.spinner("Crunching suggestions..."):
        if not use_absolute:
            # Comparative: selected_metrics is [(name, direction)]
            output_df = make_output_comparative(master_df, customer_df, selected_metrics, num_suggestions, carrier_col)
        else:
            # Absolute: selected_metrics is [(name, direction)], thresholds in metric_thresholds
            thresholds = {k: v for k, v in metric_thresholds.items()}
            output_df = make_output_absolute_thresholds(
                master_df=master_df,
                customer_df=customer_df,
                metrics_with_dir=selected_metrics,
                thresholds=thresholds,
                allow_equal=allow_equal_abs,
                suggestion_count=num_suggestions,
                carrier_col_name=carrier_col
            )

    st.subheader("Results Preview")
    if output_df.empty:
        st.warning("No suggestions found with the selected settings.")
    else:
        st.dataframe(output_df, use_container_width=True)

        # Legend
        legend_rows = [
            ["Column", "Explanation"],
            ["Carrier N", "Customer carrier outperformed (comparative mode) or compared against (absolute mode)."],
            ["Reason N", "Metrics with tags: (B)=Better, (E)=Equal; Δ shows improvement vs that customer in absolute mode."]
        ]
        legend_df = pd.DataFrame(legend_rows[1:], columns=legend_rows[0])
        st.subheader("Legend")
        st.table(legend_df)

        # Download
        data = to_excel_bytes(output_df, legend_df)
        st.download_button(
            "Download Suggestions (Excel)",
            data,
            file_name=f"{product.replace(' ','_')}_Top_{num_suggestions}_Suggestions.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )

# Auto-run or manual run
if auto_run:
    compute_and_show()
elif run_clicked:
    compute_and_show()

with st.expander("How to add/modify a product (Parcel/Ocean/etc.)"):
    st.markdown(
        """
1. Edit the `PRODUCTS` dict at the top.
2. For each product, add tuples to `metrics`: `(Display Name, direction, value_type)`.
   - `direction`: `"higher"` or `"lower"`
   - `value_type`: `"percent"` (strips `%` and coerces) or `"number"`
3. Ensure your CSVs use the **exact column names** from `metrics` and include `Carrier Name` (or change `carrier_col`).
4. (Optional) Set `volume_col` if you want it cleaned for consistency or future sorting.

**Example (Parcel):**
```python
"Parcel": {
    "metrics": [
        ("On-Time Delivery %", "higher", "percent"),
        ("First Attempt Delivery %", "higher", "percent"),
        ("Damage Rate %", "lower", "percent"),
        ("Avg Transit Days", "lower", "number"),
    ],
    "volume_col": "Volume",
    "carrier_col": "Carrier Name",
}
"""
)
