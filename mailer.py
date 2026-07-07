"""
mailer.py — emails a captured lead to the business owner.

Two ways to send, picked automatically (no extra libraries for either):

1. RECOMMENDED — Brevo's HTTPS API. Render's FREE tier blocks the normal email
   ports (25/465/587) entirely — that's the "[Errno 101] Network is unreachable"
   error — so on Render the mail has to travel over HTTPS like any web request.
   Brevo's free plan sends 300 emails/day, no card needed. Set these two
   environment variables on Render:

     BREVO_API_KEY  an API key from brevo.com (Settings → SMTP & API → API keys)
     MAIL_FROM      the "from" address — must be added & confirmed as a
                    sender in Brevo first (Senders → Add a sender)

2. Plain SMTP (smtplib) — only works where SMTP ports aren't blocked, e.g. on
   your own laptop or a paid Render instance:

     SMTP_HOST   the mail server, e.g.  smtp.gmail.com
     SMTP_PORT   587 (STARTTLS, the default) or 465 (SSL)
     SMTP_USER   the sending email address (also shown as the "from")
     SMTP_PASS   that account's APP PASSWORD  (NOT your normal login password)

If neither is configured, this does NOT crash — it just prints the lead to the
console so you can still see it and test the whole flow.
"""

import json
import os
import smtplib
import ssl
import urllib.error
import urllib.request


def send_lead(company_name, to_email, phone, question):
    """Email one lead to the owner. Returns True only if it was really sent."""
    subject = f"New lead from your {company_name} chatbot"
    body = (
        f"Someone left their details on your {company_name} chatbot:\n\n"
        f"  Phone:    {phone}\n"
        f"  Question: {question or '(none given)'}\n\n"
        f"Reach out to them soon.\n"
    )

    api_key = os.environ.get("BREVO_API_KEY")
    mail_from = os.environ.get("MAIL_FROM")
    smtp_host = os.environ.get("SMTP_HOST")
    smtp_user = os.environ.get("SMTP_USER")
    smtp_pass = os.environ.get("SMTP_PASS")

    brevo_ready = bool(api_key and mail_from)
    smtp_ready = bool(smtp_host and smtp_user and smtp_pass)

    # Not configured yet? Don't crash — just log it so the flow still works.
    if not (to_email and (brevo_ready or smtp_ready)):
        print("[lead — email NOT sent, no email service configured]")
        print(f"  would send to: {to_email!r}  phone: {phone!r}  q: {question!r}")
        return False

    try:
        if brevo_ready:
            _send_via_brevo(api_key, mail_from, company_name, to_email, subject, body)
        else:
            _send_via_smtp(smtp_host, smtp_user, smtp_pass, to_email, subject, body)
    except urllib.error.HTTPError as e:
        # Brevo rejected the request. Its response body says exactly why
        # (bad key, sender not verified, ...) — put that in the log.
        try:
            detail = e.read().decode("utf-8", "replace")
        except Exception:
            detail = "(no detail)"
        print(f"[lead — email FAILED to {to_email}: Brevo HTTP {e.code}: {detail}]")
        print(f"  phone: {phone!r}  q: {question!r}")
        return False
    except Exception as e:
        # Wrong app password, blocked port, typo'd host... log the lead and the
        # reason loudly (this shows up in Render's Logs tab), but never crash
        # the /lead endpoint — the visitor should still get a "thanks".
        print(f"[lead — email FAILED to {to_email}: {e}]")
        print(f"  phone: {phone!r}  q: {question!r}")
        return False

    print(f"[lead emailed to {to_email}]")
    return True


def _send_via_brevo(api_key, mail_from, company_name, to_email, subject, body):
    """Send through Brevo's HTTPS API — port 443, which no host blocks."""
    payload = {
        "sender": {"name": f"{company_name} chatbot", "email": mail_from},
        "to": [{"email": to_email}],
        "subject": subject,
        "textContent": body,
    }
    req = urllib.request.Request(
        "https://api.brevo.com/v3/smtp/email",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "api-key": api_key,
            "content-type": "application/json",
            "accept": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=15) as res:
        res.read()  # success is any 2xx; errors raise HTTPError above


def _send_via_smtp(host, user, password, to_email, subject, body):
    """Send through a classic mail server (only where SMTP ports are open)."""
    from email.message import EmailMessage

    port = int(os.environ.get("SMTP_PORT", "587"))
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = user
    msg["To"] = to_email
    msg.set_content(body)

    context = ssl.create_default_context()
    # Port 465 wants encryption from the very first byte (SMTP_SSL); every
    # other port (587) starts plain and upgrades (starttls). Using the wrong
    # one doesn't error — it just hangs — so pick automatically by port.
    if port == 465:
        with smtplib.SMTP_SSL(host, port, context=context, timeout=15) as smtp:
            smtp.login(user, password)
            smtp.send_message(msg)
    else:
        with smtplib.SMTP(host, port, timeout=15) as smtp:
            smtp.starttls(context=context)
            smtp.login(user, password)
            smtp.send_message(msg)
