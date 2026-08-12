"""
One-time login helper.

Opens a real Chromium window, you log into LinkedIn by hand (email, password,
2FA, captcha - whatever it throws at you). When you're on the feed, come back
to the terminal and press Enter. The session is written to session.json in this
folder and reused by every other script.

Nothing is sent anywhere. session.json never leaves your machine.

    python linkedin_auth.py
"""

import json
import os
import sys

from playwright.sync_api import sync_playwright

SESSION_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "session.json")


def login(headless: bool = False) -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        context = browser.new_context(
            viewport={"width": 1280, "height": 800},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            ),
        )
        page = context.new_page()
        page.goto("https://www.linkedin.com/login", wait_until="domcontentloaded")

        print("\nA browser window is open. Log into LinkedIn there.")
        print("Once you can see your feed, come back here and press Enter.\n")
        input("Press Enter when you are logged in... ")

        cookies = {c["name"]: c["value"] for c in context.cookies()}
        if "li_at" not in cookies:
            print(
                "\nCouldn't find the li_at cookie - that means you're not logged in yet.\n"
                "Run the script again and finish the login before pressing Enter.",
                file=sys.stderr,
            )
            browser.close()
            sys.exit(1)

        context.storage_state(path=SESSION_FILE)
        browser.close()

    os.chmod(SESSION_FILE, 0o600)
    print(f"\nSession saved to {SESSION_FILE}")
    print("You can now run send_message.py / bulk_send.py.")
    print("Sessions last a few weeks. When it expires, just run this script again.")


def load_cookies() -> dict:
    """Return {name: value} for the cookies saved by login()."""
    if not os.path.exists(SESSION_FILE):
        raise FileNotFoundError(
            "session.json not found - run `python linkedin_auth.py` first."
        )
    with open(SESSION_FILE, "r", encoding="utf-8") as fh:
        state = json.load(fh)
    return {c["name"]: c["value"] for c in state.get("cookies", [])}


if __name__ == "__main__":
    login()
