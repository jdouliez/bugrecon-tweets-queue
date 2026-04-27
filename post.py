#!/usr/bin/env python3
"""
Post a scheduled BugRecon tweet/thread to X.com via Playwright.

Usage: python post.py <slot_number>

Required env vars:
  X_AUTH_TOKEN    - X.com auth_token cookie value
  DISCORD_WEBHOOK - Discord webhook URL for success/failure notifications

Reads schedule.json from CWD, finds the matching slot, publishes the tweet
or thread (with images), then notifies Discord of the outcome.
"""
import json
import os
import sys
import traceback
import urllib.request
from pathlib import Path


def notify_discord(webhook, success, slot, name, detail=""):
    if not webhook:
        return
    color = 3066993 if success else 15158332
    title = ("✅ Tweet publié" if success else "❌ Échec publication") + f" — slot {slot} ({name})"
    payload = {
        "username": "BugRecon CM",
        "embeds": [{
            "title": title,
            "description": detail or "",
            "color": color,
            "footer": {"text": "claude-code · scheduled-tweet"},
        }],
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        webhook, data=data, method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        urllib.request.urlopen(req, timeout=15)
    except Exception as e:
        print(f"[discord] notify failed: {e}", file=sys.stderr)


def post(slot_n, auth_token, webhook):
    repo_root = Path(__file__).resolve().parent
    schedule = json.loads((repo_root / "schedule.json").read_text())
    entry = next((s for s in schedule if s["slot"] == slot_n), None)
    if not entry:
        raise RuntimeError(f"slot {slot_n} not found in schedule.json")

    name = entry["name"]
    tweets = entry["tweets"]
    print(f"[post] slot={slot_n} name={name} tweets={len(tweets)}")

    from playwright.sync_api import sync_playwright

    posted_url = None
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
        ctx = browser.new_context(
            user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 900},
        )
        ctx.add_cookies([{
            "name": "auth_token", "value": auth_token,
            "domain": ".x.com", "path": "/",
            "httpOnly": True, "secure": True, "sameSite": "None",
        }])
        page = ctx.new_page()
        page.goto("https://x.com/home", wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(4000)

        # Verify logged in
        if "/login" in page.url or "/i/flow/login" in page.url:
            raise RuntimeError(f"auth_token rejected, ended at {page.url}")

        for idx, t in enumerate(tweets):
            is_first = (idx == 0)
            print(f"[post] tweet {idx+1}/{len(tweets)} chars={len(t['text'])}")

            if is_first:
                page.goto("https://x.com/compose/post", wait_until="domcontentloaded", timeout=60000)
                page.wait_for_timeout(2500)
                editor = page.locator('div[role="textbox"][data-testid^="tweetTextarea"]').first
            else:
                # Click "Add another post" button to add a thread tweet
                add_btn = page.locator('[data-testid="addButton"]').first
                add_btn.wait_for(timeout=10000)
                add_btn.click()
                page.wait_for_timeout(800)
                # New textarea is the last one
                editor = page.locator('div[role="textbox"][data-testid^="tweetTextarea"]').last

            editor.click()
            page.wait_for_timeout(300)
            editor.fill(t["text"])
            page.wait_for_timeout(700)

            img = t.get("image")
            if img:
                img_path = str(repo_root / img)
                if not os.path.exists(img_path):
                    raise RuntimeError(f"image missing: {img_path}")
                file_inputs = page.locator('input[data-testid="fileInput"]').all()
                if not file_inputs:
                    raise RuntimeError("no fileInput found")
                file_inputs[idx].set_input_files(img_path)
                # Wait for upload
                page.wait_for_timeout(4500)

        page.wait_for_timeout(1500)
        # Click the final "Post all" / "Post" button
        post_btn = page.locator('[data-testid="tweetButton"]').first
        post_btn.wait_for(state="visible", timeout=10000)
        # ensure not disabled
        for _ in range(10):
            disabled = post_btn.get_attribute("aria-disabled") or ""
            if disabled.lower() != "true":
                break
            page.wait_for_timeout(500)
        post_btn.click()
        page.wait_for_timeout(8000)

        # Resolve posted URL by visiting profile
        page.goto("https://x.com/Bug_Recon", wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(3500)
        href = page.evaluate(
            """() => {
                const arts = document.querySelectorAll('article');
                for (const a of arts) {
                    const link = a.querySelector('a[href*="/Bug_Recon/status/"]');
                    if (link) return link.href;
                }
                return null;
            }"""
        )
        posted_url = href
        ctx.close()
        browser.close()

    return posted_url


def main():
    if len(sys.argv) < 2:
        print("usage: post.py <slot>", file=sys.stderr)
        sys.exit(2)
    slot_n = int(sys.argv[1])
    auth_token = os.environ.get("X_AUTH_TOKEN")
    webhook = os.environ.get("DISCORD_WEBHOOK")
    if not auth_token:
        print("X_AUTH_TOKEN env var required", file=sys.stderr)
        sys.exit(2)

    try:
        url = post(slot_n, auth_token, webhook)
        detail = f"[Voir le tweet]({url})\n\nURL: {url}" if url else "Posted (URL not resolved)."
        # Get name for the embed
        with open(Path(__file__).resolve().parent / "schedule.json") as f:
            sched = json.load(f)
        name = next((s["name"] for s in sched if s["slot"] == slot_n), "?")
        notify_discord(webhook, True, slot_n, name, detail)
        print(f"OK slot={slot_n} url={url}")
    except Exception as e:
        tb = traceback.format_exc()
        print(tb, file=sys.stderr)
        try:
            with open(Path(__file__).resolve().parent / "schedule.json") as f:
                sched = json.load(f)
            name = next((s["name"] for s in sched if s["slot"] == slot_n), "?")
        except Exception:
            name = "?"
        detail = f"```\n{str(e)[:1500]}\n```"
        notify_discord(webhook, False, slot_n, name, detail)
        sys.exit(1)


if __name__ == "__main__":
    main()
