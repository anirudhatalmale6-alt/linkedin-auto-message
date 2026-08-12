# LinkedIn Automated Messaging

Send LinkedIn messages from a Python script. Runs entirely on your own machine
using your own logged-in session — no third-party service, no API keys, nothing
about your account leaves your computer.

## Why not the official LinkedIn API

LinkedIn's public API has no endpoint for messaging an arbitrary member. The
messaging endpoints exist only inside their partner programs (Sales Navigator /
Recruiter System Connect / Conversation Ads), which require an approved
partnership and are restricted to specific business cases. A normal developer
app cannot send DMs.

So this uses your own authenticated session, the same way the linkedin.com web
app does.

## Setup

```bash
pip install -r requirements.txt
python -m playwright install chromium

python linkedin_auth.py       # log in once, by hand
```

`linkedin_auth.py` opens a browser, you log in normally (2FA and captcha
included), press Enter, and your session is saved to `session.json` with 0600
permissions. It lasts a few weeks; re-run when it expires.

## Send one message

```bash
python send_message.py "https://www.linkedin.com/in/some-person/" "Hi {first_name}, ..."
```

Options:

| flag | meaning |
| --- | --- |
| `--mode auto` | try the fast API path, fall back to the browser (default) |
| `--mode api` | internal-API only, headless, ~1s |
| `--mode browser` | drive a real browser, ~10s, most reliable |
| `--show-browser` | show the window instead of running headless |

## Send to a list

```bash
python bulk_send.py contacts.csv --template message.txt --dry-run   # preview
python bulk_send.py contacts.csv --template message.txt --cap 20
```

`contacts.csv` needs a `profile_url` column. Any other column becomes a
placeholder — a `first_name` column lets you write `{first_name}` in the
template. See `contacts.example.csv` and `message.example.txt`.

Every send is recorded in `sent_log.csv`, and rows already marked `sent` are
skipped if you re-run, so an interrupted run resumes cleanly.

## Use it from your own code

```python
from linkedin_client import LinkedInMessenger

m = LinkedInMessenger(mode="auto", min_delay=30, max_delay=90, daily_cap=25)
result = m.send("https://www.linkedin.com/in/some-person/", "Hi there ...")
print(result.ok, result.mode, result.detail)
```

## Staying safe

LinkedIn restricts accounts that behave like bots. Built-in protections:

- randomised 25–70s gap between messages (configurable)
- a per-run cap, default 40
- the browser mode types the text character by character with jitter rather
  than pasting it
- real browser fingerprint and user agent

Practical guidance: stay under ~50–80 messages a day on an established account,
much lower on a new one. Vary the wording between recipients — identical text
sent hundreds of times is the single biggest trigger. Run it during your normal
working hours, not at 4am.

You can only message 1st-degree connections, people in a shared group, or
anyone if you have InMail credits. For non-connections you need a connection
request with a note instead — say the word and I'll add that.

## Files

| file | what it does |
| --- | --- |
| `linkedin_auth.py` | one-time login, saves `session.json` |
| `linkedin_client.py` | the client — profile lookup, both send paths, throttling |
| `send_message.py` | CLI for a single message |
| `bulk_send.py` | CLI for a CSV, with cap + resume |
