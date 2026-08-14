"""
Application Ledger — Python/Streamlit version (Gemini-powered)
------------------------------------------------
Paste a job/internship posting, and this app uses Gemini to extract
structured fields (company, role, location, deadline, pay, key
requirements), then runs a fuzzy duplicate check before saving.

Setup:
    pip install streamlit google-genai pandas

Note: uses st.segmented_control, which requires Streamlit 1.36+.
If it's missing, run: pip install --upgrade streamlit

Run:
    streamlit run application_tracker.py

You'll need a free Gemini API key from https://aistudio.google.com/apikey
Enter it in the sidebar when the app opens, or set it as an
environment variable before running:
    export GEMINI_API_KEY=...   (Mac/Linux)
    set GEMINI_API_KEY=...      (Windows)

Note: Gemini's free tier has rate limits (roughly 10-15 requests per
minute depending on the model) and Google may use free-tier requests
to improve their models — fine for job postings, just worth knowing.

Also note: Google deprecated the old `google-generativeai` package in
favor of the unified `google-genai` SDK (this file uses the new one).
If you previously installed `google-generativeai`, uninstall it and
install `google-genai` instead — the two can't be mixed reliably.
"""

import json
import os
import re
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st
from google import genai
from google.genai import types

DATA_FILE = Path("applications.json")
# Pinned to the model confirmed available in Google AI Studio as of Aug 2026.
# Note: this is a "preview" model, which Google can deprecate with as little
# as 2 weeks' notice — if this breaks again later, check aistudio.google.com's
# model picker for the current name and swap it in here.
MODEL = "gemini-3-flash-preview"

COMPANY_MATCH_THRESHOLD = 0.82
ROLE_MATCH_THRESHOLD = 0.70

CUSTOM_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Oswald:wght@500;600;700&family=IBM+Plex+Mono:wght@400;500;600&family=Inter:wght@400;500;600&display=swap');

:root {
  --bg: #0c0f16;
  --bg-raised: #171b26;
  --ticket: #f4ecdb;
  --ticket-edge: #d8c9a3;
  --ink: #e9e4d6;
  --ink-dim: #8b8fa0;
  --navy: #262117;
  --navy-dim: #6f6a5c;
  --amber: #e8a33d;
  --amber-deep: #b97b22;
  --teal: #3fa89f;
  --danger: #c0573f;
  --line: #262c3d;
}

