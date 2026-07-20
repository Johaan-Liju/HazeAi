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

import json
from html import escape
from typing import Literal

from fastapi import BackgroundTasks, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import (
    FileResponse,
    HTMLResponse,
    PlainTextResponse,
    StreamingResponse,
)
from pydantic import BaseModel, Field

import brain
import guardrails
import mailer
import whatsapp
from companies import COMPANIES, calendar_config, knowledge_path, lead_email

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
    "https://hazeai-website.vercel.app",  # landing site's Vercel address
    "http://127.0.0.1:5500",   # local preview of website/ (python -m http.server 5500)
    "http://localhost:5500",
    "http://127.0.0.1:3000",   # landing-site dev server (npm run dev)
    "http://localhost:3000",
    "https://thirukochi.co.in",
    "https://www.thirukochi.co.in",
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
    # One tab's chat session (see widget.js). Only used for booking-enabled
    # companies, to remember the real tool-call history — see _SESSIONS below.
    session_id: str | None = Field(default=None, max_length=64)


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


# --- Booking session memory --------------------------------------------------
# Plain chat history is just display text (see Message above) — fine for the
# no-tools path, but a booking conversation needs the raw tool_use/tool_result
# blocks too (e.g. the exact ISO time check_availability returned), or the
# model has to guess that value back from memory on the visitor's next
# message and gets it wrong. So for booking-enabled companies we keep the
# real working-messages history here, keyed by the widget's per-tab session
# id, and use THAT instead of re-deriving from display text.
#
# In-memory is enough: this app runs a single worker (WEB_CONCURRENCY=1), and
# losing sessions on a redeploy just falls back to today's behaviour below.
_SESSIONS: dict[str, list[dict]] = {}
MAX_SESSIONS = 500          # cap memory use if visitors pile up
MAX_SESSION_MESSAGES = 20   # cap token cost on a very long-running chat


def _booking_messages(payload: ChatRequest, text_messages: list[dict]):
    """
    The messages to send the model for a booking turn: the stored raw history
    for this session with just the newest turn appended, or — if there's no
    known session yet — the plain-text history like before.
    """
    if payload.session_id and payload.session_id in _SESSIONS:
        newest = payload.messages[-1]
        return _SESSIONS[payload.session_id] + [
            {"role": newest.role, "content": newest.content}
        ]
    return text_messages


def _remember_session(session_id, working_messages):
    if not session_id:
        return
    _SESSIONS[session_id] = working_messages[-MAX_SESSION_MESSAGES:]
    if len(_SESSIONS) > MAX_SESSIONS:
        _SESSIONS.pop(next(iter(_SESSIONS)))  # drop the oldest session


@app.post("/chat", response_model=ChatReply)
def chat(payload: ChatRequest, request: Request):
    """Take the conversation (for a specific company), ask the brain, reply."""
    guardrails.check_rate_limit(request)
    company_name, knowledge, messages = _resolve(payload)
    booking = calendar_config(payload.company)

    if booking:
        reply, usage, working_messages = brain.answer_with_tools(
            company_name, knowledge, _booking_messages(payload, messages), booking,
            lead_email(payload.company),
        )
        _remember_session(payload.session_id, working_messages)
    else:
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
    booking = calendar_config(payload.company)

    if booking:
        # A booking turn calls out to the Calendar API mid-conversation, so
        # there's no partial text from Claude to stream as it's produced —
        # get the finished reply, then hand it to the widget in one piece.
        # The widget reveals text with its own typing effect regardless of
        # how many network chunks it arrives in, so the UX is unchanged.
        def generate():
            reply, usage, working_messages = brain.answer_with_tools(
                company_name, knowledge, _booking_messages(payload, messages), booking,
                lead_email(payload.company),
            )
            _remember_session(payload.session_id, working_messages)
            yield reply
            print(
                f"[/chat/stream {payload.company}] out {usage.output_tokens} tokens "
                f"· ~${brain.cost_usd(usage):.5f}"
            )

        return StreamingResponse(generate(), media_type="text/plain")

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


# --- WhatsApp (Meta Cloud API) ----------------------------------------------
# Two endpoints, both at the same path (Meta requires that):
#   GET  — the one-time handshake Meta does when you save the webhook.
#   POST — every incoming customer message (and delivery/read receipts).
# See whatsapp.py for how a message becomes an answer.
@app.get("/whatsapp/webhook")
def whatsapp_verify(
    hub_mode: str = Query("", alias="hub.mode"),
    hub_verify_token: str = Query("", alias="hub.verify_token"),
    hub_challenge: str = Query("", alias="hub.challenge"),
):
    """Meta's verification handshake — echo the challenge if the token matches."""
    challenge = whatsapp.verify_webhook(hub_mode, hub_verify_token, hub_challenge)
    if challenge is None:
        raise HTTPException(status_code=403, detail="verify token mismatch")
    return PlainTextResponse(challenge)


@app.post("/whatsapp/webhook")
async def whatsapp_incoming(request: Request, background: BackgroundTasks):
    """
    An incoming WhatsApp event. We answer in the BACKGROUND and return 200
    immediately — Meta retries anything we're slow to acknowledge, which would
    otherwise double-send replies.
    """
    raw = await request.body()
    if not whatsapp.valid_signature(raw, request.headers.get("X-Hub-Signature-256")):
        raise HTTPException(status_code=403, detail="bad signature")
    payload = json.loads(raw)
    background.add_task(whatsapp.process, payload)
    return {"ok": True}
