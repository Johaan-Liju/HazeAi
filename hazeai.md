# Haze AI

An AI chat assistant that businesses can put on their website with **one line of code**. It answers customer questions from the business's own information, captures callback leads by email, books appointments on a real Google Calendar, and can answer on WhatsApp too.

One server, many companies: adding a new customer takes a knowledge file and one line of config.

Website: [hazeai.in](https://hazeai.in)

## Features

- **Grounded answers.** The bot answers only from a company's own knowledge file. If it doesn't know something, it says so and offers to take a phone number.
- **Embeddable widget.** A single `<script>` tag adds a chat bubble to any site (WordPress, Wix, Shopify, custom). It uses Shadow DOM so a customer site's CSS can't break it, streams replies as they are written, and remembers the conversation across page reloads.
- **Lead capture.** A visitor leaves a number and question, and it is emailed to the business owner straight away.
- **Appointment booking.** For enabled companies, Claude checks real Google Calendar availability and books a slot, so two visitors can't get the same time.
- **WhatsApp.** The same brain answers customer messages on each business's WhatsApp Business number.
- **Multi-company.** Each company has its own knowledge, lead email, calendar and WhatsApp number.
- **Website-to-knowledge tools.** A crawler reads a company's site and a cleaner condenses it into a lean knowledge file.
- **Cost and abuse controls.** Rate limiting, request size caps, a CORS allowlist, prompt caching and a capped reply length.

## How it works

```
 Visitor's browser                              WhatsApp customer
 (widget.js on the customer's site)                    |
        |                                              |
        |  POST /chat, /chat/stream, /lead             |  Meta webhook
        v                                              v
 +-------------------------- server.py (FastAPI) ---------------------------+
 |  guardrails.py: rate limit, size caps, CORS allowlist                    |
 |        |                                                                 |
 |        v                                                                 |
 |  brain.py: knowledge + conversation -> Claude (claude-haiku-4-5)         |
 |        |                         |                      |                |
 |   grounded answer        gcal.py (availability,    mailer.py (lead      |
 |                           booking)                  emails)             |
 +--------------------------------------------------------------------------+
        ^
   knowledge/<company>.txt   (per-company facts, loaded at startup)
```

`brain.py` is the single place that talks to Claude. The terminal tester, the web server and the WhatsApp handler all use it.

## Tech stack

- **Backend:** Python 3.12, FastAPI, Uvicorn
- **AI:** Anthropic Claude (`claude-haiku-4-5`) with prompt caching and tool use
- **Frontend widget:** plain JavaScript (no framework), Shadow DOM, streaming responses
- **Integrations:** Google Calendar API (service account), WhatsApp Cloud API (Meta), Brevo API or SMTP for email
- **Crawling:** `requests`, `beautifulsoup4`

## Project structure

```
.
├── server.py          # FastAPI app: /chat, /chat/stream, /lead, WhatsApp webhook, demo pages
├── brain.py           # Claude calls, grounding rules, booking tools, cost readout
├── companies.py       # Customer list: names, lead emails, calendars, WhatsApp numbers
├── guardrails.py      # In-memory per-IP rate limiter
├── gcal.py            # Google Calendar availability and booking
├── mailer.py          # Lead emails (Brevo HTTPS API, or SMTP fallback)
├── whatsapp.py        # WhatsApp webhook: verify, signature check, reply
├── crawl.py           # Crawl a website into raw text
├── clean.py           # Condense a crawl into a lean knowledge file (one Claude call)
├── chatbot.py         # Terminal tester for the brain
├── knowledge/         # One knowledge file per company
├── web/
│   ├── widget.js      # The embeddable chat widget
│   ├── demo.html      # Demo page
│   └── privacy.html   # Privacy page
├── requirements.txt
└── Procfile           # web: uvicorn server:app --host 0.0.0.0 --port $PORT
```

## Getting started

**Requirements:** Python 3.12 and an [Anthropic API key](https://console.anthropic.com/).

```bash
# 1. Clone and enter the project
git clone https://github.com/Johaan-Liju/hazeai.git
cd hazeai

# 2. Create a virtual environment (recommended)
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Set your API key
export ANTHROPIC_API_KEY="your-key-here"     # Windows (PowerShell): $env:ANTHROPIC_API_KEY="your-key-here"

# 5. Run the server
uvicorn server:app --reload
```

Then open:

- Demo page: http://127.0.0.1:8000/demo
- Interactive API docs: http://127.0.0.1:8000/docs

To try the bot in your terminal instead:

```bash
python chatbot.py
```

## Configuration

Set these as environment variables (never commit them; `.env` is gitignored).

| Variable | Required | Purpose |
|---|---|---|
| `ANTHROPIC_API_KEY` | Yes | Claude API access |
| `BREVO_API_KEY`, `MAIL_FROM` | For lead emails (recommended) | Send leads over Brevo's HTTPS API. `MAIL_FROM` must be a verified Brevo sender |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASS` | Alternative to Brevo | Plain SMTP, for where SMTP ports aren't blocked |
| `LEAD_TO` | Optional | Fallback inbox when a company has no lead email set |
| `GOOGLE_SERVICE_ACCOUNT_JSON` | For booking | Full contents of the service-account key JSON (locally, a key file next to `gcal.py` also works) |
| `WHATSAPP_VERIFY_TOKEN` | For WhatsApp | A secret string you also enter in Meta's webhook setup |
| `WHATSAPP_TOKEN` | For WhatsApp | Meta access token for sending messages |
| `WHATSAPP_API_VERSION` | Optional | Graph API version, default `v21.0` |
| `WHATSAPP_APP_SECRET` | Optional | Turns on verification that requests really come from Meta |
| `WHATSAPP_DEFAULT_COMPANY` | Optional | Company a message answers as while testing on Meta's single test number |

If no email service is configured, leads are printed to the console instead of crashing the server.

## Embedding the widget

Add one line to any page:

```html
<script src="https://YOUR-SERVER/widget.js" data-company="coverfirst"></script>
```

Optional attributes:

| Attribute | Purpose |
|---|---|
| `data-company` | Which company this chat is for (must match `companies.py`) |
| `data-title` | Heading at the top of the chat panel |
| `data-color` | Accent colour, e.g. `#0e7a4d` |
| `data-suggestions` | Tap-to-ask starter questions separated by `\|` |

The customer's domain must also be listed in `ALLOWED_ORIGINS` in `server.py`, or the browser will block the requests.

## Adding a new company

1. Build a knowledge file, either by hand or from their website:
   ```bash
   python crawl.py https://example.com        # writes knowledge.txt (overwrites it)
   python clean.py knowledge/example.txt      # condenses it in place (one Claude call)
   ```
2. Save it as `knowledge/<id>.txt`.
3. Add one line to `COMPANIES` in `companies.py`, and a lead email in `LEAD_EMAILS`.
4. Add their website to `ALLOWED_ORIGINS` in `server.py`.
5. Optional: add an entry to `CALENDARS` for booking, and share their Google Calendar with the service-account email with "Make changes to events" permission.
6. Optional: map their WhatsApp `phone_number_id` in `WHATSAPP_NUMBERS`.

## API

| Method | Endpoint | Purpose |
|---|---|---|
| `GET` | `/` | Health check, lists the companies served |
| `GET` | `/widget.js` | The embeddable widget |
| `GET` | `/demo` | Demo page |
| `GET` | `/privacy` | Privacy page |
| `POST` | `/chat` | Send messages, get one reply |
| `POST` | `/chat/stream` | Same, streamed as it is written |
| `POST` | `/lead` | Capture a callback number and email it to the owner |
| `GET` | `/whatsapp/webhook` | Meta webhook verification |
| `POST` | `/whatsapp/webhook` | Incoming WhatsApp messages |

Requests are limited to 2,000 characters per message, 20 messages per request, and 20 requests per minute per IP. Only `user` and `assistant` roles are accepted, so a visitor can't inject a `system` message.

## Deployment

The `Procfile` runs the server with Uvicorn on `$PORT`, so it works on hosts such as Render. Set the environment variables above in your host's dashboard. Notes from the code:

- Free tiers that block email ports need the Brevo API, not SMTP.
- Hosts without a persistent disk need `GOOGLE_SERVICE_ACCOUNT_JSON` as an environment variable instead of a key file.
- The rate limiter and WhatsApp threads are in memory, so they reset on restart and aren't shared across several server processes. Swap in Redis if you scale out.

## How WhatsApp works

Meta forwards a customer's message to `/whatsapp/webhook`. The server picks the company from the number that received it, runs the message through the same brain (grounded answers and booking), and replies through Meta's API. A customer-started chat answered within 24 hours is a service conversation, which Meta bills at no charge, so no extra messaging platform is needed.

## Roadmap ideas

- Move the rate limiter and conversation memory to Redis
- Move company configuration out of `companies.py` into a database or admin page
- Per-company usage and cost dashboard

## License

Add a license of your choice (for example MIT) before others reuse the code.
