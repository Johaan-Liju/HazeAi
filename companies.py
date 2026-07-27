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
    "thirukochi": "Thirukochi Financial Services",
    "hazeai": "Haze AI",
    "affluenz": "Affluenz wealth",  # our own site — the widget on hazeai.in demos itself
    "diazinvest":"Diaz Invest",
    # Reusable sales demos (fictional businesses) — send these links to any
    # prospect in that industry so they can experience the bot before you build
    # them their own. Booking is turned on for both (see CALENDARS below).
    "clinicdemo": "Brightview Dental Studio",
    "financedemo": "Meridian Wealth",
    # Real-clinic outreach demo (Athens, Greece) — built from the clinic's public
    # info so we can send them their own working bot. Answers in Greek.
    "athensdental": "The Dental Clinic",
}

# id  ->  the business owner's email, where THAT company's leads get sent.
# Leave blank ("") and it falls back to the LEAD_TO env var — handy while you're
# testing with just your own inbox. Fill one in per customer as you onboard them.
LEAD_EMAILS = {
    "coverfirst": "johaanliju@gmail.com",
    "thirukochi": "jhoncyjacob@gmail.com",
    "hazeai": "johaanliju@gmail.com",
    "affluenz": "support@affluenzwealth.com",  # leads from our own site,  # falls back to LEAD_TO until they sign up
    "diazinvest": "johaanliju@gmail.com",    # falls back to LEAD_TO until they sign up
    "clinicdemo": "johaanliju@gmail.com",    # demo leads come to you
    "financedemo": "johaanliju@gmail.com",   # demo leads come to you
    "athensdental": "johaanliju@gmail.com",  # demo leads come to you
}


def knowledge_path(company_id):
    """Where a company's knowledge file lives, worked out from its id."""
    return f"knowledge/{company_id}.txt"


def lead_email(company_id):
    """Which inbox this company's leads go to (its own, or the LEAD_TO fallback)."""
    return LEAD_EMAILS.get(company_id) or os.environ.get("LEAD_TO", "")


# id -> booking configuration. A company's PRESENCE in this dict is what turns
# on calendar booking for their bot — leave a company out and their bot works
# exactly as before, no calendar involved.
#
#   calendar_id:   the Google Calendar to read/write — an email address, or a
#                  calendar ID from that calendar's Settings page. The client
#                  must first share this calendar with the bot's service
#                  account (its email is inside the key file gcal.py reads),
#                  with "Make changes to events" permission.
#   timezone:      an IANA name, e.g. "Asia/Kolkata"
#   work_hours:    (start_hour, end_hour) in 24-hour local time, e.g. (10, 18)
#   work_days:     which weekdays are workdays — 0=Monday ... 6=Sunday
#   slot_minutes:  length of one appointment slot
CALENDARS = {
    # Sandbox for testing the booking feature before it's offered to a real
    # client — points at Johaan's own calendar, wired to the "hazeai" demo bot.
    "hazeai": {
        "calendar_id": "johaanliju@gmail.com",
        "timezone": "Asia/Kolkata",
        "work_hours": (10, 18),
        "work_days": [0, 1, 2, 3, 4, 5],
        "slot_minutes": 30,
    },
    # Dental demo: Mon–Sat, 9am–7pm, 30-min slots. Points at the same sandbox
    # calendar so a prospect's test booking really lands in your Google Calendar.
    "clinicdemo": {
        "calendar_id": "johaanliju@gmail.com",
        "timezone": "Asia/Kolkata",
        "work_hours": (9, 19),
        "work_days": [0, 1, 2, 3, 4, 5],
        "slot_minutes": 30,
    },
    # Athens dental outreach demo: Mon–Fri, 9:30am–9pm (rounded to 10–21),
    # 30-min slots, in Athens local time. Points at the same sandbox calendar so
    # a test booking really lands in your Google Calendar.
    "athensdental": {
        "calendar_id": "johaanliju@gmail.com",
        "timezone": "Europe/Athens",
        "work_hours": (10, 21),
        "work_days": [0, 1, 2, 3, 4],
        "slot_minutes": 30,
    },
    # Finance demo: Mon–Fri, 10am–6pm, 30-min "free consultation" slots.
    "financedemo": {
        "calendar_id": "johaanliju@gmail.com",
        "timezone": "Asia/Kolkata",
        "work_hours": (10, 18),
        "work_days": [0, 1, 2, 3, 4],
        "slot_minutes": 30,
    },
}


def calendar_config(company_id):
    """This company's booking config, or None if booking isn't turned on for them."""
    return CALENDARS.get(company_id)


# id -> which WhatsApp number belongs to this company. The KEY is the
# "phone_number_id" Meta shows for that number in your app dashboard — NOT the
# phone number itself. On WhatsApp there's no widget to announce the company, so
# we tell companies apart by which of your numbers a message arrived on. Fill one
# line in per client as you connect their WhatsApp number.
WHATSAPP_NUMBERS = {
    # "123456789012345": "clinicdemo",
}


def whatsapp_company(phone_number_id):
    """
    Which company owns this WhatsApp number — from the mapping above, or the
    WHATSAPP_DEFAULT_COMPANY environment variable as a fallback (handy while
    you're testing with Meta's single free test number, so one number can stand
    in for any demo without editing code).
    """
    return WHATSAPP_NUMBERS.get(phone_number_id) or os.environ.get(
        "WHATSAPP_DEFAULT_COMPANY", ""
    )
