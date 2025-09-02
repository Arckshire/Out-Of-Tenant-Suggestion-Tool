# streamlit_app.py
# Multi-product Streamlit app (Last Mile, Parcel, Ocean).
# - Comparative mode: ANY-per-metric (original LM behavior), Reasons include Δ vs matched customer.
# - Absolute mode: plain text threshold inputs (no +/-), shown only when metric is checked; equality toggle.
# - Per-control and per-metric hover tooltips.
# - Drops 'Unnamed: 0' and blank headers from inputs/outputs.
# - Excel writer: try openpyxl/xlsxwriter; fallback to CSV downloads if neither installed.

import streamlit as st
import pandas as pd
from io import BytesIO
import importlib.util
import re

# =========================
# Product Config (EDIT ME)
# =========================
# Metric tuple: (display_name, direction, value_type[, help_text])
#   direction: "higher" | "lower"
#   value_type: "percent" | "number"
PRODUCTS = {
    "Last Mile": {
        "metrics": [
            ("Data Availability", "higher", "percent", "Percent of shipments with any usable tracking data present."),
            ("Milestone Completeness", "higher", "percent", "Percent of expected milestones received for the shipment."),
            ("Scheduled Milestone Completeness", "higher", "percent", "Percent of scheduled milestones received (planned events)."),
            ("Out for Delivery Milestone Completeness", "higher", "percent", "Percent of OOD milestones received when applicable."),
            ("In Transit Milestone Completeness", "higher", "percent", "Percent of in-transit milestones received."),
            ("Delivered Milestone Completeness", "higher", "percent", "Percent of delivered milestones received / completed."),
            ("Latency under 1 hr", "lower", "percent", "Share of milestone latencies that are under 1 hour (lower buckets dominate = better timeliness)."),
            ("Latency under 2 hr", "lower", "percent", "Share of milestone latencies under 2 hours."),
            ("Latency bw 1-3 hrs", "lower", "percent", "Share of milestone latencies between 1–3 hours."),
            ("Latency bw 3-8 hrs", "lower", "percent", "Share of milestone latencies between 3–8 hours."),
            ("Latency bw 8-24hrs", "lower", "percent", "Share of milestone latencies between 8–24 hours."),
            ("Latency bw 24-72hrs", "lower", "percent", "Share of milestone latencies between 24–72 hours."),
            ("Latency over 72hrs", "lower", "percent", "Share of milestone latencies over 72 hours."),
            ("Avg Latency Mins", "lower", "number", "Average latency across milestones in minutes (lower is better)."),
        ],
        "volume_col": "Volume",
        "carrier_col": "Carrier Name",
        "help": {
            "product": "Run the same logic for different products; only the metric columns change.",
            "master": "The complete list of p44 carriers for the selected product, with performance metrics.",
            "customer": "Carriers that your customer already uses (the comparison baseline).",
            "use_absolute": "Switch to threshold mode. In comparative mode, a candidate passes each metric if it beats/ties ANY customer carrier on that metric.",
            "allow_equal_abs": "When ON, threshold comparisons allow equality (≥ for higher-is-better; ≤ for lower-is-better).",
            "num_suggestions": "How many suggested carriers to include in the final output.",
            "order_input": "Priority order for metrics (1 = highest). Candidate must pass each metric in this order vs at least one customer carrier.",
        },
    },

    # ===== Parcel (your schema) =====
    "Parcel": {
        "metrics": [
            ("Data Availability", "higher", "percent", "Percent of parcel shipments with any usable tracking data."),
            ("Milestone Achieved %", "higher", "percent", "Percent of expected milestone events successfully recorded."),
            ("Latency Percentage", "higher", "percent", "Percent of milestones within your acceptable latency window."),
            ("Pickup Milestone", "higher", "percent", "Percent of shipments with a pickup milestone received."),
            ("Departed Milestone", "higher", "percent", "Percent of shipments with a departure milestone received."),
            ("Out for Delivery Milestone", "higher", "percent", "Percent of shipments with OOD milestone received."),
            ("Arrived Milestone", "higher", "percent", "Percent of shipments with arrival milestone received."),
            ("Delivered Milestone", "higher", "percent", "Percent of shipments with delivered milestone received."),
            ("Volume Tracked", "higher", "number", "Count of shipments tracked (higher indicates broader coverage)."),
            ("Impact - Milestone Achieved %", "higher", "number", "Estimated incremental improvement for Milestone Achieved %."),
            ("Impact - Latency Percentage", "higher", "number", "Estimated incremental improvement for Latency Percentage."),
            ("Impact - Data Availability", "higher", "number", "Estimated incremental improvement for Data Availability."),
        ],
        "volume_col": "Volume Created",
        "carrier_col": "Carrier Name",
        "help": {
            "product": "Parcel carriers & parcel metrics.",
            "master": "All parcel carriers with performance metrics (MASTER).",
            "customer": "Parcel carriers your customer already uses (CUSTOMER).",
            "use_absolute": "Switch to threshold mode with your typed targets per metric.",
            "allow_equal_abs": "Count equals as meeting the threshold.",
            "num_suggestions": "How many suggestions to output.",
            "order_input": "Priority order for parcel metrics.",
        },
    },

    # ===== Ocean (your schema) =====
    "Ocean": {
        "metrics": [
            ("Completeness 6 - p44", "higher", "percent", "Coverage of 6 standard ocean events in p44."),
            ("Completeness 8 - p44", "higher", "percent", "Coverage of 8 standard ocean events in p44."),
            ("p44 6 Uplift", "higher", "number", "Incremental coverage uplift vs baseline (6-event set)."),
            ("p44 8 Uplift", "higher", "number", "Incremental coverage uplift vs baseline (8-event set)."),
            ("1-Empty Pickup %", "higher", "percent", "Share of containers with Empty Pickup milestone."),
            ("2-Gate In %", "higher", "percent", "Share with Gate In milestone."),
            ("3-Container Loaded %", "higher", "percent", "Share with Container Loaded milestone."),
            ("4-Vessel Depart POL - p44", "higher", "percent", "Share with Vessel Departure at POL milestone (p44 signal)."),
            ("5-Vessel Arrival POD - p44", "higher", "percent", "Share with Vessel Arrival at POD milestone (p44 signal)."),
            ("6-Container Discharge POD %", "higher", "percent", "Share with Container Discharge at POD milestone."),
            ("7-Gate Out %", "higher", "percent", "Share with Gate Out milestone."),
            ("8-Empty Return %", "higher", "percent", "Share with Empty Return milestone."),
            ("Arrival at POD Uplift", "higher", "number", "Incremental arrival event coverage uplift (all-time)."),
            ("Departure from POL Uplift", "higher", "number", "Incremental departure event coverage uplift (all-time)."),
            ("Under 6h - p44", "higher", "percent", "Share of latency under 6 hours (p44 signal)."),
            ("Under 12h - p44", "higher", "percent", "Share of latency under 12 hours (p44 signal)."),
            ("Under 24h- p44", "higher", "percent", "Share of latency under 24 hours (p44 signal)."),
            ("24-48h Latency - p44", "higher", "percent", "Share of latency 24–48 hours (p44 signal)."),
            ("48-72h Latency - p44", "higher", "percent", "Share of latency 48–72 hours (p44 signal)."),
            ("Over 72h - p44", "higher", "percent", "Share of latency over 72 hours (p44 signal)."),
            ("Departure from POL - p44 Uplift (<12)", "higher", "number", "Departure event coverage uplift with <12h latency."),
            ("Arrival at POD - p44 Uplift (<12)", "higher", "number", "Arrival event coverage uplift with <12h latency."),
        ],
        "volume_col": "Shipments",
        "carrier_col": "Carrier Name",
        "help": {
            "product": "Ocean carriers & ocean metrics.",
            "master": "All ocean carriers with performance metrics (MASTER).",
            "customer": "Ocean carriers your customer already uses (CUSTOMER).",
            "use_absolute": "Switch to threshold mode with your typed targets per metric.",
            "allow_equal_abs": "Count equals as meeting the threshold.",
            "num_suggestions": "How many suggestions to output.",
            "order_input": "Priority order for ocean metrics.",
        },
    },
}

