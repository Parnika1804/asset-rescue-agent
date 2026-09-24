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
#  AUTH HELPERS  (hashlib — stdlib, no new dependency)
# ═══════════════════════════════════════════════════════════════════════════════
import hashlib, hmac, os

def _hash_password(password: str) -> str:
    """PBKDF2-HMAC-SHA256 with a random 32-byte salt. Returns 'salt_hex:hash_hex'."""
    salt = os.urandom(32)
    dk   = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 260_000)
    return salt.hex() + ":" + dk.hex()

def _verify_password(password: str, stored: str) -> bool:
    """Re-derive the hash for the stored salt and compare in constant time."""
    try:
        salt_hex, hash_hex = stored.split(":")
        salt = bytes.fromhex(salt_hex)
        dk   = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 260_000)
        return hmac.compare_digest(dk.hex(), hash_hex)
    except Exception:
        return False

def _create_user(username: str, password: str) -> tuple[bool, str]:
    """Insert a new user. Returns (success, message)."""
    conn = get_connection()
    try:
        conn.execute(
            "INSERT INTO users (username, password_hash) VALUES (?, ?)",
            (username.strip(), _hash_password(password)),
        )
        conn.commit()
        return True, "Account created."
    except Exception as e:
        return False, "Username already taken." if "UNIQUE" in str(e) else str(e)
    finally:
        conn.close()

def _check_login(username: str, password: str) -> bool:
    """Return True if username+password match a stored record."""
    conn = get_connection()
    row  = conn.execute(
        "SELECT password_hash FROM users WHERE username = ?",
        (username.strip(),),
    ).fetchone()
    conn.close()
    if row is None:
        return False
    return _verify_password(password, row["password_hash"])

