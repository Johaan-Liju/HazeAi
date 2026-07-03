"""
clean.py — turn a raw website crawl into a lean chatbot knowledge base.

A fresh crawl (crawl.py) grabs EVERYTHING: menus, buttons, repeated banners,
hundreds of product lines. That's huge and expensive to feed the model on every
single chat. This tool makes ONE Claude call that squeezes the crawl down to the
durable facts a support bot actually needs — the same lean shape as
knowledge/coverfirst.txt.

Run it once when onboarding a company:
    python clean.py knowledge/ifihomes.txt

It overwrites the file in place with the cleaned version, and prints the
before/after size plus what the one-time cleanup cost.
"""

import sys

import anthropic

import brain  # reuse the SAME model + cost readout as the live bot

CLEAN_MAX_TOKENS = 1500  # the lean output — ~1000 words is plenty

INSTRUCTIONS = """You are building a concise knowledge base for a customer-support
chatbot, from the raw text of a company's website (crawled, so it's full of junk).

Keep ONLY durable facts a customer might ask support about:
- what the business is and what it sells or does
- product or service CATEGORIES (not every individual item)
- policies: shipping, returns, warranty, payment, cancellation
- opening hours, locations / addresses
- contact details (phone, WhatsApp, email, key links)
- any clearly-stated key facts (guarantees, certifications, offers)

REMOVE: navigation menus, buttons ("Add to cart", "Search"), cookie/consent
notices, repeated promo banners, login/account text, and duplicate lines.
Do NOT list individual products with prices — they change constantly and bloat
the file; summarise the categories instead.
Do NOT invent anything that is not in the text.

Format as plain text, organised into sections with UPPERCASE headers (e.g. ABOUT,
PRODUCTS, SHIPPING & RETURNS, PAYMENT, CONTACT, HOURS). Keep it under ~700 words.
Output ONLY the knowledge base text — no preamble, no explanation."""


def main():
    if len(sys.argv) < 2:
        print("Usage: python clean.py <path-to-knowledge-file>")
        return

    path = sys.argv[1]
    raw = brain.load_knowledge(path)
    print(f"Raw file: {len(raw):,} characters. Cleaning with {brain.MODEL}…")

    client = anthropic.Anthropic()
    response = client.messages.create(
        model=brain.MODEL,
        max_tokens=CLEAN_MAX_TOKENS,
        system=INSTRUCTIONS,
        messages=[{"role": "user", "content": raw}],
    )
    cleaned = "".join(b.text for b in response.content if b.type == "text").strip()

    if not cleaned:
        print("Got an empty result — leaving the file untouched.")
        return

    with open(path, "w", encoding="utf-8") as f:
        f.write(cleaned + "\n")

    cost = brain.cost_usd(response.usage)
    print(f"Done. {len(raw):,} → {len(cleaned):,} characters.")
    print(f"One-time cleanup cost: ~${cost:.4f}")


if __name__ == "__main__":
    main()
