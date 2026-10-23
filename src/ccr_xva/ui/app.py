"""Streamlit desk view. Numbers come from the API, which calls the engines."""

from __future__ import annotations

import os

import httpx
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

API = os.getenv("CCR_API_URL", "http://localhost:8000/api/v1")
PAGES = [
    ("Upload", "upload"),
    ("Exposure", "exposure"),
    ("XVA what-if", "xva"),
    ("Chat", "chat"),
    ("Check", "check"),
]


def run() -> None:
    import sys
    from pathlib import Path

    from streamlit.web import cli as stcli

    sys.argv = ["streamlit", "run", str(Path(__file__).resolve()), "--server.port", "8501", "--server.address", "0.0.0.0"]
    stcli.main()


def _post(path: str, payload: dict | None = None, files=None) -> dict:
    response = httpx.post(f"{API}{path}", json=payload, files=files, timeout=120)
    if response.is_error:
        detail = response.text
        try:
            detail = response.json().get("detail", detail)
        except Exception:
            pass
        raise httpx.HTTPStatusError(str(detail), request=response.request, response=response)
    return response.json()


def _chart(chart: dict | None) -> None:
    if not chart:
        return
    figure = go.Figure(data=chart.get("data", []), layout=chart.get("layout", {}))
    figure.update_layout(
        template="plotly_white",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font={"family": "Segoe UI, sans-serif", "color": "#1c2430"},
        margin={"l": 40, "r": 16, "t": 48, "b": 40},
    )
    st.plotly_chart(figure, use_container_width=True)


def _fmt_rate(value: float) -> str:
    text = f"{value:.3f}".rstrip("0").rstrip(".")
    if "." not in text:
        text += ".0"
    return text


