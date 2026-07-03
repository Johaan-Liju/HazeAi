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

# id  ->  display name (what the bot calls itself)
COMPANIES = {
    "coverfirst": "CoverFirst",
    "ifihomes": "IFI homes",     
}


def knowledge_path(company_id):
    """Where a company's knowledge file lives, worked out from its id."""
    return f"knowledge/{company_id}.txt"