# =========================
# Page shell
# =========================
st.set_page_config(page_title="Carrier Suggestion Hub", layout="wide")
st.title("Carrier Recommendation Hub")
st.caption("Pick a product, upload MASTER & CUSTOMER CSVs, and generate out-of-tenant suggestions.")

def get_help(prod_key: str, field: str, default: str = "") -> str:
    return PRODUCTS.get(prod_key, {}).get("help", {}).get(field, default)

product = st.selectbox(
    "Choose Product",
    options=list(PRODUCTS.keys()),
    index=0,
    help=get_help("Last Mile", "product", "Select which product’s metrics to use.")
)
cfg = PRODUCTS[product]
metric_catalog = cfg["metrics"]
carrier_col = cfg["carrier_col"]
volume_col = cfg.get("volume_col")

st.markdown(f"**Selected Product:** `{product}`")
if not metric_catalog:
    st.warning("This product has no metrics configured yet. Edit the PRODUCTS config at the top to add metrics.")
st.divider()

# =========================
# Uploads
# =========================
st.header("1) Upload Files")
master_file = st.file_uploader(
    "Upload MASTER dataset (all p44 carriers)",
    type=["csv"],
    key="master",
    help=get_help(product, "master", "MASTER: full carrier list for the product (with metrics).")
)
customer_file = st.file_uploader(
    "Upload CUSTOMER carrier dataset (already used carriers)",
    type=["csv"],
    key="customer",
    help=get_help(product, "customer", "CUSTOMER: carriers your customer already uses (comparison baseline).")
)

