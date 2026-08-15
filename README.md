# Application Ledger

An AI-assisted tool that turns a pasted job/internship posting into a structured, trackable record — built with Python and Streamlit.

## Deployed App
https://applicationtrackerbyrhea.streamlit.app/

## What it does

1. Paste any job or internship posting into the text box.
2. The app sends the text to Google's Gemini API with a JSON schema in the prompt, asking for a structured extraction: company, role, location, deadline, pay, and 3-5 key requirements.
3. Before saving, a fuzzy duplicate check (hand-written Levenshtein distance, no external library) compares the extracted company + role against everything already logged, and flags a likely duplicate — even close variants like "Google" vs. "Google LLC" — instead of silently double-logging it.
4. Each entry renders as a card with a segmented status control: **Applied → Interviewing → Rejected → Offer**.
5. Entries can be edited inline or removed, and the full list can be exported to CSV.
6. Everything persists locally in `applications.json`.

## Why I built it

I was applying to a high volume of internships and kept losing track of what I'd already applied to, deadlines, and requirements per role. This automates the tedious part (reading and structuring a posting) while keeping the decision-relevant logic (duplicate detection) simple, transparent, and not dependent on the model getting it right.

## Tech stack

- **Python** + **Streamlit** for the UI and app logic
- **Google Gemini API** (`google-genai`, the current unified SDK) for structured extraction, using a JSON-in-prompt pattern with manual `json.loads` parsing
- **Pandas** for CSV export
- Local JSON file for persistence — no database required for personal use

## Setup

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

Get a free Gemini API key at [aistudio.google.com/apikey](https://aistudio.google.com/apikey), then set it as an environment variable:

```bash
export GEMINI_API_KEY=your_key_here
```

(Add that line to your `~/.zshrc` to make it permanent across terminal sessions.)

## Run

```bash
streamlit run application_tracker.py
```

## Deployment

This app can be deployed on [Streamlit Community Cloud](https://share.streamlit.io) for free. When deployed, add `GEMINI_API_KEY` under the app's **Secrets** settings instead of a local environment variable — the code checks Streamlit's secrets manager first, falling back to a local env var.

**Known limitation:** Streamlit Cloud's filesystem is ephemeral, so `applications.json` will not reliably persist across app restarts/redeploys in a cloud deployment. This app is built for local, personal use; a public deployment is best treated as a live demo, not a durable tracker, unless swapped to a real database.

## A note on the extraction approach

I originally prototyped this with Anthropic's Claude API using native tool-calling and a forced `tool_choice`, expecting the model to always return a structured tool-call object. That wasn't reliably honored in the environment I was prototyping in, so I switched to prompting for raw JSON output and parsing it manually — a more portable pattern that also made it easy to swap the underlying model later (this version runs on Gemini instead, with the extraction logic unchanged).

## What I'd improve next

- **Bulk import** — paste multiple postings at once and extract them in a batch
- **Deadline highlighting** — surface applications with upcoming deadlines instead of just listing history
- **Confidence flagging on extraction** — have the model explicitly flag low-confidence fields (e.g. an unclear deadline) instead of silently defaulting to "Not specified"
- **Tests for fuzzy matching** — the similarity thresholds (0.82 company / 0.7 role) were set by intuition; a small test set of known duplicates/non-duplicates would validate and justify them
- **Real database backend** — swap the local JSON file for SQLite or Postgres to make cloud deployment durable

---
