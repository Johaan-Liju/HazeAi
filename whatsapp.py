"""
whatsapp.py — lets the SAME chatbot brain answer on WhatsApp, not just on the
website widget.

The whole idea in one line: when a customer messages your WhatsApp Business
number, Meta forwards that message to our server; we run it through the exact
same brain (grounded Q&A + calendar booking) the website already uses, and send
the reply back through Meta. No new AI, no second bot — WhatsApp is just another
doorway into the brain you already built.

WHY DIRECT (no BSP like AiSensy/Interakt): a customer-initiated chat that we
answer within 24 hours is a "service conversation", which Meta bills at ₹0. Our
whole model is "customer messages, bot answers", so the core use case is
effectively free — and a monthly BSP platform fee per client would only eat
into that.

WHAT YOU NEED (environment variables — set them on Render, same place as
ANTHROPIC_API_KEY and GOOGLE_SERVICE_ACCOUNT_JSON):
  WHATSAPP_VERIFY_TOKEN  any secret string YOU invent; you paste the same
                         string into Meta's webhook setup so the two sides can
                         prove they belong together. Used once, at setup.
  WHATSAPP_TOKEN         the access token from your Meta app — the password
                         that lets us send messages as your number.
  WHATSAPP_API_VERSION   (optional) the Graph API version your Meta app shows,
                         e.g. "v21.0". Defaults below — set it to match.
  WHATSAPP_APP_SECRET    (optional) turns ON verifying that requests really came
                         from Meta. Leave unset while testing; add it later.
  WHATSAPP_DEFAULT_COMPANY  (optional) which demo a message answers as while
                         you're testing on Meta's single free test number.

WHICH COMPANY IS THIS? On the website, the widget tells us the company id. On
WhatsApp there's no widget — instead each business has its OWN number, and Meta
tells us which number received the message (its "phone_number_id"). So we map
phone_number_id -> company id in companies.WHATSAPP_NUMBERS. While you test with
Meta's one free number, whatsapp_company() falls back to WHATSAPP_DEFAULT_COMPANY.
"""

import hashlib
import hmac
import os
from collections import deque

import requests

import brain
from companies import (
    COMPANIES,
    calendar_config,
    knowledge_path,
    lead_email,
    whatsapp_company,
)

# --- Config, read once from the environment ---------------------------------
GRAPH = "https://graph.facebook.com"
API_VERSION = os.environ.get("WHATSAPP_API_VERSION", "v21.0")
VERIFY_TOKEN = os.environ.get("WHATSAPP_VERIFY_TOKEN", "")
ACCESS_TOKEN = os.environ.get("WHATSAPP_TOKEN", "")
APP_SECRET = os.environ.get("WHATSAPP_APP_SECRET", "")

# --- Per-sender conversation memory -----------------------------------------
# WhatsApp delivers ONE message per webhook, with no history attached — so we
# remember the thread ourselves, keyed by (company_id, sender phone). For
# booking-enabled companies we store the FULL working-messages history (the raw
# tool_use/tool_result blocks), exactly like server._SESSIONS does, because the
# booking flow needs the precise slot times the calendar returned last turn.
_HISTORY: dict[tuple[str, str], list[dict]] = {}
MAX_TURNS = 20                                  # cap token cost on long chats
MAX_THREADS = 1000                              # cap memory if senders pile up

# Meta retries a webhook if we're slow to answer, so the same message can arrive
# twice. Remember recent message ids and skip repeats, or the customer gets
# every reply doubled.
_SEEN_MESSAGE_IDS: deque[str] = deque(maxlen=2000)

# Knowledge files, loaded on first use and cached (same as server.py loads them
# once at startup — a second small copy in memory here is negligible).
_KNOWLEDGE: dict[str, str] = {}


def _knowledge(company_id):
    if company_id not in _KNOWLEDGE:
        _KNOWLEDGE[company_id] = brain.load_knowledge(knowledge_path(company_id))
    return _KNOWLEDGE[company_id]


# --- Webhook verification (GET) ---------------------------------------------
def verify_webhook(mode, token, challenge):
    """
    Meta calls GET /whatsapp/webhook once, when you first save the webhook, to
    prove you own the server. Echo the challenge back ONLY if the verify token
    it sends matches ours. Returns the challenge string on success, or None.
    """
    if mode == "subscribe" and token and token == VERIFY_TOKEN:
        return challenge
    return None