# ═══════════════════════════════════════════════════════════════════════════════
#  PAGE CONFIG  (must be first Streamlit call)
# ═══════════════════════════════════════════════════════════════════════════════
st.set_page_config(
    page_title="AI Asset Rescue Agent",
    page_icon="🏛️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── ensure users table exists (idempotent — safe to call every run) ───────────
_boot_conn = get_connection()
_boot_conn.executescript("""
    CREATE TABLE IF NOT EXISTS users (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        username      TEXT    UNIQUE NOT NULL,
        password_hash TEXT    NOT NULL,
        created_at    TEXT    DEFAULT (datetime('now','localtime'))
    );
""")
_boot_conn.commit()
_boot_conn.close()

# ═══════════════════════════════════════════════════════════════════════════════
#  LOGIN / SIGNUP GATE  — shown before anything else if not authenticated
# ═══════════════════════════════════════════════════════════════════════════════
if "logged_in" not in st.session_state:
    st.session_state["logged_in"]           = False
    st.session_state["authenticated_user"]  = ""

if not st.session_state["logged_in"]:
    # ── auth screen CSS ───────────────────────────────────────────────────────
    st.markdown("""
<style>
/* ── PAGE BACKGROUND ─────────────────────────────────────────────────────── */
[data-testid="stAppViewContainer"] {
    background: linear-gradient(145deg, #F0F9FF 0%, #E0F2FE 50%, #F0F9FF 100%) !important;
    min-height: 100vh !important;
}
[data-testid="stHeader"] { background: transparent !important; }

/* ── FADE-IN for the whole auth page ────────────────────────────────────────── */
@keyframes ara-auth-fadein {
    from { opacity: 0; transform: translateY(12px); }
    to   { opacity: 1; transform: translateY(0); }
}
.ara-auth-wrap {
    animation: ara-auth-fadein 0.38s ease both;
    display: flex;
    flex-direction: column;
    align-items: center;
    padding: 48px 16px 32px 16px;
}

/* ── LOGO MARK ───────────────────────────────────────────────────────────────── */
.ara-logo-wrap {
    margin-bottom: 20px;
}
.ara-logo-box {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 64px;
    height: 64px;
    background: linear-gradient(135deg, #0EA5E9 0%, #0284C7 100%);
    border-radius: 18px;
    box-shadow: 0 6px 24px rgba(14,165,233,0.35);
    position: relative;
}
/* CSS-drawn chevron/pillar icon inside the logo box */
.ara-logo-box::before {
    content: "";
    position: absolute;
    width: 22px; height: 30px;
    background: rgba(255,255,255,0.95);
    border-radius: 3px 3px 0 0;
    top: 14px; left: 12px;
}
.ara-logo-box::after {
    content: "";
    position: absolute;
    width: 14px; height: 22px;
    background: rgba(255,255,255,0.55);
    border-radius: 3px 3px 0 0;
    top: 22px; left: 36px;
}

/* ── APP NAME + TAGLINE ──────────────────────────────────────────────────────── */
.ara-brand-name {
    font-size: 1.75rem;
    font-weight: 800;
    color: #0F172A;
    margin: 0 0 6px 0;
    letter-spacing: -0.4px;
    text-align: center;
}
.ara-brand-tag {
    font-size: 0.88rem;
    color: #64748B;
    font-weight: 400;
    margin: 0 0 28px 0;
    text-align: center;
    max-width: 340px;
    line-height: 1.5;
}

/* ── AUTH CARD ───────────────────────────────────────────────────────────────── */
/* Constrain and centre the Streamlit border container */
[data-testid="stVerticalBlock"] > [data-testid="stVerticalBlockBorderWrapper"] {
    max-width: 440px !important;
    width: 100% !important;
    margin: 0 auto !important;
    background: #FFFFFF !important;
    border-radius: 16px !important;
    border: 1px solid #E0F2FE !important;
    box-shadow: 0 8px 40px rgba(14,165,233,0.14) !important;
    padding: 2rem 2.25rem !important;
    box-sizing: border-box !important;
}

/* ── CARD HEADING (the #### lines) ───────────────────────────────────────────── */
[data-testid="stMarkdownContainer"] h4 {
    font-size: 1.25rem !important;
    font-weight: 800 !important;
    color: #0F172A !important;
    margin: 0 0 1.25rem 0 !important;
    letter-spacing: -0.2px !important;
}

/* ── INPUT FIELDS ────────────────────────────────────────────────────────────── */
[data-testid="stTextInput"] label {
    font-size: 0.86rem !important;
    font-weight: 600 !important;
    color: #334155 !important;
    letter-spacing: 0.1px !important;
}
[data-testid="stTextInput"] input {
    border-radius: 8px !important;
    border: 1.5px solid #CBD5E1 !important;
    padding: 10px 13px !important;
    font-size: 0.95rem !important;
    transition: border-color 0.18s ease, box-shadow 0.18s ease !important;
    background: #F8FAFC !important;
}
[data-testid="stTextInput"] input:focus {
    border-color: #0EA5E9 !important;
    box-shadow: 0 0 0 3px rgba(14,165,233,0.15) !important;
    background: #FFFFFF !important;
    outline: none !important;
}

/* ── TABS (Login / Sign Up toggle) ──────────────────────────────────────────── */
/* Tab list bar */
[data-testid="stTabs"] [data-testid="stHorizontalBlock"],
[role="tablist"] {
    gap: 6px !important;
    margin-bottom: 1rem !important;
}
button[data-baseweb="tab"] {
    border-radius: 20px !important;
    padding: 6px 22px !important;
    font-size: 0.88rem !important;
    font-weight: 600 !important;
    border: 1.5px solid #E0F2FE !important;
    transition: background 0.20s ease, color 0.20s ease, box-shadow 0.20s ease !important;
    color: #64748B !important;
    background: transparent !important;
}
button[data-baseweb="tab"]:hover {
    background: #E0F2FE !important;
    color: #0284C7 !important;
    border-color: #BAE6FD !important;
}
button[data-baseweb="tab"][aria-selected="true"] {
    background: #0EA5E9 !important;
    color: #FFFFFF !important;
    border-color: #0EA5E9 !important;
    box-shadow: 0 2px 10px rgba(14,165,233,0.28) !important;
    font-weight: 700 !important;
}
/* Hide the default underline indicator */
[data-baseweb="tab-highlight"], [data-baseweb="tab-border"] {
    display: none !important;
}

/* ── PRIMARY BUTTON (Log in / Create account) ────────────────────────────────── */
button[kind="primary"],
button[data-testid="baseButton-primary"] {
    background: linear-gradient(135deg, #0EA5E9 0%, #0284C7 100%) !important;
    border: none !important;
    border-radius: 10px !important;
    padding: 11px 0 !important;
    font-size: 0.96rem !important;
    font-weight: 700 !important;
    letter-spacing: 0.2px !important;
    box-shadow: 0 3px 12px rgba(14,165,233,0.28) !important;
    transition: opacity 0.20s ease, transform 0.15s ease, box-shadow 0.20s ease !important;
    width: 100% !important;
}
button[kind="primary"]:hover,
button[data-testid="baseButton-primary"]:hover {
    opacity: 0.92 !important;
    transform: translateY(-1px) !important;
    box-shadow: 0 6px 20px rgba(14,165,233,0.36) !important;
}
button[kind="primary"]:active,
button[data-testid="baseButton-primary"]:active {
    transform: translateY(0) !important;
    opacity: 1 !important;
}

/* ── ERROR / SUCCESS ALERTS ──────────────────────────────────────────────────── */
[data-testid="stAlert"][data-baseweb="notification"] {
    border-radius: 10px !important;
    padding: 10px 14px !important;
    font-size: 0.88rem !important;
    margin-top: 0.75rem !important;
}
/* Error — soft red */
[data-testid="stAlert"][kind="error"],
[data-testid="stNotification"][kind="error"] {
    background: #FEF2F2 !important;
    border-left: 4px solid #EF4444 !important;
    color: #991B1B !important;
}
/* Success — soft green */
[data-testid="stAlert"][kind="success"],
[data-testid="stNotification"][kind="success"] {
    background: #F0FDF4 !important;
    border-left: 4px solid #22C55E !important;
    color: #166534 !important;
}
</style>
""", unsafe_allow_html=True)

    # ── auth page header (logo + brand) ──────────────────────────────────────
    st.markdown("""
<div class="ara-auth-wrap">
  <div class="ara-logo-wrap">
    <div class="ara-logo-box"></div>
  </div>
  <h1 class="ara-brand-name">AI Asset Rescue Agent</h1>
  <p class="ara-brand-tag">Explainable risk scoring and an AI agent<br>for smarter university asset management</p>
</div>
""", unsafe_allow_html=True)

    auth_login_tab, auth_signup_tab = st.tabs(["🔑  Login", "📝  Sign Up"])

    with auth_login_tab:
        with st.container(border=True):
            st.markdown("#### Welcome back")
            login_user = st.text_input("Username", key="login_user",
                                       placeholder="Enter your username")
            login_pass = st.text_input("Password", type="password", key="login_pass",
                                       placeholder="Enter your password")
            if st.button("Log in", type="primary", use_container_width=True, key="login_btn"):
                if not login_user or not login_pass:
                    st.error("Please enter both username and password.")
                elif _check_login(login_user, login_pass):
                    st.session_state["logged_in"]           = True
                    st.session_state["authenticated_user"]  = login_user.strip()
                    st.rerun()
                else:
                    st.error("❌ Incorrect username or password.")

    with auth_signup_tab:
        with st.container(border=True):
            st.markdown("#### Create an account")
            su_user  = st.text_input("Username", key="su_user",
                                     placeholder="Choose a username")
            su_pass  = st.text_input("Password", type="password", key="su_pass",
                                     placeholder="At least 8 characters")
            su_pass2 = st.text_input("Confirm password", type="password", key="su_pass2",
                                     placeholder="Repeat your password")
            if st.button("Create account", type="primary",
                         use_container_width=True, key="signup_btn"):
                if not su_user or not su_pass or not su_pass2:
                    st.error("All fields are required.")
                elif len(su_user.strip()) < 3:
                    st.error("Username must be at least 3 characters.")
                elif len(su_pass) < 8:
                    st.error("Password must be at least 8 characters.")
                elif su_pass != su_pass2:
                    st.error("Passwords do not match.")
                else:
                    ok, msg = _create_user(su_user, su_pass)
                    if ok:
                        st.success(f"✅ Account created! Switch to the Login tab to sign in.")
                    else:
                        st.error(f"❌ {msg}")

    st.stop()   # ← nothing below this renders until logged_in == True

# ═══════════════════════════════════════════════════════════════════════════════
#  COLOUR PALETTE  (sky-blue SaaS theme — consistent across charts and badges)
# ═══════════════════════════════════════════════════════════════════════════════
CLR_SKY    = "#0EA5E9"   # sky-500  — primary sky blue
CLR_SKY_D  = "#0284C7"   # sky-600  — darker sky for hover / borders
CLR_RED    = "#EF4444"   # red-500  — high / critical risk
CLR_AMBER  = "#F59E0B"   # amber-500 — underused / warning
CLR_GREEN  = "#22C55E"   # green-500 — healthy / normal use
CLR_BLUE   = CLR_SKY     # alias kept so nothing else needs changing
CLR_GREY   = "#94A3B8"   # slate-400 — neutral / decommissioned
CLR_MED    = "#FB923C"   # orange-400 — medium risk

STATUS_COLORS = {
    "Active":         CLR_GREEN,
    "Idle":           CLR_SKY,
    "Under Repair":   CLR_AMBER,
    "Decommissioned": CLR_GREY,
}

# ═══════════════════════════════════════════════════════════════════════════════
#  GLOBAL CSS  — sky-blue SaaS theme
# ═══════════════════════════════════════════════════════════════════════════════
st.markdown("""
<style>

/* ── FONTS & BASE ────────────────────────────────────────────────────────────── */
html, body, [class*="css"] {
    font-family: "Inter", "Segoe UI", system-ui, sans-serif;
}

/* ── 1. FADE-IN on every tab panel ─────────────────────────────────────────── */
@keyframes ara-fadein {
    from { opacity: 0; transform: translateY(8px); }
    to   { opacity: 1; transform: translateY(0);   }
}
[role="tabpanel"] { animation: ara-fadein 0.30s ease both; }

/* ── 2. NAVBAR BAND ─────────────────────────────────────────────────────────── */
.ara-navbar {
    background: linear-gradient(135deg, #0EA5E9 0%, #0284C7 100%);
    border-radius: 12px;
    padding: 16px 28px;
    margin-bottom: 18px;
    display: flex;
    align-items: center;
    gap: 14px;
    box-shadow: 0 4px 20px rgba(14,165,233,0.25);
}
.ara-navbar-icon {
    font-size: 2rem;
    line-height: 1;
    filter: drop-shadow(0 2px 4px rgba(0,0,0,0.15));
}
.ara-navbar-text h1 {
    margin: 0 0 2px 0;
    font-size: 1.35rem;
    font-weight: 800;
    color: #FFFFFF;
    letter-spacing: -0.2px;
}
.ara-navbar-text p {
    margin: 0;
    font-size: 0.8rem;
    color: rgba(255,255,255,0.82);
    font-weight: 400;
}

/* ── 3. PILL-STYLE TABS ─────────────────────────────────────────────────────── */
button[data-baseweb="tab"] {
    border-radius: 20px !important;
    padding: 6px 20px !important;
    font-size: 0.90rem !important;
    font-weight: 500 !important;
    transition: background 0.18s ease, color 0.18s ease, box-shadow 0.18s ease !important;
    border: 1.5px solid transparent !important;
}
button[data-baseweb="tab"]:hover {
    background: #E0F2FE !important;
    color: #0284C7 !important;
}
button[data-baseweb="tab"][aria-selected="true"] {
    background: #0EA5E9 !important;
    color: #FFFFFF !important;
    font-weight: 700 !important;
    box-shadow: 0 2px 10px rgba(14,165,233,0.30) !important;
    border-color: #0EA5E9 !important;
}

/* ── 4. HERO BANNER (dashboard tab) ─────────────────────────────────────────── */
.ara-hero {
    background: linear-gradient(120deg, #0EA5E9 0%, #38BDF8 55%, #BAE6FD 100%);
    border-radius: 14px;
    padding: 36px 40px 30px 40px;
    margin-bottom: 24px;
    position: relative;
    overflow: hidden;
}
/* subtle geometric decoration — pure CSS, no image */
.ara-hero::before {
    content: "";
    position: absolute;
    top: -40px; right: -40px;
    width: 200px; height: 200px;
    background: rgba(255,255,255,0.10);
    border-radius: 50%;
}
.ara-hero::after {
    content: "";
    position: absolute;
    bottom: -30px; right: 80px;
    width: 120px; height: 120px;
    background: rgba(255,255,255,0.08);
    border-radius: 50%;
}
.ara-hero h2 {
    margin: 0 0 8px 0;
    font-size: 1.85rem;
    font-weight: 800;
    color: #FFFFFF;
    line-height: 1.2;
    letter-spacing: -0.4px;
    position: relative; z-index: 1;
}
.ara-hero p {
    margin: 0;
    font-size: 0.95rem;
    color: rgba(255,255,255,0.88);
    max-width: 520px;
    position: relative; z-index: 1;
}
.ara-hero-badge {
    display: inline-block;
    background: rgba(255,255,255,0.20);
    border: 1px solid rgba(255,255,255,0.35);
    border-radius: 20px;
    padding: 3px 12px;
    font-size: 0.75rem;
    font-weight: 600;
    color: #FFFFFF;
    margin-bottom: 12px;
    position: relative; z-index: 1;
}

/* ── 5. KPI METRIC CARDS ─────────────────────────────────────────────────────── */
[data-testid="metric-container"] {
    background: #FFFFFF !important;
    border: 1.5px solid #BAE6FD !important;
    border-top: 3px solid #0EA5E9 !important;
    border-radius: 12px !important;
    padding: 16px 18px !important;
    box-shadow: 0 1px 6px rgba(14,165,233,0.08) !important;
    transition: box-shadow 0.2s ease, transform 0.2s ease !important;
}
[data-testid="metric-container"]:hover {
    box-shadow: 0 6px 20px rgba(14,165,233,0.18) !important;
    transform: translateY(-3px) !important;
}
[data-testid="metric-container"] [data-testid="stMetricLabel"] {
    font-size: 0.76rem !important;
    font-weight: 700 !important;
    color: #64748B !important;
    text-transform: uppercase !important;
    letter-spacing: 0.5px !important;
}
[data-testid="metric-container"] [data-testid="stMetricValue"] {
    font-size: 1.55rem !important;
    font-weight: 800 !important;
    color: #0F172A !important;
}

/* ── 6. ACTION-NEEDED CARDS ──────────────────────────────────────────────────── */
.action-card {
    background: #FFFFFF;
    border-left: 4px solid #EF4444;
    border-radius: 10px;
    padding: 14px 18px;
    margin-bottom: 10px;
    box-shadow: 0 1px 5px rgba(0,0,0,0.06);
    transition: box-shadow 0.20s ease, transform 0.20s ease;
}
.action-card:hover {
    box-shadow: 0 6px 20px rgba(239,68,68,0.14);
    transform: translateY(-2px);
}
.action-card h4 { margin: 0 0 4px 0; font-size: 0.94rem; font-weight: 700; color: #0F172A; }
.action-card p  { margin: 0; font-size: 0.82rem; color: #475569; }

/* ── 7. RISK BADGES ──────────────────────────────────────────────────────────── */
.badge {
    display: inline-block;
    padding: 3px 11px;
    border-radius: 20px;
    font-size: 0.73rem;
    font-weight: 700;
    letter-spacing: 0.4px;
    color: #fff;
}
.badge-red    { background: #EF4444; }
.badge-amber  { background: #F59E0B; }
.badge-yellow { background: #FB923C; }
.badge-green  { background: #22C55E; }

/* ── 8. PRIMARY BUTTONS ──────────────────────────────────────────────────────── */
button[kind="primary"],
button[data-testid="baseButton-primary"] {
    background: #0EA5E9 !important;
    border: none !important;
    border-radius: 8px !important;
    font-weight: 600 !important;
    transition: background 0.18s ease, box-shadow 0.18s ease, transform 0.15s ease !important;
}
button[kind="primary"]:hover,
button[data-testid="baseButton-primary"]:hover {
    background: #0284C7 !important;
    box-shadow: 0 4px 16px rgba(14,165,233,0.32) !important;
    transform: translateY(-1px) !important;
}
button[kind="secondary"],
button[data-testid="baseButton-secondary"] {
    border-radius: 8px !important;
    font-weight: 500 !important;
    transition: box-shadow 0.18s ease, transform 0.15s ease !important;
}
button[kind="secondary"]:hover,
button[data-testid="baseButton-secondary"]:hover {
    box-shadow: 0 3px 10px rgba(0,0,0,0.12) !important;
    transform: translateY(-1px) !important;
}

/* ── 9. APPROVE / REJECT PROPOSAL CARD ──────────────────────────────────────── */
[data-testid="stVerticalBlockBorderWrapper"] {
    border-radius: 14px !important;
    border-color: #BAE6FD !important;
    background: #F0F9FF !important;
    box-shadow: 0 2px 10px rgba(14,165,233,0.10) !important;
    transition: box-shadow 0.20s ease !important;
}
[data-testid="stVerticalBlockBorderWrapper"]:hover {
    box-shadow: 0 6px 22px rgba(14,165,233,0.15) !important;
}
/* Approve — green */
button[key="approve_btn"] {
    background: #16A34A !important;
}
button[key="approve_btn"]:hover {
    background: #15803D !important;
    box-shadow: 0 4px 16px rgba(22,163,74,0.30) !important;
}

/* ── 10. EXPANDERS ───────────────────────────────────────────────────────────── */
[data-testid="stExpander"] {
    border-radius: 10px !important;
    border-color: #BAE6FD !important;
    transition: box-shadow 0.18s ease !important;
}
[data-testid="stExpander"]:hover {
    box-shadow: 0 3px 10px rgba(14,165,233,0.10) !important;
}

/* ── 11. SIDEBAR ─────────────────────────────────────────────────────────────── */
[data-testid="stSidebar"] {
    border-right: 1px solid #BAE6FD !important;
    background: #F0F9FF !important;
}
[data-testid="stSidebar"] .stButton > button {
    border-radius: 8px !important;
    font-size: 0.85rem !important;
}

/* ── 12. DIVIDERS ────────────────────────────────────────────────────────────── */
hr { border-color: #E0F2FE !important; opacity: 1 !important; }

/* ── 13. LOGIN / SIGNUP SCREEN — base classes (detail in per-screen CSS) ──── */
.ara-auth-header { text-align: center; padding: 40px 0 16px 0; }
.ara-auth-title  { font-size: 1.7rem; font-weight: 800; color: #0F172A;
                   margin: 0 0 4px 0; letter-spacing: -0.3px; }
.ara-auth-sub    { font-size: 0.88rem; color: #64748B; margin: 0; }

/* ══════════════════════════════════════════════════════════════════════════════
   SPACING & LAYOUT POLISH — vertical rhythm, card consistency, responsive
   ══════════════════════════════════════════════════════════════════════════ */

/* ── S1. MAIN CONTENT AREA — breathable outer padding ───────────────────────── */
/* The block that wraps tab content */
[data-testid="stMainBlockContainer"] {
    padding-top: 1.5rem !important;
    padding-bottom: 3rem !important;
    max-width: 1400px !important;
}

/* ── S2. SECTION SPACING — consistent vertical rhythm between major blocks ───── */
/* Every st.subheader / st.markdown / st.divider gets breathing room above it */
[data-testid="stMarkdownContainer"] > h3,
[data-testid="stMarkdownContainer"] > h4 {
    margin-top: 2rem !important;
    margin-bottom: 0.75rem !important;
}
/* Subheaders rendered by Streamlit */
[data-testid="stHeadingWithActionElements"] {
    margin-top: 2rem !important;
    margin-bottom: 0.5rem !important;
    padding-bottom: 0.35rem !important;
}
/* Caption text — tighter to its parent */
[data-testid="stCaptionContainer"] {
    margin-top: 0.4rem !important;
    margin-bottom: 0.6rem !important;
    color: #64748B !important;
    font-size: 0.83rem !important;
}

/* ── S3. KPI CARD ROW — equal height, consistent gap, aligned content ─────────── */
/* The column wrappers that hold the metric containers */
[data-testid="stColumns"] > [data-testid="stColumn"] {
    padding-left:  0.5rem !important;
    padding-right: 0.5rem !important;
}
/* First / last column lose the extra outer half-rem */
[data-testid="stColumns"] > [data-testid="stColumn"]:first-child { padding-left:  0 !important; }
[data-testid="stColumns"] > [data-testid="stColumn"]:last-child  { padding-right: 0 !important; }
/* Metric containers: uniform height, padded, centred label */
[data-testid="metric-container"] {
    min-height: 90px !important;
    display: flex !important;
    flex-direction: column !important;
    justify-content: center !important;
    box-sizing: border-box !important;
}
/* Metric value: no extra margin below */
[data-testid="stMetricValue"] {
    line-height: 1.2 !important;
    margin-bottom: 0 !important;
}
/* Metric delta (hidden if unused) — prevent height jitter */
[data-testid="stMetricDelta"] { min-height: 0 !important; }

/* ── S4. ACTION-NEEDED CARDS — consistent internal layout ────────────────────── */
.action-card {
    padding: 16px 20px !important;
    margin-bottom: 12px !important;
    /* Uniform border system: left accent + all-sides border */
    border: 1.5px solid #FECACA !important;
    border-left: 4px solid #EF4444 !important;
    border-radius: 10px !important;
    box-sizing: border-box !important;
}
.action-card h4 {
    font-size: 0.93rem !important;
    font-weight: 700 !important;
    line-height: 1.4 !important;
    margin: 0 0 6px 0 !important;
    color: #0F172A !important;
}
.action-card p {
    font-size: 0.81rem !important;
    line-height: 1.55 !important;
    margin: 0 0 4px 0 !important;
    color: #475569 !important;
}
.action-card p:last-child { margin-bottom: 0 !important; }
/* "Suggested:" line — visually distinct */
.action-card p strong {
    color: #0284C7 !important;
    font-weight: 600 !important;
}

/* ── S5. CHART GRID — equal containers, consistent padding ───────────────────── */
/* Each chart's Plotly iframe wrapper */
[data-testid="stPlotlyChart"] {
    border-radius: 10px !important;
    overflow: hidden !important;
    border: 1.5px solid #E0F2FE !important;
    box-shadow: 0 1px 5px rgba(14,165,233,0.07) !important;
    margin-bottom: 0.5rem !important;
}
/* Space below the chart caption before the next chart row */
[data-testid="stPlotlyChart"] + [data-testid="stCaptionContainer"] {
    margin-bottom: 1.5rem !important;
}
/* Equal column gap for the 2×2 chart grid */
[data-testid="stHorizontalBlock"] {
    gap: 1.25rem !important;
    align-items: stretch !important;
}

/* ── S6. RISK TABLE — cell padding, row height ──────────────────────────────── */
/* Streamlit dataframe sits inside an iframe; style the wrapper frame */
[data-testid="stDataFrame"] {
    border-radius: 10px !important;
    border: 1.5px solid #E0F2FE !important;
    overflow: hidden !important;
    margin-bottom: 1rem !important;
}
/* Add a small gutter below the dataframe expander */
[data-testid="stExpander"] {
    margin-top: 0.5rem !important;
    margin-bottom: 1rem !important;
}

/* ── S7. SIDEBAR — consistent section spacing ────────────────────────────────── */
[data-testid="stSidebar"] [data-testid="stMarkdownContainer"] {
    padding: 0.1rem 0 !important;
}
/* Each sidebar widget (multiselect, button) gets equal top margin */
[data-testid="stSidebar"] [data-testid="stWidgetLabel"],
[data-testid="stSidebar"] .stMultiSelect,
[data-testid="stSidebar"] .stSelectbox {
    margin-top: 0.65rem !important;
}
/* Sidebar divider — extra breathing room */
[data-testid="stSidebar"] hr {
    margin: 1rem 0 !important;
}
/* Reset-filters button — adequate space above */
[data-testid="stSidebar"] .stButton {
    margin-top: 1rem !important;
}
/* "About" box — soft background card so it stands apart */
[data-testid="stSidebar"] [data-testid="stMarkdownContainer"] p,
[data-testid="stSidebar"] [data-testid="stMarkdownContainer"] li {
    font-size: 0.83rem !important;
    line-height: 1.6 !important;
    color: #334155 !important;
}

/* ── S8. CHAT TAB — spacing for buttons, messages, proposal card ─────────────── */
/* Example-question button columns: equal gap */
[data-testid="stColumn"] .stButton > button {
    min-height: 42px !important;
    padding: 8px 14px !important;
    font-size: 0.87rem !important;
    white-space: nowrap !important;
    overflow: hidden !important;
    text-overflow: ellipsis !important;
    width: 100% !important;
    box-sizing: border-box !important;
}
/* Chat message bubbles — consistent vertical spacing */
[data-testid="stChatMessage"] {
    margin-bottom: 0.75rem !important;
    padding: 0.25rem 0 !important;
}
/* Proposal card inner padding (the border=True container) */
[data-testid="stVerticalBlockBorderWrapper"] {
    padding: 20px 24px !important;
}
/* Approve / Reject button row — equal width, gap */
[data-testid="stVerticalBlockBorderWrapper"] [data-testid="stColumn"] {
    padding-left:  0.35rem !important;
    padding-right: 0.35rem !important;
}
[data-testid="stVerticalBlockBorderWrapper"] [data-testid="stColumn"]:first-child {
    padding-left: 0 !important;
}

/* ── S9. CARD SYSTEM UNIFICATION — one standard for all card-like elements ────── */
/* Canonical card token: 10px radius, E0F2FE border, white bg, soft shadow     */
/* Applied to: dataframes, expanders, plot wrappers, border containers          */
/* (metric-container, action-card, and proposal card already declared above)    */
[data-testid="stAlert"] {
    border-radius: 10px !important;
    padding: 12px 16px !important;
}

/* ── S10. RESPONSIVE GUARD — prevent overflow at 1280px+ ─────────────────────── */
/* Ensure text in narrow columns doesn't overflow */
[data-testid="stMetricLabel"],
[data-testid="stMetricValue"] {
    word-break: break-word !important;
    overflow-wrap: break-word !important;
}
/* Prevent the navbar from overflowing on narrow viewports */
.ara-navbar {
    flex-wrap: wrap !important;
    gap: 10px !important;
}

/* ── S11. ACTIONS LOG — expander spacing ─────────────────────────────────────── */
/* Each log expander row needs clear separation */
[data-testid="stExpander"] + [data-testid="stExpander"] {
    margin-top: 0.5rem !important;
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

    # ── logged-in user + logout ───────────────────────────────────────────────
    user_label = st.session_state.get("authenticated_user", "")
    st.caption(f"👤 Logged in as **{user_label}**")
    if st.button("🚪 Log out", use_container_width=True, key="logout_btn"):
        st.session_state["logged_in"]           = False
        st.session_state["authenticated_user"]  = ""
        st.rerun()
    st.divider()

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


# ── NAVBAR BAND (above tabs) ─────────────────────────────────────────────────
st.markdown("""
<div class="ara-navbar">
  <div class="ara-navbar-icon">🏛️</div>
  <div class="ara-navbar-text">
    <h1>AI Asset Rescue Agent</h1>
    <p>University equipment intelligence · powered by Azure AI Foundry + Azure AI Search</p>
  </div>
</div>
""", unsafe_allow_html=True)

# ═══════════════════════════════════════════════════════════════════════════════
#  TABS
# ═══════════════════════════════════════════════════════════════════════════════
tab_dash, tab_chat = st.tabs(["📊 Dashboard", "💬 Chat"])


# ╔═══════════════════════════════════════════════════════════════════════════╗
# ║  DASHBOARD TAB                                                           ║
# ╚═══════════════════════════════════════════════════════════════════════════╝
with tab_dash:
    # ── HERO BANNER ───────────────────────────────────────────────────────────
    st.markdown("""
<div class="ara-hero">
  <div class="ara-hero-badge">✦ Powered by Azure AI Foundry + Azure AI Search</div>
  <h2>Smarter asset management,<br>powered by AI.</h2>
  <p>Track equipment health, predict repair risk, and act before problems become expensive —
     with every action reviewed and approved by a human before anything is written.</p>
</div>
""", unsafe_allow_html=True)
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
            color_discrete_sequence=[CLR_SKY],
            title="Repair Risk Score Distribution",
            labels={"repair_risk": "Risk Score", "count": "Number of Assets"},
        )
        fig1.add_vline(x=60, line_dash="dash", line_color=CLR_AMBER,
                       annotation_text="High (60)", annotation_position="top right")
        fig1.add_vline(x=80, line_dash="dash", line_color=CLR_RED,
                       annotation_text="Critical (80)", annotation_position="top right")
        fig1.update_layout(height=CHART_H, margin=dict(t=50, b=10),
                           paper_bgcolor="white", plot_bgcolor="#F8FBFF")
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
            paper_bgcolor="white",
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
            color_discrete_sequence=["#0EA5E9","#38BDF8","#7DD3FC","#BAE6FD",
                                     "#0284C7","#0369A1","#22D3EE","#06B6D4",
                                     "#67E8F9","#A5F3FC"],
        )
        fig3.update_layout(
            showlegend=False,
            xaxis_tickangle=-35,
            height=CHART_H,
            margin=dict(t=50, b=80),
            paper_bgcolor="white", plot_bgcolor="#F8FBFF",
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
                "Normal Use":                    CLR_SKY,
            },
            barmode="stack",
        )
        fig4.update_layout(
            height=CHART_H,
            xaxis_tickangle=-30,
            margin=dict(t=50, b=80),
            paper_bgcolor="white", plot_bgcolor="#F8FBFF",
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
                    result = execute_action(proposal, performed_by=st.session_state.get("authenticated_user", "chat_user"))
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
