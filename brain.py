"""
The "brain" of the chatbot — the one reusable piece that turns a conversation
into an answer, grounded in a company's knowledge.

Everything that talks to Claude lives HERE, in one place. Both:
  - chatbot.py           (the terminal tester you already use), and
  - the web server        (coming next, Phase 2 Step 2)
import from this file. So there's a single source of truth for the model, the
cost settings, and the grounding rules — change them once, everything updates.
"""

import datetime
import json

import anthropic

import gcal
import mailer

# --- Shared settings ---------------------------------------------------------
MODEL = "claude-haiku-4-5"   # cheapest capable Claude model
MAX_TOKENS = 320             # hard stop above the one-paragraph rule below. Greek
                             # and other non-Latin scripts tokenize less
                             # efficiently than English, so 200 truncated otherwise
                             # complete answers mid-word. Raising the cap adds no
                             # cost to answers that already finished early — it only
                             # lets the longer ones complete.

# One Anthropic client, reused for every call. Reads ANTHROPIC_API_KEY from the
# environment (the key setup you did earlier). The leading underscore is a
# Python convention meaning "internal to this file."
_client = anthropic.Anthropic()


def load_knowledge(path):
    """Read a company's information from a text file and return it as a string."""
    with open(path, "r", encoding="utf-8") as f:
        return f.read().strip()


BOOKING_INSTRUCTIONS = """

You can also check appointment availability and book a slot, using the
check_availability and book_appointment tools. Rules:
- If a visitor wants to book, schedule, or asks about coming in for a meeting
  or appointment, call check_availability — never guess or invent times.
- Offer at most 3 of the returned slots, in one flowing plain-text sentence
  (e.g. "I have Thu, Jul 23 at 11:30 AM, Fri, Jul 24 at 2:00 PM, or Mon, Jul
  27 at 10:00 AM - which works?").
- Once they pick one of those EXACT slots, ask for their name and phone
  number if you don't have them yet.
- Only call book_appointment once you have all three: the exact slot they
  picked, their name, and their phone number. Copy the slot's start value
  exactly as given — never write your own date or time.
- If book_appointment returns ok: false, do not invent your own explanation —
  go by its "reason" field. If the reason is that the time wasn't recognised,
  call check_availability again and have them repick, rather than assuming
  the slot was taken.
- After a successful booking, confirm the day and time back to them in one
  short sentence. Never claim a booking succeeded unless the tool said so."""


def build_system_prompt(company_name, knowledge, booking_enabled=False):
    """The instructions that turn Claude into a grounded, on-topic support bot."""
    return f"""You are the customer support assistant for {company_name}.

Answer visitor questions using ONLY the company information provided below.
Rules:
- Reply in ONE short paragraph of 1 to 3 plain sentences — NEVER more, and never
  use line breaks. If the full answer would be long, give the most useful part
  in one paragraph and let them ask for more.
- Do NOT tack on "feel free to contact us", "reach out to us", or push the
  phone/email when you've already answered the question. Just give the answer.
- ONLY when the answer is not in the information: say you don't have that detail,
  and then invite them to contact us (phone/WhatsApp/email) so a human can help.
- Never invent prices, policies, hours, or product details.
- No greetings, no sign-offs, no "the provided information" — just the answer.
- Write in PLAIN TEXT only — your reply appears in a simple chat bubble that
  does not render formatting. No markdown: no asterisks, no **bold**, no
  bullet-point lists, no headers, no backticks. If you need to list things,
  write them as short plain lines or a flowing sentence.
{BOOKING_INSTRUCTIONS if booking_enabled else ""}

===== COMPANY INFORMATION =====
{knowledge}
===== END COMPANY INFORMATION ====="""


def answer(company_name, knowledge, messages):
    """
    The reusable brain. Given who the bot is, what it knows, and the
    conversation so far, return (reply_text, usage).

    Arguments:
      company_name: e.g. "CoverFirst"
      knowledge:    the company's info as a string (from load_knowledge)
      messages:     the conversation so far, a list like:
                      [{"role": "user", "content": "are you open sunday?"},
                       {"role": "assistant", "content": "No, we're closed Sundays."},
                       {"role": "user", "content": "what about saturday?"}]

    Returns:
      reply_text: what the bot says (a string)
      usage:      token counts for this call (used for the cost readout)
    """
    response = _client.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        system=[
            {
                "type": "text",
                "text": build_system_prompt(company_name, knowledge),
                "cache_control": {"type": "ephemeral"},
            }
        ],
        messages=messages,
    )
    # Claude returns a list of content blocks; join the text ones into a string.
    reply_text = "".join(
        block.text for block in response.content if block.type == "text"
    )
    return reply_text, response.usage


def stream_answer(company_name, knowledge, messages):
    """
    Like answer(), but STREAMS the reply so it can be shown piece by piece.

    Use it with a `with` block:

        with brain.stream_answer(name, knowledge, msgs) as stream:
            for piece in stream.text_stream:      # each piece is a bit of text
                ...                               # send it to the browser
            usage = stream.get_final_message().usage   # for the cost readout

    All the model and grounding settings live here, exactly like answer() — the
    only difference is the reply arrives in pieces instead of all at once.
    """
    return _client.messages.stream(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        system=[
            {
                "type": "text",
                "text": build_system_prompt(company_name, knowledge),
                "cache_control": {"type": "ephemeral"},
            }
        ],
        messages=messages,
    )


