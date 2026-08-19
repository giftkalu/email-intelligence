"""
Email Intelligence - process.py

One-time (rerunnable) script:
  1. Fetch emails from the last 2 days via Gmail API
  2. Analyze each with Gemini (category, priority, action, deadline, summary)
  3. Store results in SQLite

Setup required before running - see README.md.

Run: python process.py
"""

import base64
import json
import os
import sqlite3
import time
from email.utils import parsedate_to_datetime

from dotenv import load_dotenv
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
import google.generativeai as genai

load_dotenv()

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]
DB_PATH = "emails.db"
GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]
QUERY = "newer_than:2d -category:promotions -category:social"
MAX_BODY_CHARS = 1500

genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel("gemini-3.6-flash")


def gmail_service():
    creds = None
    if os.path.exists("token.json"):
        creds = Credentials.from_authorized_user_file("token.json", SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file("credentials.json", SCOPES)
            creds = flow.run_local_server(port=0)
        with open("token.json", "w") as f:
            f.write(creds.to_json())
    return build("gmail", "v1", credentials=creds)


def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS emails (
        gmail_id TEXT PRIMARY KEY,
        sender TEXT,
        subject TEXT,
        received_at TEXT,
        email_url TEXT,
        category TEXT,
        priority TEXT,
        requires_action INTEGER,
        deadline_phrase TEXT,
        deadline_date TEXT,
        summary TEXT,
        suggested_action TEXT,
        reasoning TEXT,
        attended INTEGER DEFAULT 0,
        processed_at TEXT
        )
    """)
    conn.commit()
    return conn


def already_processed(conn, gmail_id):
    cur = conn.execute("SELECT 1 FROM emails WHERE gmail_id = ?", (gmail_id,))
    return cur.fetchone() is not None


def extract_body(payload) -> str:
    if payload.get("body", {}).get("data"):
        return base64.urlsafe_b64decode(payload["body"]["data"]).decode("utf-8", errors="ignore")
    for part in payload.get("parts", []) or []:
        if part.get("mimeType") == "text/plain" and part.get("body", {}).get("data"):
            return base64.urlsafe_b64decode(part["body"]["data"]).decode("utf-8", errors="ignore")
    for part in payload.get("parts", []) or []:
        text = extract_body(part)
        if text:
            return text
    return ""


def get_header(headers, name):
    for h in headers:
        if h["name"].lower() == name.lower():
            return h["value"]
    return ""

def analyze_emails(emails) -> list:
    email_text = ""

    for i, email in enumerate(emails):
        email_text += f"""
--- EMAIL {i} ---
Gmail ID: {email["gmail_id"]}
From: {email["sender"]}
Subject: {email["subject"]}
Received: {email["received_at"]}
Body:
{email["body"][:MAX_BODY_CHARS]}
--- END EMAIL {i} ---
"""

    prompt = f"""You are an email intelligence assistant.

Analyze ALL of the emails below.

For EACH email determine:

1. category: one of Job, University, Networking, Finance, Personal, Promotion, Other
2. priority: high, medium, or low
3. requires_action: true or false
4. deadline_phrase: the exact phrase from the email mentioning a deadline, or "none"
5. deadline_date: best-effort ISO date (YYYY-MM-DD), or "none"
6. summary: one sentence
7. suggested_action: the single most useful next action, or "none"
8. reasoning: one short sentence explaining the priority

IMPORTANT:
- Do not invent deadlines.
- Do not invent actions.
- If information is insufficient, use "none".
- Return exactly ONE result for every email.
- Keep the Gmail ID exactly as provided.

Return ONLY valid JSON in this format:

[
  {{
    "gmail_id": "",
    "category": "",
    "priority": "",
    "requires_action": false,
    "deadline_phrase": "",
    "deadline_date": "",
    "summary": "",
    "suggested_action": "",
    "reasoning": ""
  }}
]

EMAILS:

{email_text}
"""

    response = model.generate_content(prompt)

    text = (
        response.text
        .strip()
        .replace("```json", "")
        .replace("```", "")
        .strip()
    )

    return json.loads(text)

def run():
    conn = init_db()
    service = gmail_service()

    results = service.users().messages().list(
        userId="me",
        q=QUERY,
        maxResults=500
    ).execute()

    messages = results.get("messages", [])

    print(f"Found {len(messages)} emails from the last 3 days")

    emails_to_analyze = []

    for i, msg_ref in enumerate(messages, 1):
        gmail_id = msg_ref["id"]

        if already_processed(conn, gmail_id):
            continue

        msg = service.users().messages().get(
            userId="me",
            id=gmail_id,
            format="full"
        ).execute()

        headers = msg["payload"]["headers"]

        sender = get_header(headers, "From")
        subject = get_header(headers, "Subject")
        date_header = get_header(headers, "Date")

        try:
            received_at = parsedate_to_datetime(
                date_header
            ).isoformat()
        except Exception:
            received_at = date_header

        body = extract_body(msg["payload"])

        emails_to_analyze.append({
            "gmail_id": gmail_id,
            "sender": sender,
            "subject": subject,
            "received_at": received_at,
            "email_url": f"https://mail.google.com/mail/u/0/#all/{gmail_id}",
            "body": body
        })

    if not emails_to_analyze:
        print("No new emails to analyze.")
        conn.close()
        return

    print(
        f"Sending {len(emails_to_analyze)} emails "
        "to Gemini in ONE API call..."
    )

    try:
        analyses = analyze_emails(emails_to_analyze)

    except Exception as e:
        print(f"Gemini analysis failed: {e}")
        conn.close()
        return

    print(f"Received {len(analyses)} analyses from Gemini")

    email_lookup = {
    email["gmail_id"]: email
    for email in emails_to_analyze
    }

    for analysis in analyses:

        email = email_lookup.get(analysis["gmail_id"])
        email_url = f"https://mail.google.com/mail/u/0/#all/{email['gmail_id']}"

        if not email:
            print(
                f"Warning: Gemini returned unknown Gmail ID "
                f"{analysis['gmail_id']}"
            )
            continue

        conn.execute(
    """INSERT INTO emails (
        gmail_id,
        sender,
        subject,
        received_at,
        email_url,
        category,
        priority,
        requires_action,
        deadline_phrase,
        deadline_date,
        summary,
        suggested_action,
        reasoning,
        attended,
        processed_at
    )
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, datetime('now'))""",
    (
        email["gmail_id"],
        email["sender"],
        email["subject"],
        email["received_at"],
        email_url,
        analysis.get("category", "Other"),
        analysis.get("priority", "low"),
        1 if analysis.get("requires_action") else 0,
        analysis.get("deadline_phrase", "none"),
        analysis.get("deadline_date", "none"),
        analysis.get("summary", ""),
        analysis.get("suggested_action", "none"),
        analysis.get("reasoning", ""),
    )
)
    conn.commit()
    conn.close()

    print("Done. Run: streamlit run app.py")


if __name__ == "__main__":
    run()
