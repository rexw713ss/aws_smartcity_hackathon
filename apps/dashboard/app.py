"""Temporary Streamlit UI for the offline Youth Compass vertical slice."""

from __future__ import annotations

import html
import os
from typing import Any

import pandas as pd  # type: ignore[import-untyped]
import streamlit as st

from apps.dashboard.api_client import ApiError, YouthCompassApi

st.set_page_config(
    page_title="新北青年政策羅盤",
    page_icon="🧭",
    layout="wide",
    initial_sidebar_state="expanded",
)

_CSS = """
<style>
  :root { --ink:#14231e; --muted:#607069; --paper:#f5f2e9; --card:#fffefa;
          --green:#176b52; --lime:#cbe56a; --orange:#e47742; --line:#deddd3; }
  .stApp { background: var(--paper); color: var(--ink); }
  [data-testid="stSidebar"] { background: #14231e; }
  [data-testid="stSidebar"] * { color: #f6f3e9; }
  [data-testid="stSidebar"] input { color: #14231e; }
  [data-testid="stHeader"] { background: transparent; }
  .block-container { padding-top: 2.1rem; max-width: 1440px; }
  h1, h2, h3 { color: var(--ink); letter-spacing: -0.035em; }
  h1 { font-size: clamp(2.2rem, 4vw, 4.4rem) !important; line-height: .96 !important; }
  .eyebrow { color: var(--green); font-size:.75rem; font-weight:800; letter-spacing:.16em;
             text-transform:uppercase; margin-bottom:.75rem; }
  .hero-copy { color:var(--muted); font-size:1.08rem; max-width:760px; margin:.5rem 0 1.5rem; }
  .status-pill { display:inline-flex; align-items:center; gap:.5rem; border:1px solid #31564a;
                 border-radius:999px; padding:.35rem .7rem; font-size:.78rem; }
  .status-dot { width:.52rem; height:.52rem; border-radius:50%; background:#80d39b; }
  .metric-card { background:var(--card); border:1px solid var(--line); border-radius:14px;
                 min-height:142px; padding:1.15rem 1.2rem;
                 box-shadow:0 8px 28px rgba(20,35,30,.04); }
  .metric-label { color:var(--muted); font-size:.74rem; font-weight:750; letter-spacing:.08em;
                  text-transform:uppercase; }
  .metric-value { color:var(--ink); font-size:2rem; font-weight:760; margin:.55rem 0 .15rem; }
  .metric-note { color:var(--muted); font-size:.82rem; }
  .section-note { color:var(--muted); margin-top:-.5rem; margin-bottom:1rem; }
  .empty { background:var(--card); border:1px dashed #a7aaa1; border-radius:14px;
           padding:2rem; text-align:center; color:var(--muted); }
  .review { background:#fffefa; border-left:4px solid var(--orange); border-radius:10px;
            padding:1rem 1.2rem; margin:.75rem 0; }
  div[data-testid="stButton"] button { border-radius:9px; font-weight:700; }
  div[data-testid="stDataFrame"] { border:1px solid var(--line); border-radius:12px;
                                    overflow:hidden; }
  [data-testid="stMetric"] { background:var(--card); border:1px solid var(--line);
                             border-radius:12px; padding:1rem; }
</style>
"""
st.markdown(_CSS, unsafe_allow_html=True)


def _state(key: str, default: Any) -> Any:
    if key not in st.session_state:
        st.session_state[key] = default
    return st.session_state[key]


def _api() -> YouthCompassApi:
    return YouthCompassApi(st.session_state.api_url)


def _safe(call: Any, *args: Any, **kwargs: Any) -> Any | None:
    try:
        return call(*args, **kwargs)
    except ApiError as exc:
        label = f"{exc.code}: " if exc.code else ""
        st.error(f"{label}{exc.message}")
        return None


def _card(label: str, value: str, note: str) -> None:
    st.markdown(
        '<div class="metric-card">'
        f'<div class="metric-label">{html.escape(label)}</div>'
        f'<div class="metric-value">{html.escape(value)}</div>'
        f'<div class="metric-note">{html.escape(note)}</div>'
        "</div>",
        unsafe_allow_html=True,
    )


def _default_metric(dataset: dict[str, Any]) -> str:
    topic = str(dataset.get("topic", "")).lower()
    dataset_id = str(dataset.get("datasetId", "")).lower()
    known = {
        "population": "population_count",
        "employment": "job_seekers",
        "education": "education_count",
        "marriage": "marriage_count",
        "migration": "migration_count",
    }
    for hint, metric in known.items():
        if hint in topic or hint in dataset_id:
            return metric
    return "metric_value"


