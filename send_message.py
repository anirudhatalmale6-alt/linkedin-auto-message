"""
Send one message.

    python send_message.py "https://www.linkedin.com/in/some-person/" "Hi John, saw your post about X..."
    python send_message.py some-person "Hi John" --mode browser --show-browser

Use {first_name} in the text and it gets filled in from the profile slug,
e.g. /in/john-smith-123 -> "John".
"""

import argparse
import sys

from linkedin_client import LinkedInError, LinkedInMessenger, public_id_from_url


def guess_first_name(url_or_id: str) -> str:
    slug = public_id_from_url(url_or_id)
    first = slug.split("-")[0]
    return first.capitalize() if first.isalpha() else "there"


def main() -> int:
    parser = argparse.ArgumentParser(description="Send a LinkedIn message")
    parser.add_argument("profile", help="profile URL or public id")
    parser.add_argument("message", help="message text ({first_name} is substituted)")
    parser.add_argument("--mode", default="auto", choices=["auto", "api", "browser"])
    parser.add_argument("--show-browser", action="store_true", help="watch it happen")
    args = parser.parse_args()

    text = args.message.replace("{first_name}", guess_first_name(args.profile))

    try:
        messenger = LinkedInMessenger(mode=args.mode, headless=not args.show_browser)
        result = messenger.send(args.profile, text)
    except (LinkedInError, FileNotFoundError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    return 0 if result.ok else 1


if __name__ == "__main__":
    sys.exit(main())
