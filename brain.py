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
MAX_TOKENS = 300             # cap answer length to keep replies short & cheap

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
- Keep answers as SHORT as possible — ideally one sentence, at most two.
- Answer only what was asked. Do not add extra details, lists, background, or
  suggestions the visitor didn't ask for.
- If the answer is not in the information, say you don't have that detail and
  give the contact info (phone/WhatsApp/email) so a human can help.
- Never invent prices, policies, hours, or product details.
- No greetings, no sign-offs, no "the provided information" — just the answer.

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
