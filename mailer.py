"""
mailer.py — emails a captured lead to the business owner.

Uses Python's built-in smtplib (no extra libraries). You turn on real emails by
setting these environment variables on the server (e.g. on Render):

  SMTP_HOST   the mail server, e.g.  smtp.gmail.com
  SMTP_PORT   the port, usually       587
  SMTP_USER   the sending email address (also shown as the "from")
  SMTP_PASS   that account's APP PASSWORD  (NOT your normal login password)

Gmail tip: turn on 2-step verification, then create an "App password" at
https://myaccount.google.com/apppasswords and use that 16-character code as
SMTP_PASS.

If those aren't set (e.g. on your laptop before you've configured email), this
does NOT crash — it just prints the lead to the console so you can still see it
and test the whole flow. Set the env vars on Render to switch real emails on.
"""

import os
import smtplib
import ssl
from email.message import EmailMessage


def _config():
    """Read the SMTP settings from the environment (all may be None)."""
    return (
        os.environ.get("SMTP_HOST"),
        int(os.environ.get("SMTP_PORT", "587")),
        os.environ.get("SMTP_USER"),
        os.environ.get("SMTP_PASS"),
    )


def send_lead(company_name, to_email, phone, question):
    """Email one lead to the owner. Returns True only if it was really sent."""
    host, port, user, password = _config()

    subject = f"New lead from your {company_name} chatbot"
    body = (
        f"Someone left their details on your {company_name} chatbot:\n\n"
        f"  Phone:    {phone}\n"
        f"  Question: {question or '(none given)'}\n\n"
        f"Reach out to them soon.\n"
    )

    # Not configured yet? Don't crash — just log it so the flow still works.
    if not (host and user and password and to_email):
        print("[lead — email NOT sent, SMTP/recipient not configured]")
        print(f"  would send to: {to_email!r}  phone: {phone!r}  q: {question!r}")
        return False

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = user
    msg["To"] = to_email
    msg.set_content(body)

    context = ssl.create_default_context()
    try:
        with smtplib.SMTP(host, port, timeout=20) as smtp:
            smtp.starttls(context=context)
            smtp.login(user, password)
            smtp.send_message(msg)
    except Exception as e:
        # Wrong app password, typo'd host, blocked port... log the lead and the
        # reason loudly (this shows up in Render's Logs tab), but never crash
        # the /lead endpoint — the visitor should still get a "thanks".
        print(f"[lead — email FAILED to {to_email}: {e}]")
        print(f"  phone: {phone!r}  q: {question!r}")
        return False
    print(f"[lead emailed to {to_email}]")
    return True
