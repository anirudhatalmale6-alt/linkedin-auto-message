"""
LinkedIn messaging client.

Two ways of sending, both using the session you created with linkedin_auth.py:

  mode="api"      talks to the same internal endpoints the linkedin.com web app
                  calls. Fast, headless, no browser. Can break when LinkedIn
                  changes their frontend.

  mode="browser"  drives a real Chromium window through the normal Message
                  flow. Slower (~10s per message) but it is exactly what a
                  human does, so it keeps working.

  mode="auto"     (default) tries the API, falls back to the browser.

Everything runs on your machine. No third party ever sees your session.
"""

from __future__ import annotations

import json
import random
import re
import time
import uuid
from dataclasses import dataclass
from typing import Optional

import requests

from linkedin_auth import SESSION_FILE, load_cookies

BASE = "https://www.linkedin.com"
VOYAGER = f"{BASE}/voyager/api"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


class LinkedInError(RuntimeError):
    pass


@dataclass
class SendResult:
    profile: str
    ok: bool
    mode: str
    detail: str = ""

    def __str__(self) -> str:
        status = "sent" if self.ok else "FAILED"
        return f"[{status}] {self.profile} ({self.mode}) {self.detail}".rstrip()


def public_id_from_url(url_or_id: str) -> str:
    """Accept a full profile URL or a bare public id, return the public id."""
    value = url_or_id.strip().rstrip("/")
    match = re.search(r"linkedin\.com/in/([^/?#]+)", value)
    if match:
        return match.group(1)
    if "/" in value or " " in value:
        raise LinkedInError(f"Doesn't look like a profile URL or id: {url_or_id!r}")
    return value


