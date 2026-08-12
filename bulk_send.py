"""
Send to a list of people from a CSV, with throttling and a daily cap.

    python bulk_send.py contacts.csv --template message.txt
    python bulk_send.py contacts.csv --template message.txt --dry-run
    python bulk_send.py contacts.csv --template message.txt --cap 20 --min-delay 40 --max-delay 120

contacts.csv needs a `profile_url` column. Any other columns become template
placeholders, so a `first_name` column lets you write {first_name} in the
message. Already-sent rows are skipped on re-runs (tracked in sent_log.csv).
"""

import argparse
import csv
import os
import sys
from datetime import datetime

from linkedin_client import LinkedInError, LinkedInMessenger

HERE = os.path.dirname(os.path.abspath(__file__))
LOG_FILE = os.path.join(HERE, "sent_log.csv")


def already_sent() -> set:
    if not os.path.exists(LOG_FILE):
        return set()
    with open(LOG_FILE, newline="", encoding="utf-8") as fh:
        return {row["profile_url"] for row in csv.DictReader(fh) if row.get("status") == "sent"}


def log_result(profile_url: str, status: str, detail: str) -> None:
    is_new = not os.path.exists(LOG_FILE)
    with open(LOG_FILE, "a", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        if is_new:
            writer.writerow(["timestamp", "profile_url", "status", "detail"])
        writer.writerow([datetime.now().isoformat(timespec="seconds"), profile_url, status, detail])


def render(template: str, row: dict) -> str:
    text = template
    for key, value in row.items():
        text = text.replace("{" + key + "}", (value or "").strip())
    return text


def main() -> int:
    parser = argparse.ArgumentParser(description="Bulk LinkedIn messages")
    parser.add_argument("csv_file")
    parser.add_argument("--template", required=True, help="text file with the message")
    parser.add_argument("--mode", default="auto", choices=["auto", "api", "browser"])
    parser.add_argument("--cap", type=int, default=40, help="max messages this run")
    parser.add_argument("--min-delay", type=float, default=25.0)
    parser.add_argument("--max-delay", type=float, default=70.0)
    parser.add_argument("--dry-run", action="store_true", help="print, don't send")
    parser.add_argument("--show-browser", action="store_true")
    args = parser.parse_args()

    with open(args.template, encoding="utf-8") as fh:
        template = fh.read().strip()

    with open(args.csv_file, newline="", encoding="utf-8-sig") as fh:
        rows = list(csv.DictReader(fh))

    if not rows or "profile_url" not in rows[0]:
        print("CSV needs a profile_url column", file=sys.stderr)
        return 1

    done = already_sent()
    queue = [r for r in rows if r["profile_url"].strip() and r["profile_url"].strip() not in done]
    skipped = len(rows) - len(queue)
    print(f"{len(rows)} rows, {skipped} already sent, {len(queue)} to go (cap {args.cap})\n")

    if args.dry_run:
        for row in queue[: args.cap]:
            print(f"--- {row['profile_url']}\n{render(template, row)}\n")
        print("Dry run - nothing was sent.")
        return 0

    try:
        messenger = LinkedInMessenger(
            mode=args.mode,
            min_delay=args.min_delay,
            max_delay=args.max_delay,
            daily_cap=args.cap,
            headless=not args.show_browser,
        )
    except (LinkedInError, FileNotFoundError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    sent = failed = 0
    for row in queue:
        if messenger.sent_count >= args.cap:
            print(f"\nHit the cap of {args.cap} for this run. Re-run later to continue.")
            break
        result = messenger.send(row["profile_url"].strip(), render(template, row))
        log_result(row["profile_url"].strip(), "sent" if result.ok else "failed", result.detail)
        sent += result.ok
        failed += not result.ok

    print(f"\nDone. {sent} sent, {failed} failed. Full history in sent_log.csv")
    return 0


if __name__ == "__main__":
    sys.exit(main())