_state("api_url", os.getenv("YOUTH_COMPASS_API_URL", "http://127.0.0.1:8000"))
_state("active_job_id", None)
_state("reviewer", "reviewer@newtaipei.gov.tw")
_state("copilot_result", None)

with st.sidebar:
    st.markdown("## 🧭 Youth Compass")
    st.caption("Offline reviewer console")
    st.text_input("FastAPI URL", key="api_url")
    st.text_input("Reviewer identity", key="reviewer")
    health = _safe(_api().health)
    if health:
        st.markdown(
            '<div class="status-pill"><span class="status-dot"></span>'
            f"API online · v{html.escape(str(health.get('version', '?')))}</div>",
            unsafe_allow_html=True,
        )
    else:
        st.caption("API offline · start FastAPI on port 8000")
    st.divider()
    st.caption("LOCAL REFERENCE RUNTIME")
    st.caption("FastAPI · DuckDB · Parquet · SQLite")

st.markdown('<div class="eyebrow">New Taipei City · Youth Affairs</div>', unsafe_allow_html=True)
st.title("新北青年政策羅盤")
st.markdown(
    '<div class="hero-copy">Turn unfamiliar public data into reviewable, traceable '
    "policy evidence — without replacing the published dashboard until a human approves it.</div>",
    unsafe_allow_html=True,
)

overview_tab, explorer_tab, copilot_tab, onboarding_tab = st.tabs(
    [
        "01 · Policy overview",
        "02 · District explorer",
        "03 · Decision copilot",
        "04 · Data onboarding",
    ]
)

with overview_tab:
    datasets = _safe(_api().datasets) if health else None
    datasets = datasets or []
    published = [item for item in datasets if item.get("status") == "published"]
    average_quality = (
        sum(float(item.get("qualityScore", 0)) for item in published) / len(published)
        if published
        else 0
    )
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        _card("Published datasets", str(len(published)), "Approved evidence sources")
    with c2:
        _card("Average quality", f"{average_quality:.0%}", "Across published versions")
    with c3:
        _card("Runtime", "Offline", "Ready to swap for AWS adapters")
    with c4:
        _card("Decision gate", "Human", "No silent dashboard changes")

    st.markdown("### Evidence catalog")
    st.markdown(
        '<div class="section-note">Every card represents the latest visible version. '
        "Storage paths remain behind the API boundary.</div>",
        unsafe_allow_html=True,
    )
    if published:
        table = pd.DataFrame(
            [
                {
                    "Dataset": item.get("datasetId"),
                    "Topic": item.get("topic"),
                    "Version": item.get("version"),
                    "Role": item.get("datasetRole"),
                    "Quality": f"{float(item.get('qualityScore', 0)):.0%}",
                    "Published": item.get("publishedAt") or "—",
                }
                for item in published
            ]
        )
        st.dataframe(table, use_container_width=True, hide_index=True)
    else:
        st.markdown(
            '<div class="empty"><strong>No approved dataset yet.</strong><br>'
            "Open <em>Data onboarding</em>, upload the sample CSV, inspect its mapping, "
            "then approve it to populate this dashboard.</div>",
            unsafe_allow_html=True,
        )

with explorer_tab:
    if not published:
        st.info("Publish a dataset in Data onboarding before opening district analytics.")
    else:
        left, middle, right = st.columns([1.2, 1, 1])
        dataset_labels = {
            f"{item.get('topic')} · {item.get('datasetId')}": item for item in published
        }
        with left:
            selected_label = st.selectbox("Dataset", list(dataset_labels))
        selected = dataset_labels[selected_label]
        with middle:
            metric_code = st.text_input(
                "Metric code",
                value=_default_metric(selected),
                help="Temporary input until the catalog exposes its metric dictionary.",
            )
        with right:
            period = st.text_input("Period (optional)", placeholder="2025 or 2025-06")

        if st.button("Run district analysis", type="primary", use_container_width=True):
            summary = _safe(
                _api().city_summary,
                selected["datasetId"],
                metric_code,
                period or None,
            )
            profile = _safe(
                _api().districts,
                selected["datasetId"],
                metric_code,
                period or None,
            )
            if summary and profile:
                st.session_state.analytics_result = (summary, profile)

        result = st.session_state.get("analytics_result")
        if result:
            summary, profile = result
            a, b, c, d = st.columns(4)
            a.metric("City total", f"{summary['value']:,.0f}", summary.get("unitCode", ""))
            b.metric("Districts", summary.get("districtCount", 0))
            c.metric("Estimated", f"{summary.get('estimatedValue', 0):,.0f}")
            d.metric("Quality", f"{float(summary.get('qualityScore', 0)):.0%}")
            rows = profile.get("districts", [])
            chart_data = pd.DataFrame(
                [
                    {
                        "District": row.get("districtName") or row.get("districtCode"),
                        "Value": row.get("value", 0),
                    }
                    for row in rows
                ]
            ).set_index("District")
            st.markdown(f"### District comparison · {html.escape(summary['period'])}")
            st.bar_chart(chart_data, color="#176b52", horizontal=True)