def cost_usd(usage):
    """Rough US-dollar cost of one Claude call, from its token usage (Haiku rates)."""
    return (
        usage.input_tokens                                  # uncached input ($1 / 1M)
        + (usage.cache_creation_input_tokens or 0) * 1.25   # cache writes  ($1.25 / 1M)
        + (usage.cache_read_input_tokens or 0) * 0.10       # cache reads   ($0.10 / 1M)
        + usage.output_tokens * 5                           # output        ($5 / 1M)
    ) / 1_000_000


# --- Calendar booking (only used for companies with a calendar_config) ------
_BOOKING_TOOLS = [
    {
        "name": "check_availability",
        "description": (
            "Look up the next open appointment slots on the calendar. Call "
            "this whenever a visitor wants to book, schedule, or asks about "
            "coming in for a meeting or appointment — never guess times."
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "book_appointment",
        "description": (
            "Reserve one of the exact slots returned by check_availability. "
            "Only call this once the visitor has picked one of those exact "
            "times AND given their name and phone number."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "start": {
                    "type": "string",
                    "description": (
                        "The chosen slot's 'start' value, copied exactly as "
                        "given by check_availability — never write your own."
                    ),
                },
                "name": {"type": "string", "description": "The visitor's name."},
                "phone": {"type": "string", "description": "The visitor's phone number."},
            },
            "required": ["start", "name", "phone"],
        },
    },
]

MAX_TOOL_ROUNDS = 4  # safety cap so a confused model can't loop forever


class _Usage:
    """Accumulates token usage across several Claude calls (one tool round each)."""

    def __init__(self):
        self.input_tokens = 0
        self.output_tokens = 0
        self.cache_creation_input_tokens = 0
        self.cache_read_input_tokens = 0

    def add(self, usage):
        self.input_tokens += usage.input_tokens
        self.output_tokens += usage.output_tokens
        self.cache_creation_input_tokens += usage.cache_creation_input_tokens or 0
        self.cache_read_input_tokens += usage.cache_read_input_tokens or 0


def _run_tool(tool_name, tool_input, calendar_config, company_name, lead_to_email):
    """Execute one booking tool call and return a JSON-serialisable result."""
    print(f"[tool] {tool_name} input={tool_input}")

    if tool_name == "check_availability":
        slots = gcal.find_slots(calendar_config)
        result = {
            "slots": [
                {"start": start.isoformat(), "label": gcal.format_slot(start)}
                for start, _end in slots
            ]
        }
        print(f"[tool] check_availability -> {result}")
        return result

    if tool_name == "book_appointment":
        name = tool_input.get("name", "").strip()
        phone = tool_input.get("phone", "").strip()
        try:
            start = datetime.datetime.fromisoformat(tool_input.get("start", ""))
        except ValueError:
            print(f"[tool] book_appointment -> bad start value {tool_input.get('start')!r}")
            return {"ok": False, "reason": "that time wasn't recognised — check availability again"}

        try:
            event_id = gcal.book_slot(
                calendar_config,
                start,
                summary=f"{name} — booked via {company_name} chatbot",
                description=f"Phone: {phone}",
            )
        except gcal.SlotTaken:
            print(f"[tool] book_appointment -> SlotTaken for {start.isoformat()}")
            return {"ok": False, "reason": "that slot was just taken by someone else"}

        label = gcal.format_slot(start)
        print(f"[tool] book_appointment -> ok, event_id={event_id}, {label}")
        mailer.send_lead(company_name, lead_to_email, phone, f"Booked appointment for {label} (name: {name})")
        return {"ok": True, "confirmed": label}

    return {"error": f"unknown tool {tool_name}"}


def answer_with_tools(company_name, knowledge, messages, calendar_config, lead_to_email):
    """
    Like answer(), but for companies with calendar booking turned on: the
    model can call check_availability and book_appointment along the way.
    Runs as many rounds as it takes (capped at MAX_TOOL_ROUNDS) and returns
    (reply_text, usage, working_messages) — usage summed across every round.

    working_messages is the FULL conversation including the raw tool_use /
    tool_result blocks (not just display text). The caller should persist it
    and pass it back in as `messages` on the visitor's next turn — otherwise
    the exact slot time returned by check_availability is lost the moment
    this call returns, and the model has to guess it back from memory on the
    next turn (it can't; that guess is what caused bad bookings).
    """
    working_messages = [dict(m) for m in messages]
    total_usage = _Usage()
    system = [
        {
            "type": "text",
            "text": build_system_prompt(company_name, knowledge, booking_enabled=True),
            "cache_control": {"type": "ephemeral"},
        }
    ]

    for _ in range(MAX_TOOL_ROUNDS):
        response = _client.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            system=system,
            messages=working_messages,
            tools=_BOOKING_TOOLS,
        )
        total_usage.add(response.usage)

        if response.stop_reason != "tool_use":
            reply_text = "".join(b.text for b in response.content if b.type == "text")
            working_messages.append({"role": "assistant", "content": response.content})
            return reply_text, total_usage, working_messages

        working_messages.append({"role": "assistant", "content": response.content})
        tool_results = [
            {
                "type": "tool_result",
                "tool_use_id": block.id,
                "content": json.dumps(
                    _run_tool(block.name, block.input, calendar_config, company_name, lead_to_email)
                ),
            }
            for block in response.content
            if block.type == "tool_use"
        ]
        working_messages.append({"role": "user", "content": tool_results})

    return (
        "Sorry — I'm having trouble checking the calendar right now. Please try again shortly.",
        total_usage,
        working_messages,
    )