# =========================
# Parameters
# =========================
st.header("2) Parameters")
use_absolute = st.checkbox(
    "Use absolute thresholds mode (override comparative logic)",
    value=False,
    help=get_help(product, "use_absolute", "Type numeric targets per metric; suggestions must meet them.")
)
allow_equal_abs = st.checkbox(
    "Absolute mode: allow equals to pass",
    value=True,
    help=get_help(product, "allow_equal_abs", "When ON, thresholds allow equality (≥ higher-is-better; ≤ lower-is-better).")
)
num_suggestions = st.number_input(
    "How many top suggestions do you want?",
    min_value=1, value=10, step=1, format="%d",
    help=get_help(product, "num_suggestions", "How many suggested carriers to include in the output.")
)

auto_run = st.checkbox("Auto-run on changes", value=True)
run_clicked = st.button("Run")

# =========================
# Comparative (default) UI
# =========================
if not use_absolute:
    metric_labels = [f"{i+1}. {name} ({direction})" for i, (name, direction, *_rest) in enumerate(metric_catalog)]
    st.markdown("**Select metric priority order.** Enter numbers in comma-separated order (e.g., `1,2,3`):")
    st.text("\n".join(metric_labels))
    default_order = ",".join(str(i+1) for i in range(min(3, len(metric_catalog)))) if metric_catalog else ""
    order_input = st.text_input(
        "Metric priority order",
        value=default_order,
        help=get_help(product, "order_input", "Priority order of metrics for comparative (cascading) logic.")
    )
    selected_indices = []
    try:
        selected_indices = [int(x.strip()) - 1 for x in order_input.split(",") if x.strip()]
    except Exception:
        st.error("Invalid metric order input; use numbers like 1,2,3")
    # (col, direction)
    selected_metrics = [(metric_catalog[i][0], metric_catalog[i][1]) for i in selected_indices if 0 <= i < len(metric_catalog)]
else:
    # ===== Absolute thresholds mode: plain text inputs, shown only when checked =====
    st.markdown("**Absolute thresholds mode** — tick metrics and type thresholds (free text, decimals allowed, `%` optional).")

    # initialize defaults for current product once per session
    prod_key = f"abs_init__{product}"
    if prod_key not in st.session_state:
        for name, direction, vtype, *_h in metric_catalog:
            st.session_state.setdefault(f"abs_chk__{product}__{name}", False)
            st.session_state.setdefault(f"abs_txt__{product}__{name}", "95.00" if vtype == "percent" else "60.00")
        st.session_state[prod_key] = True

    abs_selected, abs_thresholds = [], {}
    left, right = st.columns(2)
    half = (len(metric_catalog) + 1) // 2

    def parse_threshold_str(s: str, vtype: str):
        if s is None: return None
        s = str(s).strip()
        if s == "": return None
        s = s.replace("%", "").replace(",", "")
        try:
            val = float(s)
        except Exception:
            return None
        if vtype == "percent" and (val < 0 or val > 100):
            return None
        return val

    for i, entry in enumerate(metric_catalog):
        # Support both 3-tuple and 4-tuple entries
        if len(entry) == 4:
            name, direction, vtype, m_help = entry
        else:
            name, direction, vtype = entry
            m_help = ""
        container = left if i < half else right
        with container:
            st.checkbox(
                f"{name} ({'higher' if direction=='higher' else 'lower'} is better)",
                key=f"abs_chk__{product}__{name}",
                help=m_help
            )
            if st.session_state.get(f"abs_chk__{product}__{name}", False):
                st.text_input(
                    f"Threshold • {name}",
                    key=f"abs_txt__{product}__{name}",
                    placeholder=("e.g., 95 or 95.00" if vtype == "percent" else "e.g., 60 or 60.00"),
                    help=f"Type a number{ ' between 0 and 100' if vtype=='percent' else '' }. '%' allowed."
                )
                val = parse_threshold_str(st.session_state.get(f"abs_txt__{product}__{name}", ""), vtype)
                if val is not None:
                    abs_selected.append((name, direction))
                    abs_thresholds[name] = float(val)
                else:
                    st.caption(":red[Enter a valid number{}]".format(" (0–100)" if vtype == "percent" else ""))

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

