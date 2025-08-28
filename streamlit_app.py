# streamlit_app.py
# Multi-product Streamlit app (Last Mile ready).
# - Comparative mode: ANY-per-metric (your original), adds Δ in Reasons.
# - Absolute mode: plain text inputs per selected metric (no +/-), shown only when checkbox is ticked.
# - Drops 'Unnamed: 0' and blank columns.
# - Excel writer: try openpyxl/xlsxwriter; fallback to CSV downloads if neither is available.

import streamlit as st
import pandas as pd
from io import BytesIO
import importlib.util
import re

# =========================
# Product Config (EDIT ME)
# =========================
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
        "volume_col": "Volume",
        "carrier_col": "Carrier Name",
    },
    # Fill when ready:
    "Parcel": {"metrics": [], "volume_col": "Volume", "carrier_col": "Carrier Name"},
    "Ocean":  {"metrics": [], "volume_col": "Volume", "carrier_col": "Carrier Name"},
}

# =========================
# App Shell
# =========================
st.set_page_config(page_title="Carrier Suggestion Hub", layout="wide")
st.title("Carrier Recommendation Hub")
st.caption("Pick a product, upload MASTER & CUSTOMER CSVs, and generate out-of-tenant suggestions.")

product = st.selectbox("Choose Product", options=list(PRODUCTS.keys()), index=0)
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
master_file = st.file_uploader("Upload MASTER dataset (all p44 carriers)", type=["csv"], key="master")
customer_file = st.file_uploader("Upload CUSTOMER carrier dataset (already used carriers)", type=["csv"], key="customer")

# =========================
# Parameters
# =========================
st.header("2) Parameters")
use_absolute = st.checkbox("Use absolute thresholds mode (override comparative logic)", value=False)
allow_equal_abs = st.checkbox("Absolute mode: allow equals to pass", value=True, help="When ON, ≥ for higher metrics and ≤ for lower metrics.")
num_suggestions = st.number_input("How many top suggestions do you want?", min_value=1, value=10, step=1, format="%d")

auto_run = st.checkbox("Auto-run on changes", value=True)
run_clicked = st.button("Run")

# =========================
# Comparative (default) UI
# =========================
if not use_absolute:
    metric_labels = [f"{i+1}. {name} ({direction})" for i, (name, direction, _vt) in enumerate(metric_catalog)]
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
    # ===== Absolute thresholds mode: plain text fields shown only when metric is checked =====
    st.markdown("**Absolute thresholds mode** — tick metrics and type thresholds (free text, decimals allowed, `%` optional).")

    # initialize session defaults once
    if "abs_init_done" not in st.session_state:
        for name, direction, vtype in metric_catalog:
            st.session_state.setdefault(f"abs_chk_{name}", False)
            st.session_state.setdefault(f"abs_txt_{name}", "95.00" if vtype == "percent" else "60.00")
        st.session_state["abs_init_done"] = True

    abs_selected, abs_thresholds = [], {}
    left, right = st.columns(2)
    half = (len(metric_catalog) + 1) // 2

    def parse_threshold_str(s: str, vtype: str):
        if s is None:
            return None
        s = str(s).strip()
        if s == "":
            return None
        s = s.replace("%", "").replace(",", "")
        try:
            val = float(s)
        except Exception:
            return None
        # soft guard for percents
        if vtype == "percent" and (val < 0 or val > 100):
            return None
        return val

    for i, (name, direction, vtype) in enumerate(metric_catalog):
        container = left if i < half else right
        with container:
            st.checkbox(
                f"{name} ({'higher' if direction=='higher' else 'lower'} is better)",
                key=f"abs_chk_{name}"
            )
            if st.session_state.get(f"abs_chk_{name}", False):
                st.text_input(
                    f"Threshold • {name}",
                    key=f"abs_txt_{name}",
                    placeholder="e.g., 95 or 95.00" if vtype == "percent" else "e.g., 60 or 60.00",
                )
                # build selections as you type; no +/- controls, plain text only
                val = parse_threshold_str(st.session_state.get(f"abs_txt_{name}", ""), vtype)
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
    for name, _direction, vtype in product_cfg["metrics"]:
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

    missing_in_master = [m[0] for m in metric_catalog if (m[0] not in master_df.columns)]
    missing_in_customer = [m[0] for m in metric_catalog if (m[0] not in customer_df.columns)]
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
            ["Carrier N", "Customer carrier outperformed (comparative mode) or compared against (absolute mode)."],
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

if auto_run or run_clicked:
    compute_and_show()