.stApp {
  background:
    radial-gradient(ellipse at top left, #131826 0%, transparent 55%),
    var(--bg) !important;
}
html, body, [class*="css"] { font-family: 'Inter', -apple-system, sans-serif; color: var(--ink); }

/* Masthead */
.ledger-masthead {
  display: flex; align-items: flex-end; justify-content: space-between;
  border-bottom: 2px solid var(--line); padding-bottom: 14px; margin-bottom: 6px;
}
.ledger-masthead h1 {
  font-family: 'Oswald', sans-serif; font-weight: 600; font-size: 30px; margin: 0;
  letter-spacing: 0.5px; text-transform: uppercase; color: var(--ink);
}
.ledger-tag {
  font-family: 'IBM Plex Mono', monospace; font-size: 10px; color: #0c0f16;
  letter-spacing: 1.5px; text-transform: uppercase; background: var(--amber);
  padding: 4px 9px; border-radius: 3px; font-weight: 600;
}

/* Sidebar */
section[data-testid="stSidebar"] {
  background: var(--bg-raised) !important; border-right: 1px solid var(--line);
}
section[data-testid="stSidebar"] * { color: var(--ink) !important; }

/* Buttons */
.stButton > button, .stDownloadButton > button, .stFormSubmitButton > button {
  font-family: 'Inter', sans-serif !important; font-weight: 600 !important;
  border-radius: 5px !important; border: 1px solid var(--line) !important;
}
.stButton > button[kind="primary"], .stFormSubmitButton > button[kind="primary"] {
  background: var(--amber) !important; color: #201705 !important; border: none !important;
}
.stButton > button[kind="secondary"] {
  background: transparent !important; color: var(--ink-dim) !important;
}

/* Text areas / inputs */
.stTextArea textarea, .stTextInput input {
  background: var(--bg-raised) !important; color: var(--ink) !important;
  border: 1px solid var(--line) !important; font-family: 'Inter', sans-serif !important;
}

/* Logged application cards — clean native container, not a forced re-skin */
div[class*="st-key-card_"] {
  background: var(--bg-raised) !important;
  border-radius: 10px !important;
  border: 1px solid var(--line) !important;
  border-left: 3px solid var(--amber) !important;
  padding: 4px 4px !important;
}
div[class*="st-key-card_"] .role-title {
  font-family: 'Oswald', sans-serif; font-size: 17px; font-weight: 600; color: var(--ink);
  text-transform: uppercase; letter-spacing: 0.2px;
}
div[class*="st-key-card_"] .company-tag {
  font-family: 'IBM Plex Mono', monospace; font-size: 11px; color: var(--amber);
  text-transform: uppercase; letter-spacing: 0.8px; font-weight: 600;
}
div[class*="st-key-card_"] .meta-caption {
  font-family: 'IBM Plex Mono', monospace !important; font-size: 11px !important; color: var(--ink-dim) !important;
}

/* Segmented control (status) — style to feel native to the dark theme, not overridden hard */
div[class*="st-key-card_"] [data-testid="stSegmentedControl"] label {
  font-family: 'IBM Plex Mono', monospace !important; font-size: 10.5px !important;
  text-transform: uppercase !important; letter-spacing: 0.4px !important;
}

/* Requirement chips via inline code styling (native monospace pill look) */
div[class*="st-key-card_"] code {
  background: rgba(63,168,159,0.15) !important; color: #6fc7bd !important;
  border: 1px solid rgba(63,168,159,0.35) !important; border-radius: 3px !important;
}
</style>
"""


# ---------- Local persistence ----------

def load_applications():
    if DATA_FILE.exists():
        try:
            return json.loads(DATA_FILE.read_text())
        except (json.JSONDecodeError, OSError):
            return []
    return []


def save_applications(apps):
    DATA_FILE.write_text(json.dumps(apps, indent=2))


# ---------- Fuzzy matching (Levenshtein-based, no extra dependency) ----------

def levenshtein(a: str, b: str) -> int:
    m, n = len(a), len(b)
    if m == 0:
        return n
    if n == 0:
        return m
    prev = list(range(n + 1))
    for i in range(1, m + 1):
        curr = [i] + [0] * n
        for j in range(1, n + 1):
            cost = 0 if a[i - 1] == b[j - 1] else 1
            curr[j] = min(prev[j] + 1, curr[j - 1] + 1, prev[j - 1] + cost)
        prev = curr
    return prev[n]


def similarity(a: str, b: str) -> float:
    s1, s2 = (a or "").lower().strip(), (b or "").lower().strip()
    if not s1 and not s2:
        return 1.0
    if not s1 or not s2:
        return 0.0
    max_len = max(len(s1), len(s2))
    return 1 - levenshtein(s1, s2) / max_len


def find_duplicate(apps, company, role):
    for a in apps:
        if (
            similarity(a["company"], company) >= COMPANY_MATCH_THRESHOLD
            and similarity(a["role"], role) >= ROLE_MATCH_THRESHOLD
        ):
            return a
    return None


# ---------- Gemini extraction ----------

def extract_posting(api_key: str, posting_text: str) -> dict:
    prompt = f"""Extract the application details from this job/internship posting and respond with ONLY a raw JSON object, no markdown fences, no preamble, no explanation — just the JSON.

Schema:
{{
  "company": string,
  "role": string,
  "location": string (city/state, "Remote", or "Not specified"),
  "deadline": string (application deadline if stated, else "Not specified"),
  "pay": string (salary/pay if stated, else "Not specified"),
  "key_requirements": array of 3-5 short strings, the standout requirements or skills from the posting
}}

Posting:
{posting_text}"""

    client = genai.Client(api_key=api_key)
    response = client.models.generate_content(
        model=MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(max_output_tokens=1000),
    )

    raw_text = response.text or ""
    cleaned = re.sub(r"```json|```", "", raw_text).strip()
    return json.loads(cleaned)  # raises json.JSONDecodeError if malformed — caught by caller


# ---------- CSV export ----------

def apps_to_dataframe(apps):
    rows = []
    for a in apps:
        rows.append(
            {
                "Company": a["company"],
                "Role": a["role"],
                "Location": a["location"],
                "Deadline": a["deadline"],
                "Pay": a["pay"],
                "Status": a["status"],
                "Requirements": "; ".join(a.get("requirements", [])),
                "Logged": a["added_at"][:10],
            }
        )
    return pd.DataFrame(rows)


# ---------- Streamlit UI ----------

def main():
    st.set_page_config(page_title="Application Ledger", page_icon="🎫", layout="centered")
    st.markdown(CUSTOM_CSS, unsafe_allow_html=True)

    if "apps" not in st.session_state:
        st.session_state.apps = load_applications()
    if "pending_dup" not in st.session_state:
        st.session_state.pending_dup = None

    st.markdown(
        f"""
        <div class="ledger-masthead">
            <h1>✈ Application Ledger</h1>
            <div style="text-align:right;">
                <span class="ledger-tag">Agent-assisted</span><br/>
                <span style="font-family:'IBM Plex Mono',monospace; font-size:11px; color:var(--ink-dim);">
                    {len(st.session_state.apps)} logged
                </span>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.caption("Paste a posting → We extract the details → logged locally.")

    # --- API key ---
    with st.sidebar:
        st.subheader("Gemini API Key")
        env_key = os.environ.get("GEMINI_API_KEY", "")
        api_key = st.text_input(
            "API key",
            value=env_key,
            type="password",
            help="Get a free key at aistudio.google.com/apikey. Not stored anywhere except this session.",
        )
        st.caption(f"{len(st.session_state.apps)} applications logged")
        if st.session_state.apps:
            csv = apps_to_dataframe(st.session_state.apps).to_csv(index=False)
            st.download_button(
                "⬇ Export CSV",
                data=csv,
                file_name=f"applications_{datetime.now().strftime('%Y-%m-%d')}.csv",
                mime="text/csv",
            )

    # --- Input box (wrapped in a form so one click submits the text + triggers extraction together) ---
    with st.form(key="posting_form", clear_on_submit=False):
        posting_text = st.text_area(
            "Paste a job or internship posting",
            height=180,
            placeholder="Company, role, requirements, deadline — whatever you have...",
        )
        extract_clicked = st.form_submit_button("Extract & log", type="primary")

    clear_clicked = st.button("Clear")
    if clear_clicked:
        st.rerun()

    def commit_entry(extracted):
        entry = {
            "id": datetime.now().strftime("%Y%m%d%H%M%S%f"),
            "company": extracted.get("company", "Unknown"),
            "role": extracted.get("role", "Unknown"),
            "location": extracted.get("location", "Not specified"),
            "deadline": extracted.get("deadline", "Not specified"),
            "pay": extracted.get("pay", "Not specified"),
            "requirements": extracted.get("key_requirements", []),
            "status": "Applied",
            "added_at": datetime.now().isoformat(),
        }
        st.session_state.apps.insert(0, entry)
        save_applications(st.session_state.apps)
        st.session_state.pending_dup = None
        st.success(f"Logged {entry['company']} — {entry['role']}")

    if extract_clicked:
        if not posting_text.strip():
            st.warning("Paste a posting before extracting.")
        elif not api_key:
            st.error("Add your Gemini API key in the sidebar first.")
        else:
            with st.spinner("Reading posting..."):
                try:
                    extracted = extract_posting(api_key, posting_text)
                    dup = find_duplicate(st.session_state.apps, extracted.get("company", ""), extracted.get("role", ""))
                    if dup:
                        st.session_state.pending_dup = {"extracted": extracted, "match": dup}
                    else:
                        commit_entry(extracted)
                except json.JSONDecodeError:
                    st.error("Couldn't parse the model's response as JSON. Try pasting more of the posting.")
                except Exception as e:
                    st.error(f"Error: {e}")

    # --- Duplicate confirmation ---
    if st.session_state.pending_dup:
        dup = st.session_state.pending_dup
        st.warning(
            f"Possible duplicate — you already have **{dup['match']['company']} — {dup['match']['role']}** "
            f"logged on {dup['match']['added_at'][:10]}."
        )
        c1, c2 = st.columns([1, 1])
        if c1.button("Add anyway"):
            commit_entry(dup["extracted"])
            st.rerun()
        if c2.button("Skip"):
            st.session_state.pending_dup = None
            st.rerun()

    st.divider()

    # --- Ledger ---
    if not st.session_state.apps:
        st.info("No applications logged yet. Paste your first posting above.")

    status_order = ["Applied", "Interviewing", "Rejected", "Offer"]

    for app in st.session_state.apps:
        with st.container(border=True, key=f"card_{app['id']}"):
            top1, top2 = st.columns([2.2, 1.8])
            with top1:
                st.markdown(f'<div class="role-title">{app["role"]}</div>', unsafe_allow_html=True)
                st.markdown(f'<div class="company-tag">{app["company"]}</div>', unsafe_allow_html=True)
            with top2:
                new_status = st.segmented_control(
                    "Status",
                    status_order,
                    default=app["status"],
                    key=f"status_{app['id']}",
                    label_visibility="collapsed",
                )
                if new_status and new_status != app["status"]:
                    app["status"] = new_status
                    save_applications(st.session_state.apps)

            st.markdown(
                f'<div class="meta-caption">📍 {app["location"]} &nbsp;·&nbsp; 🗓 {app["deadline"]} '
                f'&nbsp;·&nbsp; 💵 {app["pay"]} &nbsp;·&nbsp; logged {app["added_at"][:10]}</div>',
                unsafe_allow_html=True,
            )
            if app.get("requirements"):
                st.markdown(
                    " ".join(f"`{r}`" for r in app["requirements"]),
                )

            b1, b2, _ = st.columns([1, 1, 4])
            edit_key = f"editing_{app['id']}"
            if b1.button("Edit", key=f"edit_btn_{app['id']}"):
                st.session_state[edit_key] = not st.session_state.get(edit_key, False)
            if b2.button("Remove", key=f"remove_btn_{app['id']}"):
                st.session_state.apps = [a for a in st.session_state.apps if a["id"] != app["id"]]
                save_applications(st.session_state.apps)
                st.rerun()

            if st.session_state.get(edit_key):
                with st.form(key=f"edit_form_{app['id']}"):
                    new_role = st.text_input("Role", value=app["role"])
                    new_company = st.text_input("Company", value=app["company"])
                    c1, c2, c3 = st.columns(3)
                    new_location = c1.text_input("Location", value=app["location"])
                    new_deadline = c2.text_input("Deadline", value=app["deadline"])
                    new_pay = c3.text_input("Pay", value=app["pay"])
                    new_reqs = st.text_input(
                        "Requirements (comma-separated)",
                        value=", ".join(app.get("requirements", [])),
                    )
                    if st.form_submit_button("Save"):
                        app["role"] = new_role.strip() or app["role"]
                        app["company"] = new_company.strip() or app["company"]
                        app["location"] = new_location.strip() or "Not specified"
                        app["deadline"] = new_deadline.strip() or "Not specified"
                        app["pay"] = new_pay.strip() or "Not specified"
                        app["requirements"] = [r.strip() for r in new_reqs.split(",") if r.strip()]
                        save_applications(st.session_state.apps)
                        st.session_state[edit_key] = False
                        st.rerun()


if __name__ == "__main__":
    main()