class LinkedInMessenger:
    def __init__(
        self,
        mode: str = "auto",
        min_delay: float = 25.0,
        max_delay: float = 70.0,
        daily_cap: int = 40,
        headless: bool = True,
        verbose: bool = True,
    ):
        if mode not in ("auto", "api", "browser"):
            raise ValueError("mode must be auto, api or browser")
        self.mode = mode
        self.min_delay = min_delay
        self.max_delay = max_delay
        self.daily_cap = daily_cap
        self.headless = headless
        self.verbose = verbose
        self.sent_count = 0
        self._last_send: Optional[float] = None

        self.cookies = load_cookies()
        if "li_at" not in self.cookies:
            raise LinkedInError("No li_at cookie in session.json - run linkedin_auth.py again.")

        csrf = self.cookies.get("JSESSIONID", "").strip('"')
        self.session = requests.Session()
        self.session.cookies.update(self.cookies)
        self.session.headers.update(
            {
                "user-agent": USER_AGENT,
                "csrf-token": csrf,
                "x-restli-protocol-version": "2.0.0",
                "x-li-lang": "en_US",
                "accept": "application/vnd.linkedin.normalized+json+2.1",
                "referer": f"{BASE}/feed/",
            }
        )
        self._me_urn: Optional[str] = None

    # ------------------------------------------------------------------ utils

    def _log(self, message: str) -> None:
        if self.verbose:
            print(message, flush=True)

    def _throttle(self) -> None:
        """Human-ish pause between messages. First message goes out immediately."""
        if self._last_send is None:
            return
        wait = random.uniform(self.min_delay, self.max_delay)
        elapsed = time.time() - self._last_send
        remaining = wait - elapsed
        if remaining > 0:
            self._log(f"  ...waiting {remaining:.0f}s before the next one")
            time.sleep(remaining)

    # -------------------------------------------------------------- api layer

    def me(self) -> str:
        """URN id of the logged-in account (the ACoAA... part)."""
        if self._me_urn:
            return self._me_urn
        response = self.session.get(f"{VOYAGER}/me", timeout=30)
        if response.status_code != 200:
            raise LinkedInError(f"/me returned {response.status_code} - session probably expired")
        urn = json.dumps(response.json())
        match = re.search(r"urn:li:fsd?_profile:\(?(ACoAA[\w\-_]+)", urn)
        if not match:
            raise LinkedInError("Could not read your own profile id from /me")
        self._me_urn = match.group(1)
        return self._me_urn

    def resolve_profile(self, url_or_id: str) -> str:
        """Profile URL -> member id (ACoAA...)."""
        public_id = public_id_from_url(url_or_id)
        response = self.session.get(f"{VOYAGER}/identity/profiles/{public_id}", timeout=30)
        if response.status_code == 404:
            raise LinkedInError(f"Profile not found: {public_id}")
        if response.status_code != 200:
            raise LinkedInError(f"Profile lookup for {public_id} returned {response.status_code}")
        match = re.search(r"(ACoAA[\w\-_]+)", response.text)
        if not match:
            raise LinkedInError(f"Could not extract the member id for {public_id}")
        return match.group(1)

    def _send_api(self, member_id: str, message: str) -> None:
        """Newer messenger endpoint first, legacy conversations endpoint as backup."""
        me = self.me()
        mailbox = f"urn:li:fsd_profile:{me}"
        payload = {
            "message": {
                "body": {"text": message, "attributes": []},
                "renderContentUnions": [],
                "conversationTitle": None,
            },
            "mailboxUrn": mailbox,
            "trackingId": str(uuid.uuid4()),
            "dedupeByClientGeneratedToken": False,
            "hostRecipientUrns": [f"urn:li:fsd_profile:{member_id}"],
        }
        response = self.session.post(
            f"{VOYAGER}/voyagerMessagingDashMessengerMessages?action=createMessage",
            json=payload,
            timeout=30,
        )
        if response.status_code in (200, 201):
            return

        legacy = {
            "keyVersion": "LEGACY_INBOX",
            "conversationCreate": {
                "eventCreate": {
                    "originToken": str(uuid.uuid4()),
                    "value": {
                        "com.linkedin.voyager.messaging.create.MessageCreate": {
                            "body": message,
                            "attachments": [],
                            "attributedBody": {"text": message, "attributes": []},
                            "mediaAttachments": [],
                        }
                    },
                },
                "subtype": "MEMBER_TO_MEMBER",
                "recipients": [member_id],
            },
        }
        legacy_response = self.session.post(
            f"{VOYAGER}/messaging/conversations?action=create",
            json=legacy,
            timeout=30,
        )
        if legacy_response.status_code in (200, 201):
            return
        raise LinkedInError(
            f"API send refused (modern {response.status_code}, legacy {legacy_response.status_code})"
        )

    # ---------------------------------------------------------- browser layer

    def _send_browser(self, profile_url: str, message: str) -> None:
        from playwright.sync_api import sync_playwright

        public_id = public_id_from_url(profile_url)
        url = f"{BASE}/in/{public_id}/"

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=self.headless)
            context = browser.new_context(
                storage_state=SESSION_FILE,
                viewport={"width": 1280, "height": 800},
                user_agent=USER_AGENT,
            )
            page = context.new_page()
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=60000)
                page.wait_for_timeout(random.randint(2000, 4000))

                if "/authwall" in page.url or "/login" in page.url:
                    raise LinkedInError("Session expired - run linkedin_auth.py again")

                message_button = page.locator(
                    "main button:has-text('Message'), main a:has-text('Message')"
                ).first
                if message_button.count() == 0:
                    raise LinkedInError(
                        "No Message button on this profile - you are probably not "
                        "connected, or they have messaging restricted"
                    )
                message_button.click()
                page.wait_for_timeout(random.randint(1500, 3000))

                box = page.locator(
                    "div.msg-form__contenteditable[contenteditable='true'], "
                    "div[role='textbox'][contenteditable='true']"
                ).first
                box.wait_for(state="visible", timeout=20000)
                box.click()

                # type it out rather than pasting - looks like a person
                for chunk in message.split("\n"):
                    page.keyboard.type(chunk, delay=random.randint(15, 45))
                    if chunk != message.split("\n")[-1]:
                        page.keyboard.press("Shift+Enter")
                page.wait_for_timeout(random.randint(800, 1600))

                send_button = page.locator("button.msg-form__send-button, button:has-text('Send')").first
                send_button.wait_for(state="visible", timeout=15000)
                if send_button.is_disabled():
                    raise LinkedInError("Send button stayed disabled - message may be empty")
                send_button.click()
                page.wait_for_timeout(random.randint(2000, 3500))
            finally:
                context.close()
                browser.close()

    # ------------------------------------------------------------- public api

    def send(self, profile_url: str, message: str) -> SendResult:
        if self.sent_count >= self.daily_cap:
            return SendResult(profile_url, False, "-", f"daily cap of {self.daily_cap} reached")

        self._throttle()
        self._log(f"-> {profile_url}")

        errors = []
        modes = {"auto": ["api", "browser"], "api": ["api"], "browser": ["browser"]}[self.mode]

        for mode in modes:
            try:
                if mode == "api":
                    member_id = self.resolve_profile(profile_url)
                    self._send_api(member_id, message)
                else:
                    self._send_browser(profile_url, message)
            except Exception as exc:  # noqa: BLE001 - report, try the next mode
                errors.append(f"{mode}: {exc}")
                self._log(f"  {mode} failed: {exc}")
                continue

            self.sent_count += 1
            self._last_send = time.time()
            result = SendResult(profile_url, True, mode)
            self._log(f"  {result}")
            return result

        self._last_send = time.time()
        return SendResult(profile_url, False, modes[-1], " | ".join(errors))