def _header() -> str:
    if "page" not in st.session_state:
        st.session_state.page = PAGES[0][0]
    brand, *nav = st.columns([1.7, 0.85, 0.9, 1.15, 0.65, 0.7], vertical_alignment="center")
    with brand:
        st.markdown(
            """
            <div class="brand-block">
              <div class="brand">CCR-XVA Monitor</div>
              <div class="tagline">Counterparty credit risk desk. Engines compute every number.</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    for column, (name, slug) in zip(nav, PAGES, strict=True):
        selected = st.session_state.page == name
        key = f"nav-{slug}-on" if selected else f"nav-{slug}"
        with column:
            if st.button(name, key=key, use_container_width=True):
                st.session_state.page = name
                st.rerun()
    return st.session_state.page


st.set_page_config(page_title="CCR-XVA Monitor", layout="wide", initial_sidebar_state="collapsed")
st.markdown(
    """
    <style>
      .stApp { background: #f3f5f8; color: #1c2430; }
      .block-container { padding-top: 1.1rem; padding-bottom: 2.5rem; max-width: 1180px; }
      header[data-testid="stHeader"], .stAppHeader { display: none; }
      [data-testid="stToolbar"] { display: none; }
      [data-testid="stDecoration"] { display: none; }
      footer { display: none; }
      .brand { font-size: 1.55rem; font-weight: 650; letter-spacing: -0.02em; color: #0e2a43; }
      .tagline { color: #5c6b7a; font-size: 0.92rem; margin-top: 0.15rem; }
      div[class*="st-key-nav-"] button {
        background: #1d4ed8 !important;
        color: #ffffff !important;
        border: 1px solid #1d4ed8 !important;
        border-radius: 6px;
        font-weight: 600;
        white-space: nowrap;
        min-height: 2.4rem;
      }
      div[class*="st-key-nav-"] button:hover { background: #1e40af !important; border-color: #1e40af !important; }
      div[class*="st-key-nav-"][class*="-on"] button,
      div[class*="st-key-nav-"][class*="-on"] button:hover {
        background: #15803d !important;
        border-color: #15803d !important;
        color: #ffffff !important;
      }
      button[data-testid="stBaseButton-primary"] {
        background: #0e2a43 !important;
        border-color: #0e2a43 !important;
        color: #ffffff !important;
      }
      button[data-testid="stBaseButton-primary"]:hover { background: #16395a !important; border-color: #16395a !important; }
      div[data-testid="stVerticalBlockBorderWrapper"] {
        background: #ffffff;
        border: 1px solid #e1e6ee;
        border-radius: 10px;
      }
      h2, h3 { color: #0e2a43; letter-spacing: -0.02em; }
      .stButton > button[kind="primary"], .stButton > button {
        border-radius: 6px;
      }
    </style>
    """,
    unsafe_allow_html=True,
)

page = _header()
st.divider()

if page == "Upload":
    st.subheader("Book")
    st.caption("Load the sample portfolio, or upload a trade file and a cash CSA.")
    sample, upload = st.columns(2)
    with sample:
        with st.container(border=True):
            st.markdown("**Sample book**")
            st.caption("USD interest-rate swaps and FX forwards. An existing CSA is left in place.")
            if st.button("Load sample book", type="primary"):
                try:
                    st.json(_post("/sample"))
                except httpx.HTTPError as exc:
                    st.error(str(exc))
    with upload:
        with st.container(border=True):
            st.markdown("**Trade file**")
            st.caption("CSV or JSON. Dates may be YYYY-MM-DD or M/D/YYYY.")
            trades = st.file_uploader("Trade CSV or JSON", type=["csv", "json"], label_visibility="collapsed")
            if trades is not None and st.button("Upload trades", type="primary"):
                files = {"file": (trades.name, trades.getvalue(), "text/csv")}
                try:
                    st.json(_post("/trades/upload", files=files))
                except httpx.HTTPError as exc:
                    st.error(str(exc))
    with st.container(border=True):
        st.markdown("**Collateral agreement**")
        st.caption("Example: daily cash collateral, 0 threshold, 10% MTA")
        with st.form("csa"):
            csa_id = st.text_input("CSA id", "CSA-UI")
            netting_set_id = st.text_input("Netting set", "NS1")
            text = st.text_input("CSA text", "daily cash collateral, 0 threshold, 10% MTA")
            notional = st.number_input("Notional for percent MTA", value=10_000_000.0, step=1_000_000.0)
            if st.form_submit_button("Save CSA", type="primary"):
                try:
                    st.json(
                        _post(
                            "/csas",
                            {
                                "text": text,
                                "csa_id": csa_id,
                                "netting_set_id": netting_set_id,
                                "notional": notional,
                            },
                        )
                    )
                except httpx.HTTPError as exc:
                    st.error(str(exc))

elif page == "Exposure":
    st.subheader("Exposure")
    st.caption("Expected exposure and potential future exposure for one netting set.")
    with st.container(border=True):
        netting_col, path_col, action_col = st.columns([2, 3, 1], vertical_alignment="bottom")
        netting_set_id = netting_col.text_input("Netting set", "NS1")
        paths = path_col.slider("Paths", min_value=50, max_value=2000, value=200, step=50)
        run_exposure = action_col.button("Calculate", type="primary")
    if run_exposure:
        try:
            result = _post(
                "/calculate/exposure",
                {"netting_set_id": netting_set_id, "scenario": {"as_of": "2026-10-05", "n_paths": paths}},
            )
            profile = result["profile"]
            peak = max(profile["pfe_95"]) if profile["pfe_95"] else 0.0
            metric_ee, metric_pfe, metric_id = st.columns(3)
            metric_ee.metric("EPE", f"{profile['epe']:,.0f} USD")
            metric_pfe.metric("Peak PFE95", f"{peak:,.0f} USD")
            metric_id.metric("Calculation", profile["calculation_id"][:8])
            _chart(result.get("chart"))
            st.dataframe(
                pd.DataFrame(
                    {"date": profile["dates"], "ee": profile["ee"], "pfe_95": profile["pfe_95"], "pfe_99": profile["pfe_99"]}
                ),
                use_container_width=True,
                hide_index=True,
            )
            if profile.get("drivers"):
                st.markdown("**Risk drivers**")
                st.dataframe(pd.DataFrame(profile["drivers"]), use_container_width=True, hide_index=True)
        except httpx.HTTPError as exc:
            st.error(str(exc))

elif page == "XVA what-if":
    st.subheader("XVA")
    st.caption("Approximate unilateral CVA, DVA, and teaching FVA.")
    with st.container(border=True):
        netting_set_id = st.text_input("Netting set", "NS1", key="xva-ns")
        threshold_col, recovery_col = st.columns(2)
        threshold = threshold_col.number_input("Threshold override", value=0.0, step=100_000.0)
        recovery = recovery_col.slider("Recovery", min_value=0.0, max_value=1.0, value=0.40, step=0.05)
        run_xva = st.button("Calculate XVA", type="primary")
    if run_xva:
        try:
            result = _post(
                "/calculate/xva",
                {
                    "netting_set_id": netting_set_id,
                    "threshold_override": threshold,
                    "recovery_override": recovery,
                    "save_latest": False,
                    "scenario": {"as_of": "2026-10-05", "n_paths": 200},
                },
            )
            xva = result["xva"]
            cva_col, dva_col, fva_col, total_col = st.columns(4)
            cva_col.metric("CVA", f"{xva.get('cva', 0):,.0f}")
            dva_col.metric("DVA", f"{xva.get('dva') or 0:,.0f}")
            fva_col.metric("FVA", f"{xva.get('fva') or 0:,.0f}")
            total_col.metric("Total", f"{xva.get('total_xva', 0):,.0f}")
            with st.expander("Full result"):
                st.json(xva)
        except httpx.HTTPError as exc:
            st.error(str(exc))

elif page == "Check":
    st.subheader("Desk check")
    st.caption("Confirms a live calculation, then recalls it from a new session, and runs the evaluation.")
    if st.button("Run checks", type="primary"):
        try:
            core = _post(
                "/query",
                {
                    "query": "What is the current peak PFE for ABC Bank?",
                    "session_id": "public-check",
                    "include_charts": False,
                    "as_of": "2026-10-05",
                    "n_paths": 40,
                },
            )
            memory = _post(
                "/query",
                {
                    "query": "Recall the last calculation for ABC Bank",
                    "session_id": "fresh-session",
                    "include_charts": False,
                    "as_of": "2026-10-05",
                    "n_paths": 20,
                },
            )
            report = _post("/eval/run")
        except httpx.HTTPError as exc:
            st.error(str(exc))
        else:
            core_col, memory_col, eval_col = st.columns(3)
            core_ok = bool(core.get("answer")) and not core.get("refused") and bool(core.get("numeric_values"))
            memory_ok = "Stored peak PFE" in memory.get("answer", "") or "Stored CVA" in memory.get("answer", "")
            eval_ok = bool(report.get("passed"))
            core_col.metric("Core calculation", "Pass" if core_ok else "Fail")
            memory_col.metric("Memory", "Pass" if memory_ok else "Fail")
            eval_col.metric("Evaluation", "Pass" if eval_ok else "Fail")
            failure = report.get("failure_set") or {}
            accuracy = failure.get("handoff_accuracy")
            baseline_accuracy = failure.get("baseline_handoff_accuracy")
            misroute_count = failure.get("misroute_count")
            baseline_misroutes = failure.get("baseline_misroute_count")
            handoff_col, misroute_col = st.columns(2)
            if accuracy is not None and baseline_accuracy is not None:
                handoff_col.metric("Handoff accuracy", _fmt_rate(accuracy), delta=round(accuracy - baseline_accuracy, 3))
            if misroute_count is not None and baseline_misroutes is not None:
                misroute_col.metric(
                    "Misroutes",
                    misroute_count,
                    delta=misroute_count - baseline_misroutes,
                    delta_color="inverse",
                )
            cases = failure.get("cases") or []
            if cases:
                st.dataframe(
                    pd.DataFrame(
                        [
                            {
                                "Question": case["query"],
                                "Expected owner": case["expected_owner"],
                                "Actual owner": case["owner"],
                                "Category": case["category"],
                            }
                            for case in cases
                        ]
                    ),
                    use_container_width=True,
                    hide_index=True,
                )
            st.caption("Open issues. These counts are not a pass or a fail.")
            false_col, drift_col = st.columns(2)
            false_col.metric("False refusals", failure.get("false_refusal_count", 0))
            drift_col.metric("Snapshot drift", failure.get("snapshot_drift_count", 0))
            st.markdown(core.get("answer", ""))
            st.markdown(memory.get("answer", ""))
            with st.expander("Evaluation detail"):
                st.json(report)
else:
    st.subheader("Ask")
    st.caption("The desk quotes the engines, the methodology notes, a stored snapshot, or a live market quote.")
    with st.container(border=True):
        question = st.text_input("Question", "What is the current peak PFE for ABC Bank and the main risk drivers?")
        ask = st.button("Ask", type="primary")
    if ask and question:
        try:
            result = _post(
                "/query",
                {"query": question, "session_id": "streamlit", "include_charts": True, "as_of": "2026-10-05", "n_paths": 120},
            )
            if result.get("refused"):
                st.warning(result["answer"])
            else:
                st.markdown(result["answer"])
            _chart(result.get("chart"))
            if result.get("numeric_values"):
                st.dataframe(pd.DataFrame(result["numeric_values"]), use_container_width=True, hide_index=True)
            if result.get("citations"):
                with st.expander("Citations"):
                    st.json(result["citations"])
        except httpx.HTTPError as exc:
            st.error(str(exc))
