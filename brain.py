"""
The "brain" of the chatbot — the one reusable piece that turns a conversation
into an answer, grounded in a company's knowledge.

Everything that talks to Claude lives HERE, in one place. Both:
  - chatbot.py           (the terminal tester you already use), and
  - the web server        (coming next, Phase 2 Step 2)
import from this file. So there's a single source of truth for the model, the
cost settings, and the grounding rules — change them once, everything updates.
"""

import anthropic

# --- Shared settings ---------------------------------------------------------
MODEL = "claude-haiku-4-5"   # cheapest capable Claude model
MAX_TOKENS = 200             # hard stop well above the one-paragraph rule below

# One Anthropic client, reused for every call. Reads ANTHROPIC_API_KEY from the
# environment (the key setup you did earlier). The leading underscore is a
# Python convention meaning "internal to this file."
_client = anthropic.Anthropic()


def load_knowledge(path):
    """Read a company's information from a text file and return it as a string."""
    with open(path, "r", encoding="utf-8") as f:
        return f.read().strip()


def build_system_prompt(company_name, knowledge):
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