with copilot_tab:
    st.markdown("### Ask a grounded location question")
    st.markdown(
        '<div class="section-note">The copilot routes questions only to registered tools. '
        "Dataset inspection, queries, comparisons, scoring, and citations remain "
        "deterministic.</div>",
        unsafe_allow_html=True,
    )
    question = st.text_area(
        "Question",
        placeholder="Where should I buy a home? / Nên đặt trụ sạc xe ở đâu?",
    )
    entity_scope = st.text_input(
        "Candidate IDs (optional, comma separated)",
        placeholder="banqiao, linkou",
    )
    minimum_quality = st.slider(
        "Minimum evidence quality",
        min_value=0.0,
        max_value=1.0,
        value=0.7,
        step=0.05,
    )
    if st.button(
        "Run grounded analysis",
        type="primary",
        use_container_width=True,
        disabled=not question.strip() or not health,
    ):
        result = _safe(
            _api().copilot,
            question,
            entity_ids=[item.strip() for item in entity_scope.split(",") if item.strip()],
            min_quality_score=minimum_quality,
        )
        if result:
            st.session_state.copilot_result = result

    copilot_result = st.session_state.copilot_result
    if copilot_result:
        response_status = copilot_result.get("status", "unknown")
        if response_status == "answered":
            st.success(copilot_result.get("answer", ""))
        else:
            st.warning(copilot_result.get("answer", ""))
        decomposition = copilot_result.get("decomposition") or {}
        routed_plan = copilot_result.get("routed_plan") or {}
        if decomposition:
            with st.expander("Query decomposition and tool route"):
                st.caption(decomposition.get("objective", ""))
                st.dataframe(
                    pd.DataFrame(
                        [
                            {
                                "Step": step.get("step_id"),
                                "Operation": step.get("operation"),
                                "Tool": step.get("tool_name"),
                                "Depends on": ", ".join(step.get("depends_on", [])),
                            }
                            for step in routed_plan.get("steps", [])
                        ]
                    ),
                    hide_index=True,
                    use_container_width=True,
                )
                missing_operations = routed_plan.get("missing_operations", [])
                if missing_operations:
                    st.warning("Missing tools: " + ", ".join(missing_operations))
        plan = copilot_result.get("plan") or {}
        if plan:
            st.caption(
                f"Plan: {plan.get('profile_code')}@{plan.get('profile_version')} · "
                f"{len(plan.get('feature_codes', []))} features"
            )
        candidates = copilot_result.get("candidates", [])
        if candidates:
            st.dataframe(
                pd.DataFrame(
                    [
                        {
                            "Rank": item.get("rank") or "—",
                            "Candidate": item.get("entity_name") or item.get("entity_id"),
                            "Eligible": item.get("eligible"),
                            "Score": item.get("score"),
                            "Missing": ", ".join(item.get("missing_required_features", [])),
                        }
                        for item in candidates
                    ]
                ),
                hide_index=True,
                use_container_width=True,
            )
        comparison = (copilot_result.get("comparison") or {}).get("changes", [])
        if comparison:
            st.markdown("#### Observation comparison")
            st.dataframe(
                pd.DataFrame(
                    [
                        {
                            "Entity": item.get("entity_name") or item.get("entity_id"),
                            "From": item.get("first_period"),
                            "To": item.get("last_period"),
                            "First value": item.get("first_value"),
                            "Last value": item.get("last_value"),
                            "Change %": item.get("percent_change"),
                            "Direction": item.get("direction"),
                        }
                        for item in comparison
                    ]
                ),
                hide_index=True,
                use_container_width=True,
            )
        citations = copilot_result.get("citations", [])
        if citations:
            with st.expander("Evidence and lineage"):
                st.dataframe(pd.DataFrame(citations), hide_index=True, use_container_width=True)
        for warning in copilot_result.get("warnings", []):
            st.caption(f"⚠️ {warning}")

