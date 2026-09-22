"""
app.py
AI Asset Rescue Agent — Streamlit dashboard.

Run:
    streamlit run app.py
"""

import json
import io
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from db import get_connection
from scoring import score_assets
from agent import run_agent
from tools import execute_action

# ═══════════════════════════════════════════════════════════════════════════════
#  PAGE CONFIG  (must be first Streamlit call)
# ═══════════════════════════════════════════════════════════════════════════════
st.set_page_config(
    page_title="AI Asset Rescue Agent",
    page_icon="🏛️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ═══════════════════════════════════════════════════════════════════════════════
#  COLOUR PALETTE  (consistent across all charts and badges)
# ═══════════════════════════════════════════════════════════════════════════════
CLR_RED    = "#d62728"   # high / critical risk
CLR_AMBER  = "#ff7f0e"   # underused / warning
CLR_GREEN  = "#2ca02c"   # healthy / normal use
CLR_BLUE   = "#1f6feb"   # primary accent
CLR_GREY   = "#adb5bd"   # neutral / decommissioned
CLR_MED    = "#f5a623"   # medium risk

STATUS_COLORS = {
    "Active":        CLR_GREEN,
    "Idle":          CLR_BLUE,
    "Under Repair":  CLR_AMBER,
    "Decommissioned": CLR_GREY,
}

# ═══════════════════════════════════════════════════════════════════════════════
#  GLOBAL CSS
# ═══════════════════════════════════════════════════════════════════════════════
st.markdown("""
<style>
/* action-needed card */
.action-card {
    background: #fff8f0;
    border-left: 4px solid #d62728;
    border-radius: 6px;
    padding: 10px 14px;
    margin-bottom: 8px;
}
.action-card h4 { margin: 0 0 4px 0; font-size: 0.95rem; color: #1a1a2e; }
.action-card p  { margin: 0; font-size: 0.82rem; color: #444; }
/* risk badges */
.badge {
    display: inline-block;
    padding: 2px 8px;
    border-radius: 12px;
    font-size: 0.78rem;
    font-weight: 600;
    color: #fff;
}
.badge-red    { background: #d62728; }
.badge-amber  { background: #ff7f0e; }
.badge-yellow { background: #f5a623; color: #1a1a2e; }
.badge-green  { background: #2ca02c; }
/* chat example buttons row */
.example-btn { margin: 4px 0; }
/* approve/reject mock card */
.mock-card {
    border: 1px solid #dee2e6;
    border-radius: 8px;
    padding: 14px 18px;
    background: #f8f9fa;
}
</style>
""", unsafe_allow_html=True)


# ═══════════════════════════════════════════════════════════════════════════════
#  CACHED DATA LOADERS
# ═══════════════════════════════════════════════════════════════════════════════
@st.cache_data(ttl=60)
def load_scored() -> pd.DataFrame:
    return score_assets()


@st.cache_data(ttl=60)
def load_log() -> pd.DataFrame:
    conn = get_connection()
    df = pd.read_sql(
        "SELECT log_id, timestamp, asset_id, action_type, performed_by, details "
        "FROM actions_log ORDER BY log_id DESC LIMIT 100",
        conn,
    )
    conn.close()
    return df


# ═══════════════════════════════════════════════════════════════════════════════
#  HELPERS
# ═══════════════════════════════════════════════════════════════════════════════
def risk_label(score: int) -> str:
    if score >= 80: return "Critical"
    if score >= 60: return "High"
    if score >= 40: return "Medium"
    return "Low"

def risk_badge_html(score: int) -> str:
    label = risk_label(score)
    cls = {"Critical": "badge-red", "High": "badge-amber",
           "Medium": "badge-yellow", "Low": "badge-green"}[label]
    return f'<span class="badge {cls}">{label}</span>'

def suggested_action(row) -> str:
    if row["failures"] >= 4:
        return "🔧 Schedule emergency repair"
    if row["age_years"] >= 8:
        return "🔄 Consider replacement"
    if row["days_since_maintenance"] >= 548:
        return "🛠️ Schedule maintenance"
    return "🔍 Review asset condition"

def pct_str(n: int, total: int) -> str:
    return f"{n/total*100:.0f}%" if total else "—"


# ═══════════════════════════════════════════════════════════════════════════════
#  SIDEBAR — FILTERS + ABOUT
# ═══════════════════════════════════════════════════════════════════════════════
with st.sidebar:
    st.header("🔎 Filters")

    with st.spinner("Loading asset data…"):
        full_df = load_scored()

    all_depts   = sorted(full_df["dept"].dropna().unique().tolist())
    all_types   = sorted(full_df["type"].dropna().unique().tolist())
    all_statuses = sorted(full_df["status"].dropna().unique().tolist())

    sel_depts    = st.multiselect("Department",  all_depts,    default=all_depts,
                                  help="Show assets from these departments")
    sel_types    = st.multiselect("Asset Type",  all_types,    default=all_types,
                                  help="Show these asset types")
    sel_statuses = st.multiselect("Status",      all_statuses, default=all_statuses,
                                  help="Show assets with these statuses")

    if st.button("↺ Reset filters", use_container_width=True):
        st.rerun()

    st.divider()
    st.markdown("""
**ℹ️ About this app**

The AI Asset Rescue Agent helps university IT teams track equipment health
and take timely action.

- **Risk scores are fully explainable** — every score comes with a plain-English
  reason broken down by maintenance history, failures, and age.
- **Every action requires human approval** — the agent proposes;
  a person reviews and confirms before any change is written to the database.
- **Powered by Azure AI Foundry + Azure AI Search (RAG)** — the Chat tab uses
  GPT-4.1-mini with function calling and vector search over the policy docs.
""")


# ═══════════════════════════════════════════════════════════════════════════════
#  APPLY FILTERS
# ═══════════════════════════════════════════════════════════════════════════════
df = full_df[
    full_df["dept"].isin(sel_depts)
    & full_df["type"].isin(sel_types)
    & full_df["status"].isin(sel_statuses)
].copy()

# in-service = everything except Decommissioned
inservice_df = df[df["status"] != "Decommissioned"]
n_inservice  = len(inservice_df)


# ═══════════════════════════════════════════════════════════════════════════════
#  TABS
# ═══════════════════════════════════════════════════════════════════════════════
tab_dash, tab_chat = st.tabs(["📊 Dashboard", "💬 Chat"])


# ╔═══════════════════════════════════════════════════════════════════════════╗
# ║  DASHBOARD TAB                                                           ║
# ╚═══════════════════════════════════════════════════════════════════════════╝
with tab_dash:
    st.title("🏛️ AI Asset Rescue Agent")
    st.caption("University asset health overview · data as of 20 Sep 2026")

    if df.empty:
        st.warning("No assets match the current filters. Use the sidebar to adjust.")
        st.stop()

    # ── KPI CARDS ─────────────────────────────────────────────────────────────
    st.subheader("Key Metrics")

    n_high_risk  = int((inservice_df["repair_risk"] >= 60).sum())
    n_critical   = int((inservice_df["repair_risk"] >= 80).sum())
    n_underused  = int(inservice_df["underuse"].sum())
    n_repair     = int((inservice_df["status"] == "Under Repair").sum())
    n_decomm     = int((df["status"] == "Decommissioned").sum())

    c1, c2, c3, c4, c5 = st.columns(5)

    c1.metric(
        "In-Service Assets", n_inservice,
        help="All assets excluding Decommissioned, within current filters.",
    )
    c2.metric(
        "🔴 High Risk",
        f"{n_high_risk}  ({pct_str(n_high_risk, n_inservice)})",
        help="In-service assets with repair risk score ≥ 60. "
             "Scores combine maintenance overdue, failure count, and asset age.",
    )
    c3.metric(
        "🔴 Critical",
        f"{n_critical}  ({pct_str(n_critical, n_inservice)})",
        help="In-service assets with repair risk score ≥ 80. "
             "Immediate review required within 7 days (audit_policy §4).",
    )
    c4.metric(
        "🟡 Underused",
        f"{n_underused}  ({pct_str(n_underused, n_inservice)})",
        help="Active or Idle assets with usage hours below 25 % of age-expected "
             "(500 hrs/yr) or below the 200 hr floor. Consider reallocation.",
    )
    c5.metric(
        "🔧 Under Repair", n_repair,
        help="Assets currently offline for repair. Cannot be reallocated until cleared.",
    )

    st.divider()

    # ── ACTION-NEEDED CARDS ───────────────────────────────────────────────────
    st.subheader("⚠️ Action Needed — Top 5 Highest-Risk Assets")
    top5 = (
        inservice_df[inservice_df["repair_risk"] >= 60]
        .sort_values("repair_risk", ascending=False)
        .head(5)
    )

    if top5.empty:
        st.success("✅ No high-risk assets with the current filters.")
    else:
        for _, r in top5.iterrows():
            badge   = risk_badge_html(r["repair_risk"])
            action  = suggested_action(r)
            # Truncate reason to first sentence for the card
            short_reason = r["reason"].split(".")[0] + "."
            st.markdown(f"""
<div class="action-card">
  <h4>{r['id']} &nbsp;·&nbsp; {r['type']} &nbsp;·&nbsp; {r['dept']}
      &nbsp;&nbsp;{badge}&nbsp; <span style="color:#888;font-size:0.85rem;">score {r['repair_risk']}</span>
  </h4>
  <p>{short_reason}</p>
  <p><strong>Suggested:</strong> {action}</p>
</div>
""", unsafe_allow_html=True)

    st.divider()

    # ── HIGH-RISK TABLE ───────────────────────────────────────────────────────
    st.subheader("🔴 High-Risk Assets (repair risk ≥ 60)")

    high_df = (
        inservice_df[inservice_df["repair_risk"] >= 60]
        .sort_values("repair_risk", ascending=False)
        .copy()
    )

    if high_df.empty:
        st.success("No high-risk assets match the current filters.")
    else:
        # Short reason for the table cell; full text in an expander below
        high_df["risk_label"]    = high_df["repair_risk"].apply(risk_label)
        high_df["short_reason"]  = high_df["reason"].apply(
            lambda s: s[:90] + "…" if len(s) > 90 else s
        )

        display_df = high_df[[
            "id", "type", "dept", "location", "status",
            "repair_risk", "risk_label", "days_since_maintenance",
            "failures", "short_reason",
        ]].rename(columns={
            "id":                     "Asset ID",
            "type":                   "Type",
            "dept":                   "Department",
            "location":               "Location",
            "status":                 "Status",
            "repair_risk":            "Risk Score",
            "risk_label":             "Risk Level",
            "days_since_maintenance": "Days Since Maint.",
            "failures":               "Failures",
            "short_reason":           "Reason (summary)",
        })

        st.dataframe(
            display_df,
            use_container_width=True,
            hide_index=True,
            column_config={
                "Risk Score": st.column_config.ProgressColumn(
                    "Risk Score",
                    help="Composite score 0–100 (maintenance + failures + age).",
                    format="%d",
                    min_value=0,
                    max_value=100,
                ),
            },
        )

        # Full reason expander
        with st.expander("📄 View full reasons for all high-risk assets"):
            for _, r in high_df.iterrows():
                st.markdown(f"**{r['id']}** ({r['type']}, {r['dept']})")
                st.write(r["reason"])
                st.divider()

        # Download button
        csv_buf = io.StringIO()
        high_df[["id","type","dept","location","status",
                 "repair_risk","risk_label","days_since_maintenance",
                 "failures","reason"]].to_csv(csv_buf, index=False)
        st.download_button(
            label="⬇️ Download high-risk table as CSV",
            data=csv_buf.getvalue(),
            file_name="high_risk_assets.csv",
            mime="text/csv",
        )

    st.divider()

    # ── 2×2 CHART GRID ────────────────────────────────────────────────────────
    st.subheader("📈 Utilisation & Risk Overview")

    row1_left, row1_right = st.columns(2)
    row2_left, row2_right = st.columns(2)

    CHART_H = 380

    # Chart 1 — Risk score distribution (in-service only)
    with row1_left:
        fig1 = px.histogram(
            inservice_df,
            x="repair_risk",
            nbins=20,
            color_discrete_sequence=[CLR_RED],
            title="Repair Risk Score Distribution",
            labels={"repair_risk": "Risk Score", "count": "Number of Assets"},
        )
        fig1.add_vline(x=60, line_dash="dash", line_color=CLR_AMBER,
                       annotation_text="High (60)", annotation_position="top right")
        fig1.add_vline(x=80, line_dash="dash", line_color=CLR_RED,
                       annotation_text="Critical (80)", annotation_position="top right")
        fig1.update_layout(height=CHART_H, margin=dict(t=50, b=10))
        st.plotly_chart(fig1, use_container_width=True)
        st.caption("Most in-service assets score below 60. "
                   "Assets above the dashed lines need immediate attention.")

    # Chart 2 — Asset status breakdown (all filtered assets including Decommissioned)
    with row1_right:
        status_counts = (
            df["status"].value_counts().reset_index()
        )
        status_counts.columns = ["Status", "Count"]
        fig2 = px.pie(
            status_counts,
            names="Status",
            values="Count",
            title="Asset Status Breakdown",
            hole=0.42,
            color="Status",
            color_discrete_map=STATUS_COLORS,
        )
        fig2.update_traces(textposition="outside", textinfo="percent+label")
        fig2.update_layout(
            height=CHART_H,
            showlegend=False,
            margin=dict(t=50, b=10),
        )
        st.plotly_chart(fig2, use_container_width=True)
        pct_active = pct_str(int((df["status"] == "Active").sum()), len(df))
        st.caption(f"{pct_active} of filtered assets are Active. "
                   "Idle and Under Repair assets may need reallocation or repair.")

    # Chart 3 — Usage hours by department (box plot, in-service)
    with row2_left:
        fig3 = px.box(
            inservice_df,
            x="dept",
            y="usage_hours",
            color="dept",
            title="Usage Hours by Department",
            labels={"dept": "Department", "usage_hours": "Usage Hours"},
            color_discrete_sequence=px.colors.qualitative.Safe,
        )
        fig3.update_layout(
            showlegend=False,
            xaxis_tickangle=-35,
            height=CHART_H,
            margin=dict(t=50, b=80),
        )
        st.plotly_chart(fig3, use_container_width=True)
        st.caption("Wide boxes indicate uneven usage within a department. "
                   "Low medians may signal assets ripe for reallocation.")

    # Chart 4 — Underused assets by type (stacked bar, in-service)
    with row2_right:
        type_counts = (
            inservice_df
            .groupby(["type", "underuse"])
            .size()
            .reset_index(name="count")
        )
        type_counts["Usage"] = type_counts["underuse"].map(
            {True: "Underused (low usage for age)", False: "Normal Use"}
        )
        fig4 = px.bar(
            type_counts,
            x="type",
            y="count",
            color="Usage",
            title="Underused Assets by Type",
            labels={"type": "Asset Type", "count": "Count", "Usage": ""},
            color_discrete_map={
                "Underused (low usage for age)": CLR_AMBER,
                "Normal Use":                    CLR_GREEN,
            },
            barmode="stack",
        )
        fig4.update_layout(
            height=CHART_H,
            xaxis_tickangle=-30,
            margin=dict(t=50, b=80),
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        )
        st.plotly_chart(fig4, use_container_width=True)
        st.caption("Orange segments are underused relative to their age. "
                   "Prioritise these for reallocation to higher-demand departments.")

    st.divider()

    # ── ACTIONS LOG ───────────────────────────────────────────────────────────
    st.subheader("📋 Recent Actions Log")

    with st.spinner("Loading actions log…"):
        log_df = load_log()

    if log_df.empty:
        st.info(
            "📭 No actions have been logged yet.\n\n"
            "Actions are recorded here when the agent (or an IT coordinator) "
            "commits a maintenance or reallocation decision via `execute_action()`.",
            icon="ℹ️",
        )
    else:
        for _, row in log_df.iterrows():
            action_pretty = row["action_type"].replace("_", " ").title()
            ts = row["timestamp"] or "—"
            with st.expander(
                f"**{row['asset_id']}** — {action_pretty} · {ts} · by {row['performed_by']}"
            ):
                st.markdown(
                    f"- **Asset:** {row['asset_id']}\n"
                    f"- **Action:** {action_pretty}\n"
                    f"- **Performed by:** {row['performed_by']}\n"
                    f"- **Time:** {ts}"
                )
                if row["details"]:
                    try:
                        parsed = json.loads(row["details"])
                        st.json(parsed)
                    except Exception:
                        st.code(row["details"])

    # ── REFRESH ────────────────────────────────────────────────────────────────
    st.divider()
    if st.button("🔄 Refresh all data", use_container_width=False):
        st.cache_data.clear()
        st.rerun()


# ╔═══════════════════════════════════════════════════════════════════════════╗
# ║  CHAT TAB                                                                ║
# ╚═══════════════════════════════════════════════════════════════════════════╝
with tab_chat:
    st.title("💬 AI Agent Chat")
    st.caption("Powered by Azure AI Foundry + Azure AI Search (RAG)")

    # ── session state init ────────────────────────────────────────────────────
    if "messages" not in st.session_state:
        st.session_state["messages"] = []          # [{role, content}, ...]
    if "pending_proposal" not in st.session_state:
        st.session_state["pending_proposal"] = None  # proposal dict or None
    if "example_q" not in st.session_state:
        st.session_state["example_q"] = ""

    # ── welcome message (only before first exchange) ──────────────────────────
    if not st.session_state["messages"]:
        with st.container(border=True):
            st.markdown("""
### 👋 Welcome to the Asset Rescue Agent

I can help you:
- **Find** assets by type, department, or location
- **Identify** high-risk or underused equipment
- **Propose** maintenance schedules or reallocations
- **Answer** questions about university asset policies

Every action I suggest is shown to you as an **Approve / Reject card** before
anything is written to the database. You stay in control at every step.
""")

    # ── example question buttons ──────────────────────────────────────────────
    st.markdown("#### 💡 Try asking:")
    eq1, eq2 = st.columns(2)
    eq3, eq4 = st.columns(2)

    with eq1:
        if st.button("🔴 Which assets need repair?",
                     use_container_width=True, key="eq1"):
            st.session_state["example_q"] = "Which assets need repair?"
            st.rerun()
    with eq2:
        if st.button("💤 Show underused laptops",
                     use_container_width=True, key="eq2"):
            st.session_state["example_q"] = "Show underused laptops"
            st.rerun()
    with eq3:
        if st.button("📋 What does the maintenance policy say?",
                     use_container_width=True, key="eq3"):
            st.session_state["example_q"] = "What does the maintenance policy say?"
            st.rerun()
    with eq4:
        if st.button("🔀 Reallocate an underused asset",
                     use_container_width=True, key="eq4"):
            st.session_state["example_q"] = "Reallocate an underused asset"
            st.rerun()

    st.divider()

    # ── render existing conversation ──────────────────────────────────────────
    for msg in st.session_state["messages"]:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    # ── pending Approve / Reject card (shown below the last message) ──────────
    if st.session_state["pending_proposal"] is not None:
        proposal = st.session_state["pending_proposal"]
        action_type = proposal.get("action_type", "")
        action_label = action_type.replace("_", " ").title()

        with st.container(border=True):
            st.markdown(f"**🗂️ Proposed Action: {action_label}**")

            if action_type == "schedule_maintenance":
                st.markdown(f"""
| Field | Value |
|---|---|
| Asset ID | {proposal.get('asset_id', '—')} |
| Type | {proposal.get('asset_type', '—')} |
| Department | {proposal.get('dept', '—')} |
| Location | {proposal.get('location', '—')} |
| Proposed date | {proposal.get('proposed_maintenance_date', '—')} |
| Last maintained | {proposal.get('current_last_maintenance', '—')} |
""")
            elif action_type == "reallocate_asset":
                st.markdown(f"""
| Field | Value |
|---|---|
| Asset ID | {proposal.get('asset_id', '—')} |
| Type | {proposal.get('asset_type', '—')} |
| From department | {proposal.get('from_dept', '—')} |
| From location | {proposal.get('from_location', '—')} |
| To department | {proposal.get('to_dept', '—')} |
| To location | {proposal.get('to_location', '—')} |
""")
            else:
                st.json(proposal)

            st.caption("No change is made until you click **Approve**.")
            col_approve, col_reject, _ = st.columns([1, 1, 3])

            with col_approve:
                if st.button("✅ Approve", type="primary", key="approve_btn"):
                    result = execute_action(proposal, performed_by="chat_user")
                    if result.get("success"):
                        approved_msg = (
                            f"✅ **Action approved and committed.** "
                            f"`{proposal.get('action_type')}` on "
                            f"`{proposal.get('asset_id')}` has been recorded."
                        )
                        st.session_state["messages"].append(
                            {"role": "assistant", "content": approved_msg}
                        )
                    else:
                        err_msg = (
                            f"⚠️ **Approval failed:** {result.get('error', 'Unknown error.')}"
                        )
                        st.session_state["messages"].append(
                            {"role": "assistant", "content": err_msg}
                        )
                    st.session_state["pending_proposal"] = None
                    st.cache_data.clear()   # force dashboard KPIs/charts to refresh
                    st.rerun()

            with col_reject:
                if st.button("❌ Reject", key="reject_btn"):
                    st.session_state["messages"].append(
                        {"role": "assistant",
                         "content": "🚫 **Proposal rejected.** No changes were made."}
                    )
                    st.session_state["pending_proposal"] = None
                    st.rerun()

    # ── chat input (and example-button injection) ─────────────────────────────
    # Consume a queued example-button click as if the user typed it
    prefill = st.session_state.pop("example_q", "") if st.session_state.get("example_q") else ""

    user_input = st.chat_input("Ask about your assets…", key="chat_input")

    # Prefer typed input; fall back to example-button prefill
    raw_input = user_input or prefill or ""

    if raw_input:
        # 1. Add user message to history and render it immediately
        st.session_state["messages"].append({"role": "user", "content": raw_input})
        with st.chat_message("user"):
            st.markdown(raw_input)

        # 2. Call the agent
        with st.chat_message("assistant"):
            with st.spinner("Thinking…"):
                result = run_agent(raw_input)

            agent_text = result["response"]
            st.markdown(agent_text)

        # 3. Persist assistant reply
        st.session_state["messages"].append(
            {"role": "assistant", "content": agent_text}
        )

        # 4. Check tool calls for a proposal (schedule_maintenance / reallocate_asset)
        new_proposal = None
        for tc in result.get("tool_calls", []):
            if tc["name"] in ("schedule_maintenance", "reallocate_asset"):
                # result_preview is truncated; re-parse via the full result stored
                # in tc — run_agent only stores a preview, so we re-call the tool
                # to get the full dict.  Actually we can parse the preview safely:
                # proposals are small JSON. Use the preview but strip the ellipsis.
                raw = tc["result_preview"].rstrip("…").rstrip("…")
                try:
                    proposal_dict = json.loads(raw)
                except json.JSONDecodeError:
                    # preview was truncated — re-call the tool for the full result
                    from tools import schedule_maintenance, reallocate_asset
                    if tc["name"] == "schedule_maintenance":
                        proposal_dict = schedule_maintenance(tc["args"].get("asset_id", ""))
                    else:
                        proposal_dict = reallocate_asset(
                            tc["args"].get("asset_id", ""),
                            tc["args"].get("to_dept", ""),
                            tc["args"].get("to_location", ""),
                        )
                # Only surface real proposals, not errors
                if isinstance(proposal_dict, dict) and "error" not in proposal_dict:
                    new_proposal = proposal_dict
                    break   # show one card at a time

        if new_proposal:
            st.session_state["pending_proposal"] = new_proposal
        
        st.rerun()
