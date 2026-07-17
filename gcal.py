"""
gcal.py — lets the chatbot read a client's real Google Calendar availability
and hold a slot on it, so two visitors can never end up booked into the same
time.

Only companies listed in companies.CALENDARS get this. A client turns it on
by sharing their calendar with the bot's service-account email (found inside
the key file below) with "Make changes to events" permission.

Credentials, same pattern as mailer.py's email settings:
  Locally:   a downloaded service-account JSON key file sits next to this
             file (gitignored — see .gitignore).
  On Render: put the ENTIRE contents of that JSON file into one environment
             variable, GOOGLE_SERVICE_ACCOUNT_JSON (Render has no persistent
             disk to keep a key file on, the same reason mailer.py uses env
             vars instead of a config file).

NOTE: this file is deliberately NOT named calendar.py — that would shadow
Python's own built-in `calendar` module (which email.utils, used by
mailer.py, imports internally) for the whole process.
"""

import datetime
import os
from zoneinfo import ZoneInfo

from google.oauth2 import service_account
from googleapiclient.discovery import build

SCOPES = ["https://www.googleapis.com/auth/calendar"]
LOCAL_KEY_FILE = "haze-ai-calender-d6e70ba060b8.json"  # gitignored — local dev only

_service = None  # the API client, built once and reused for every call


class SlotTaken(Exception):
    """The chosen slot got booked by someone else between offering it and now."""


def _client():
    global _service
    if _service is None:
        env_json = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")
        if env_json:
            import json
            creds = service_account.Credentials.from_service_account_info(
                json.loads(env_json), scopes=SCOPES
            )
        else:
            creds = service_account.Credentials.from_service_account_file(
                LOCAL_KEY_FILE, scopes=SCOPES
            )
        _service = build("calendar", "v3", credentials=creds)
    return _service


def _busy_periods(calendar_id, time_min, time_max):
    """Which chunks of [time_min, time_max) are already busy on this calendar."""
    result = (
        _client()
        .freebusy()
        .query(
            body={
                "timeMin": time_min.isoformat(),
                "timeMax": time_max.isoformat(),
                "items": [{"id": calendar_id}],
            }
        )
        .execute()
    )
    busy = result["calendars"][calendar_id].get("busy", [])
    return [
        (
            datetime.datetime.fromisoformat(b["start"]),
            datetime.datetime.fromisoformat(b["end"]),
        )
        for b in busy
    ]


def _overlaps(start, end, busy_periods):
    return any(start < b_end and end > b_start for b_start, b_end in busy_periods)


def format_slot(start):
    """Human-friendly label for a slot's start time, e.g. 'Thu, Jul 23 at 11:30 AM'."""
    day_name = start.strftime("%a")
    month = start.strftime("%b")
    time_str = start.strftime("%I:%M %p").lstrip("0")  # "09:30 AM" -> "9:30 AM"
    return f"{day_name}, {month} {start.day} at {time_str}"


def find_slots(config, count=3, days_ahead=10):
    """
    Up to `count` upcoming open slots for this calendar, soonest first, as a
    list of (start, end) timezone-aware datetimes in the client's own timezone.

    `config` is one entry from companies.CALENDARS (calendar_id, timezone,
    work_hours, work_days, slot_minutes — see that file for the shape).
    """
    tz = ZoneInfo(config["timezone"])
    now = datetime.datetime.now(tz)
    start_hour, end_hour = config["work_hours"]
    slot_len = datetime.timedelta(minutes=config["slot_minutes"])

    range_end = now + datetime.timedelta(days=days_ahead)
    busy = _busy_periods(config["calendar_id"], now, range_end)

    slots = []
    for day_offset in range(days_ahead + 1):
        day = (now + datetime.timedelta(days=day_offset)).date()
        if day.weekday() not in config["work_days"]:
            continue
        slot_start = datetime.datetime.combine(day, datetime.time(hour=start_hour), tzinfo=tz)
        day_end = datetime.datetime.combine(day, datetime.time(hour=end_hour), tzinfo=tz)

        while slot_start + slot_len <= day_end:
            slot_finish = slot_start + slot_len
            if slot_start > now and not _overlaps(slot_start, slot_finish, busy):
                slots.append((slot_start, slot_finish))
                if len(slots) >= count:
                    return slots
            slot_start += slot_len
    return slots


def book_slot(config, start, summary, description=""):
    """
    Hold [start, start + slot length) on the calendar with a blocking event.

    Re-checks for a conflict right before writing — this closes the gap
    between a visitor being OFFERED a slot and them CONFIRMING it, so two
    visitors racing for the same opening can't both get booked. Raises
    SlotTaken if someone else got there first.
    """
    end = start + datetime.timedelta(minutes=config["slot_minutes"])

    busy = _busy_periods(config["calendar_id"], start, end)
    if _overlaps(start, end, busy):
        raise SlotTaken()

    event = (
        _client()
        .events()
        .insert(
            calendarId=config["calendar_id"],
            body={
                "summary": summary,
                "description": description,
                "start": {"dateTime": start.isoformat()},
                "end": {"dateTime": end.isoformat()},
            },
        )
        .execute()
    )
    return event["id"]
