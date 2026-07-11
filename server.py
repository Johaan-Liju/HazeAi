"""
Phase 2, Step 6 — the web server, now with guardrails.

Three cheap safety rails before going public (no extra libraries needed):
  1. Rate limiting   — one visitor can't spam thousands of messages (guardrails.py)
  2. Size caps       — no giant pasted walls of text, and no fake "system" role
                       (enforced right on the request model below)
  3. CORS allowlist  — only YOUR customers' websites may call this from a browser

Run it:   uvicorn server:app --reload
Test at http://127.0.0.1:8000/docs , demo at http://127.0.0.1:8000/demo
"""

from html import escape
from typing import Literal

from fastapi import BackgroundTasks, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
from pydantic import BaseModel, Field

import brain
import guardrails
import mailer
from companies import COMPANIES, knowledge_path, lead_email

app = FastAPI()

# --- CORS: which websites may call this server from a browser ----------------
# The widget runs on your CUSTOMERS' sites, so each customer's domain must be
# listed here. A browser on any other site gets blocked. (This is browser-level:
# add a customer's domain when you onboard them.)
ALLOWED_ORIGINS = [
    "http://127.0.0.1:8000",   # local testing (the /demo page)
    "http://localhost:8000",
    "https://coverfirst.in",
    "https://www.coverfirst.in",
    "https://ifihomes.com",
    "https://www.ifihomes.com",
    "https://hazeai.in",        # our own landing site (widget demos itself)
    "https://www.hazeai.in",
    "http://127.0.0.1:5500",   # local preview of website/ (python -m http.server 5500)
    "http://localhost:5500",
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

# Load every company's knowledge once, when the server starts.
KNOWLEDGE = {
    company_id: brain.load_knowledge(knowledge_path(company_id))
    for company_id in COMPANIES
}


# --- The shape of a request and a reply (with size limits) -------------------
class Message(BaseModel):
    # Only "user" or "assistant" — a visitor can't sneak in a "system" message
    # to override the bot's grounding rules.
    role: Literal["user", "assistant"]
    content: str = Field(max_length=2000)   # cap one message's length


class ChatRequest(BaseModel):
    company: str = Field(max_length=64)
    # At least 1 message, at most 20 (the widget only sends the last 10 anyway).
    messages: list[Message] = Field(min_length=1, max_length=20)


class ChatReply(BaseModel):
    reply: str


class LeadRequest(BaseModel):
    """A visitor leaving their number for a callback (the lead-capture form)."""
    company: str = Field(max_length=64)
    phone: str = Field(min_length=1, max_length=40)      # must leave a number
    question: str = Field(default="", max_length=1000)   # their message (optional)


# --- Endpoints ---------------------------------------------------------------
@app.get("/")
def home():
    """Health check — also lists which companies this server is serving."""
    return {"status": "ok", "companies": list(COMPANIES)}


# "no-cache" doesn't mean "don't cache" — it means "ask the server if this
# changed before using your saved copy". Unchanged files still come back as a
# tiny instant 304, but the moment you deploy a new widget every browser picks
# it up on the next page load. Without this, browsers guess how long to keep
# files and visitors can be stuck on an old widget for days.
ALWAYS_REVALIDATE = {"Cache-Control": "no-cache"}


@app.get("/widget.js")
def widget_js():
    """The chat widget script that a customer's website loads."""
    return FileResponse(
        "web/widget.js",
        media_type="application/javascript",
        headers=ALWAYS_REVALIDATE,
    )


# Shown when a demo link points at a company that isn't set up (typo, or a
# prospect forwarding an old link). Friendly, and turns even a dead link into
# a contact opportunity.
DEMO_404 = """<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Demo not found</title></head>
<body style="font-family:system-ui,sans-serif;display:grid;place-items:center;
min-height:100vh;margin:0;background:#f4f5fb;color:#1c1c28;text-align:center;padding:24px">
<div><div style="font-size:44px">🤖</div>
<h1 style="margin:10px 0 6px;font-size:24px">This demo isn't live yet</h1>
<p style="max-width:420px;color:#555">The link may have a typo — or this demo
just hasn't been set up. Email
<a href="mailto:johaanliju@gmail.com" style="color:#4f46e5">johaanliju@gmail.com</a>
and it can be ready within a day.</p></div>
</body></html>"""


@app.get("/demo")
def demo(company: str = "coverfirst"):
    """The per-prospect demo page: /demo?company=<id> shows THAT company's bot.

    This is the sales link you send a prospect after crawling their site —
    the page greets them by name and their own chatbot opens by itself.
    Onboarding a prospect is the usual two steps (knowledge file + one line
    in companies.py); their demo link then just works.
    """
    company = company.strip().lower()
    if company not in COMPANIES:
        return HTMLResponse(DEMO_404, status_code=404, headers=ALWAYS_REVALIDATE)

    with open("web/demo.html", encoding="utf-8") as f:
        page = f.read()
    # The id is a validated COMPANIES key; the display name is escaped in case
    # one ever contains an HTML-special character like &.
    page = page.replace("{{COMPANY_ID}}", company)
    page = page.replace("{{COMPANY_NAME}}", escape(COMPANIES[company]))
    return HTMLResponse(page, headers=ALWAYS_REVALIDATE)


def _resolve(payload: ChatRequest):
    """Check the company is known, then return its (name, knowledge, messages)."""
    if payload.company not in COMPANIES:
        raise HTTPException(
            status_code=404, detail=f"Unknown company '{payload.company}'"
        )
    company_name = COMPANIES[payload.company]
    knowledge = KNOWLEDGE[payload.company]
    messages = [{"role": m.role, "content": m.content} for m in payload.messages]
    return company_name, knowledge, messages


@app.post("/chat", response_model=ChatReply)
def chat(payload: ChatRequest, request: Request):
    """Take the conversation (for a specific company), ask the brain, reply."""
    guardrails.check_rate_limit(request)
    company_name, knowledge, messages = _resolve(payload)

    reply, usage = brain.answer(company_name, knowledge, messages)
    print(
        f"[/chat {payload.company}] out {usage.output_tokens} tokens "
        f"· ~${brain.cost_usd(usage):.5f}"
    )
    return ChatReply(reply=reply)


@app.post("/chat/stream")
def chat_stream(payload: ChatRequest, request: Request):
    """Same as /chat, but streams the reply back piece by piece (used by the widget)."""
    guardrails.check_rate_limit(request)
    company_name, knowledge, messages = _resolve(payload)

    def generate():
        # Open the stream, hand each piece of text straight out to the browser.
        with brain.stream_answer(company_name, knowledge, messages) as stream:
            for piece in stream.text_stream:
                yield piece
            usage = stream.get_final_message().usage
        # Once the whole reply is sent, print what it cost.
        print(
            f"[/chat/stream {payload.company}] out {usage.output_tokens} tokens "
            f"· ~${brain.cost_usd(usage):.5f}"
        )

    return StreamingResponse(generate(), media_type="text/plain")


@app.post("/lead")
def lead(payload: LeadRequest, request: Request, background: BackgroundTasks):
    """A visitor left their number — email the lead to that company's owner."""
    guardrails.check_rate_limit(request)
    if payload.company not in COMPANIES:
        raise HTTPException(
            status_code=404, detail=f"Unknown company '{payload.company}'"
        )
    company_name = COMPANIES[payload.company]
    print(f"[/lead {payload.company}] phone={payload.phone!r} — emailing in background")
    # Send the email AFTER responding: the visitor gets an instant "thanks"
    # instead of staring at a frozen button while we talk to the mail server.
    # The lead is logged above either way, so it's never lost.
    background.add_task(
        mailer.send_lead,
        company_name, lead_email(payload.company), payload.phone, payload.question,
    )
    return {"ok": True}