with onboarding_tab:
    st.markdown("### Add a new evidence source")
    st.markdown(
        '<div class="section-note">CSV, Excel, and JSON are normalized, profiled, and '
        "mapped. Nothing reaches "
        "the dashboard until you approve the proposal.</div>",
        unsafe_allow_html=True,
    )
    upload_col, process_col = st.columns([1, 1.35], gap="large")
    with upload_col:
        uploaded = st.file_uploader(
            "Tabular source",
            type=["csv", "tsv", "xlsx", "xlsm", "json", "jsonl", "ndjson", "pdf"],
        )
        topic_hint = st.text_input("Topic hint (optional)", placeholder="employment")
        upload_clicked = st.button(
            "Profile and map file",
            type="primary",
            use_container_width=True,
            disabled=uploaded is None or not health,
        )
        if upload_clicked and uploaded is not None:
            response = _safe(
                _api().upload,
                file_name=uploaded.name,
                content=uploaded.getvalue(),
                submitted_by=st.session_state.reviewer,
                topic_hint=topic_hint or None,
            )
            if response:
                st.session_state.active_job_id = response["jobId"]
                st.rerun()
        st.caption("Happy path: data/samples/population_demo.csv")
        st.caption("Quarantine path: tests/fixtures/employment_unfamiliar.csv")

    with process_col:
        job_id = st.session_state.active_job_id
        if not job_id:
            st.markdown(
                '<div class="empty"><strong>Waiting for a file</strong><br>'
                "The inferred schema, confidence, warnings, and approval controls will appear here."
                "</div>",
                unsafe_allow_html=True,
            )
        else:
            job = _safe(_api().job, job_id)
            if job:
                st.markdown(
                    f'<div class="review"><strong>Job {html.escape(job_id[:12])}…</strong><br>'
                    f"Status: {html.escape(str(job.get('status')))} · "
                    f"Quality: {float(job.get('qualityScore', 0)):.0%}</div>",
                    unsafe_allow_html=True,
                )
                if job.get("status") == "awaiting_approval":
                    mapping = _safe(_api().mapping, job_id)
                    if mapping:
                        proposal = mapping["proposal"]
                        confidence = float(proposal.get("overall_confidence", 0))
                        m1, m2, m3 = st.columns(3)
                        m1.metric("Topic", proposal.get("topic", "—"))
                        m2.metric("Confidence", f"{confidence:.0%}")
                        m3.metric(
                            "Grain fields", len(proposal.get("grain", {}).get("dimensions", []))
                        )
                        rows = [
                            {
                                "Source": item["source_column"],
                                "Canonical field": item["target_field"],
                                "Transform": item["transformation"],
                                "Confidence": f"{float(item['confidence']):.0%}",
                            }
                            for item in proposal.get("columns", [])
                        ]
                        if rows:
                            st.dataframe(
                                pd.DataFrame(rows), hide_index=True, use_container_width=True
                            )
                        warnings = [
                            *proposal.get("warnings", []),
                            *[
                                issue["message"]
                                for issue in mapping.get("validation", {}).get("issues", [])
                            ],
                        ]
                        if warnings:
                            st.warning("\n\n".join(warnings))
                        comment = st.text_area(
                            "Review note",
                            placeholder="Checked district and metric mapping against the source.",
                        )
                        approve_col, reject_col = st.columns(2)
                        if approve_col.button(
                            "Approve & publish", type="primary", use_container_width=True
                        ):
                            decided = _safe(
                                _api().decide,
                                job_id,
                                decision="approve",
                                decided_by=st.session_state.reviewer,
                                comment=comment,
                            )
                            if decided:
                                st.success(
                                    "Dataset published. The evidence catalog is now updated."
                                )
                                st.session_state.analytics_result = None
                                st.rerun()
                        if reject_col.button("Reject", use_container_width=True):
                            decided = _safe(
                                _api().decide,
                                job_id,
                                decision="reject",
                                decided_by=st.session_state.reviewer,
                                comment=comment,
                            )
                            if decided:
                                st.warning(
                                    "Dataset rejected; the published dashboard was unchanged."
                                )
                                st.rerun()
                elif job.get("status") in {"published", "quarantined"}:
                    quality = _safe(_api().quality, job_id)
                    if quality:
                        report = quality["quality"]
                        q1, q2, q3 = st.columns(3)
                        q1.metric("Accepted rows", report.get("rows_accepted", 0))
                        q2.metric("Rejected rows", report.get("rows_rejected", 0))
                        q3.metric("Quality", f"{float(report.get('quality_score', 0)):.0%}")
                    if st.button("Review another file", use_container_width=True):
                        st.session_state.active_job_id = None
                        st.rerun()
                elif job.get("status") == "rejected":
                    st.warning(
                        "This proposal was rejected. The current dashboard data was preserved."
                    )
                    if st.button("Review another file", use_container_width=True):
                        st.session_state.active_job_id = None
                        st.rerun()