def drop_unwanted_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Remove columns like 'Unnamed: 0' and empty/blank-named columns."""
    if df is None or df.empty:
        return df
    cols_to_drop = []
    for c in df.columns:
        c_str = "" if c is None else str(c)
        if c_str.strip() == "":
            cols_to_drop.append(c)
        if re.match(r"^Unnamed:?\s*0*$", c_str):
            cols_to_drop.append(c)
    if cols_to_drop:
        df = df.drop(columns=list(set(cols_to_drop)), errors="ignore")
    return df

def prep(df: pd.DataFrame, product_cfg: dict) -> pd.DataFrame:
    """Standardize columns, strip %, coerce numerics based on value_type; drop 'Unnamed' cols."""
    df = df.copy()
    df = drop_unwanted_columns(df)
    df.columns = df.columns.str.strip()

    if product_cfg["carrier_col"] in df.columns:
        df[product_cfg["carrier_col"]] = df[product_cfg["carrier_col"]].astype(str).str.strip()

    vcol = product_cfg.get("volume_col")
    if vcol and vcol in df.columns:
        df[vcol] = (
            df[vcol].astype(str).str.replace(",", "", regex=False)
            .str.extract(r"(\d+\.?\d*)")[0].astype(float)
        )

    # Clean configured metric columns
    for entry in product_cfg["metrics"]:
        name, _direction, vtype = entry[:3]
        if name in df.columns:
            if vtype == "percent":
                df[name] = df[name].apply(clean_percent)
            else:
                df[name] = pd.to_numeric(df[name], errors="coerce")

    df = drop_unwanted_columns(df)
    return df

def engine_available(module_name: str) -> bool:
    return importlib.util.find_spec(module_name) is not None

def to_excel_bytes_or_none(suggestions_df: pd.DataFrame, legend_df: pd.DataFrame):
    """
    Try to create an Excel file in-memory.
    Returns (bytes, mime) if successful, else (None, None) to indicate fallback to CSV is needed.
    """
    output = BytesIO()
    for engine in ("openpyxl", "xlsxwriter"):
        if engine_available(engine):
            try:
                with pd.ExcelWriter(output, engine=engine) as writer:
                    drop_unwanted_columns(suggestions_df).to_excel(writer, index=False, sheet_name="Suggestions")
                    drop_unwanted_columns(legend_df).to_excel(writer, index=False, sheet_name="Legend")
                output.seek(0)
                return output.getvalue(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            except Exception:
                output.seek(0)
                output.truncate(0)
                continue
    return None, None

# ===== Comparative mode (ANY-per-metric, with Δ) =====
def make_output_comparative(master_df, customer_df, metrics, suggestion_count, carrier_col_name):
    if not metrics:
        return pd.DataFrame()

    master_df = drop_unwanted_columns(master_df)
    customer_df = drop_unwanted_columns(customer_df)

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
                    if pd.isna(cust_val):
                        continue
                    is_better = (sugg_val > cust_val) if direction == "higher" else (sugg_val < cust_val)
                    is_equal = abs(sugg_val - cust_val) < 1e-6
                    delta = (sugg_val - cust_val) if direction == "higher" else (cust_val - sugg_val)
                    delta_str = f"{delta:+.2f}" if pd.notna(delta) else "NA"
                    tag = "(B)" if is_better else ("(E)" if is_equal else "")
                    if tag:
                        metric_label = f"{col} {tag} (Δ {delta_str})"
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
    df = drop_unwanted_columns(df)
    df.insert(0, "SL No", range(1, len(df) + 1))
    for col in df.columns:
        if str(col).lower().startswith("carrier"):
            df[col] = df[col].astype(str).str.title()
    df = drop_unwanted_columns(df)
    return df

# ===== Absolute thresholds mode (includes Δ) =====
def make_output_absolute_thresholds(master_df, customer_df, metrics_with_dir, thresholds, allow_equal, suggestion_count, carrier_col_name):
    if not metrics_with_dir:
        return pd.DataFrame()

    master_df = drop_unwanted_columns(master_df)
    customer_df = drop_unwanted_columns(customer_df)

    def pass_threshold(val, thr, direction, allow_eq):
        if pd.isna(val) or pd.isna(thr):
            return False
        if direction == "higher":
            return (val > thr) or (allow_eq and val >= thr)
        else:
            return (val < thr) or (allow_eq and val <= thr)

    unused = master_df[~master_df[carrier_col_name].str.lower().isin(customer_df[carrier_col_name].str.lower())].copy()

    # Identify "bad" customer carriers (fail thresholds)
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
                        reasons.append(f"{col} {tag} (Δ {delta:+.2f})")
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
    df = drop_unwanted_columns(df)
    df.insert(0, "SL No", range(1, len(df) + 1))
    for col in df.columns:
        if str(col).lower().startswith("carrier"):
            df[col] = df[col].astype(str).str.title()
    df = drop_unwanted_columns(df)
    return df

# =========================
# Run
# =========================
st.header("3) Generate Suggestions")

def compute_and_show():
    if master_file is None or customer_file is None:
        st.info("Upload both files to continue.")
        return

    if use_absolute and len(selected_metrics) == 0:
        st.info("Tick metrics and type thresholds in Absolute mode.")
        return
    if (not use_absolute) and len(selected_metrics) == 0:
        st.info("Enter a valid metric priority order with at least one metric.")
        return

    master_df = prep(pd.read_csv(master_file), cfg)
    customer_df = prep(pd.read_csv(customer_file), cfg)

    if carrier_col not in master_df.columns or carrier_col not in customer_df.columns:
        st.error(f"Both files must include a `{carrier_col}` column.")
        return

    missing_in_master = [entry[0] for entry in metric_catalog if (entry[0] not in master_df.columns)]
    missing_in_customer = [entry[0] for entry in metric_catalog if (entry[0] not in customer_df.columns)]
    if missing_in_master:
        st.warning(f"MASTER missing columns (not fatal if not selected): {', '.join(missing_in_master)}")
    if missing_in_customer:
        st.warning(f"CUSTOMER missing columns (not fatal if not selected): {', '.join(missing_in_customer)}")

    with st.spinner("Crunching suggestions..."):
        if not use_absolute:
            output_df = make_output_comparative(master_df, customer_df, selected_metrics, num_suggestions, carrier_col)
        else:
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
        output_df = drop_unwanted_columns(output_df)
        st.dataframe(output_df, use_container_width=True)

        legend_rows = [
            ["Column", "Explanation"],
            ["Carrier N", "Customer carrier outperformed (comparative) or compared against (absolute)."],
            ["Reason N", "Metrics with tags: (B)=Better, (E)=Equal; Δ shows improvement vs that customer (positive is better)."]
        ]
        legend_df = pd.DataFrame(legend_rows[1:], columns=legend_rows[0])
        st.subheader("Legend")
        st.table(legend_df)

        # Try Excel; if not possible, fall back to CSVs
        excel_bytes, mime = to_excel_bytes_or_none(output_df, legend_df)
        if excel_bytes is not None:
            st.download_button(
                "Download Suggestions (Excel)",
                excel_bytes,
                file_name=f"{product.replace(' ','_')}_Top_{num_suggestions}_Suggestions.xlsx",
                mime=mime
            )
        else:
            st.warning("Excel engines not available in this environment. Providing CSV downloads instead.")
            st.download_button(
                "Download Suggestions (CSV)",
                output_df.to_csv(index=False).encode("utf-8"),
                file_name=f"{product.replace(' ','_')}_Suggestions.csv",
                mime="text/csv"
            )
            st.download_button(
                "Download Legend (CSV)",
                legend_df.to_csv(index=False).encode("utf-8"),
                file_name="Legend.csv",
                mime="text/csv"
            )

# Auto-run or manual run
if auto_run or run_clicked:
    compute_and_show()