def valid_signature(raw_body, header):
    """
    True if this POST really came from Meta. Skipped (returns True) until you set
    WHATSAPP_APP_SECRET — so testing works out of the box, and you can switch on
    verification later just by adding that one environment variable.
    """
    if not APP_SECRET:
        return True
    expected = "sha256=" + hmac.new(
        APP_SECRET.encode(), raw_body, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, header or "")


# --- Sending a reply back through Meta --------------------------------------
def send_text(phone_number_id, to, body):
    """Send one plain-text WhatsApp message from `phone_number_id` to `to`."""
    if not ACCESS_TOKEN:
        print("[whatsapp] WHATSAPP_TOKEN not set — cannot send. Reply was:", body)
        return
    url = f"{GRAPH}/{API_VERSION}/{phone_number_id}/messages"
    resp = requests.post(
        url,
        headers={"Authorization": f"Bearer {ACCESS_TOKEN}"},
        json={
            "messaging_product": "whatsapp",
            "to": to,
            "type": "text",
            "text": {"body": body},
        },
        timeout=20,
    )
    if resp.status_code >= 400:
        print(f"[whatsapp] send failed {resp.status_code}: {resp.text[:300]}")


# --- Turning one incoming message into a reply ------------------------------
def _reply_for(company_id, sender, text):
    """Run the brain for one WhatsApp message, remembering the thread."""
    company_name = COMPANIES[company_id]
    knowledge = _knowledge(company_id)
    booking = calendar_config(company_id)
    key = (company_id, sender)
    history = _HISTORY.get(key, [])
    messages = history + [{"role": "user", "content": text}]

    if booking:
        # Same path as the website's booking chat: the model may call
        # check_availability / book_appointment, and answer_with_tools hands
        # back the full working history (tool blocks and all) to store.
        reply, usage, working = brain.answer_with_tools(
            company_name, knowledge, messages, booking, lead_email(company_id)
        )
        _HISTORY[key] = working[-MAX_TURNS:]
    else:
        reply, usage = brain.answer(company_name, knowledge, messages)
        _HISTORY[key] = (
            messages + [{"role": "assistant", "content": reply}]
        )[-MAX_TURNS:]

    if len(_HISTORY) > MAX_THREADS:
        _HISTORY.pop(next(iter(_HISTORY)))       # drop the oldest thread
    return reply, usage


def _handle_one(phone_number_id, company_id, msg):
    """Answer a single message object from the webhook payload."""
    message_id = msg.get("id", "")
    if message_id in _SEEN_MESSAGE_IDS:
        return                                   # a duplicate retry — skip
    _SEEN_MESSAGE_IDS.append(message_id)

    sender = msg.get("from", "")
    if not company_id or company_id not in COMPANIES:
        print(
            f"[whatsapp] no company mapped for phone_number_id={phone_number_id!r} — "
            "add it to companies.WHATSAPP_NUMBERS or set WHATSAPP_DEFAULT_COMPANY"
        )
        return

    if msg.get("type") != "text":
        # Images, audio, stickers, etc. — we only read text for now.
        send_text(
            phone_number_id, sender,
            "I can only read text messages right now — please type your "
            "question and I'll help.",
        )
        return

    text = msg.get("text", {}).get("body", "").strip()
    if not text:
        return

    print(f"[whatsapp {company_id}] from {sender}: {text!r}")
    reply, usage = _reply_for(company_id, sender, text)
    print(
        f"[whatsapp {company_id}] out {usage.output_tokens} tokens "
        f"· ~${brain.cost_usd(usage):.5f}"
    )
    send_text(phone_number_id, sender, reply)


def process(payload):
    """
    Walk a webhook payload and answer every text message in it. Meant to run in
    the BACKGROUND (see server.py) so we can return 200 to Meta immediately —
    Meta retries anything we're slow to acknowledge.

    A payload can also carry delivery/read "statuses" instead of "messages";
    those have no "messages" list, so the inner loop simply does nothing.
    """
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})
            phone_number_id = value.get("metadata", {}).get("phone_number_id", "")
            company_id = whatsapp_company(phone_number_id)
            for msg in value.get("messages", []):
                _handle_one(phone_number_id, company_id, msg)
