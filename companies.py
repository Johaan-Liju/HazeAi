"""
The list of companies this one server can answer for.

This is your customer list. One server, many companies — that's the whole idea
of Step 3. To onboard a new company you do just two things:
  1. Drop a knowledge file at  knowledge/<id>.txt
  2. Add one line to COMPANIES below

The "id" is a short, lowercase, no-spaces nickname (a "slug"). It's used in two
places: as the knowledge filename, and as the value the chat widget sends so the
server knows which company is asking.
"""

import os

# id  ->  display name (what the bot calls itself)
COMPANIES = {
    "coverfirst": "CoverFirst",
    "ifihomes": "IFI homes",
    "thirukochi": "Thirukochi Financial Services",
    "aims": "AIMS Insurance",
    "finsights": "Finsights by Square League",
}

# id  ->  the business owner's email, where THAT company's leads get sent.
# Leave blank ("") and it falls back to the LEAD_TO env var — handy while you're
# testing with just your own inbox. Fill one in per customer as you onboard them.
LEAD_EMAILS = {
    "coverfirst": "johaanliju@gmail.com",
    "ifihomes": "hazeai2026@gmail.com",
    "thirukochi": "jhoncyjacob@gmail.com",
    "aims": "",  # falls back to LEAD_TO until they sign up
    "finsights": "",  # falls back to LEAD_TO until they sign up
}


def knowledge_path(company_id):
    """Where a company's knowledge file lives, worked out from its id."""
    return f"knowledge/{company_id}.txt"


def lead_email(company_id):
    """Which inbox this company's leads go to (its own, or the LEAD_TO fallback)."""
    return LEAD_EMAILS.get(company_id) or os.environ.get("LEAD_TO", "")
