#!/usr/bin/env python3
"""
Cleanup script — deletes all messages posted by this bot in the channel
and resets state.json so the main scraper starts fresh.

Requires the bot token to have channels:history (public) or
groups:history (private) scope in addition to chat:write.

Run via the "Reset bot (delete messages)" GitHub Actions workflow.
"""

import json
import os
import sys
import time
import urllib.request

STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "state.json")


def slack_api(method: str, payload: dict, token: str) -> dict:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        f"https://slack.com/api/{method}",
        data=data,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json; charset=utf-8",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def slack_get(method: str, params: dict, token: str) -> dict:
    query = "&".join(f"{k}={v}" for k, v in params.items())
    req = urllib.request.Request(
        f"https://slack.com/api/{method}?{query}",
        headers={"Authorization": f"Bearer {token}"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def delete_message(channel: str, ts: str, token: str):
    result = slack_api("chat.delete", {"channel": channel, "ts": ts}, token)
    if not result.get("ok"):
        print(f"  warning: could not delete {ts}: {result.get('error')}")


def main():
    token = os.environ.get("SLACK_BOT_TOKEN")
    channel = os.environ.get("SLACK_CHANNEL_ID")

    if not token or not channel:
        print("SLACK_BOT_TOKEN and SLACK_CHANNEL_ID must be set.", file=sys.stderr)
        sys.exit(1)

    # Find the bot's own user ID so we only delete its messages.
    auth = slack_get("auth.test", {}, token)
    if not auth.get("ok"):
        print(f"auth.test failed: {auth}", file=sys.stderr)
        sys.exit(1)
    bot_user_id = auth.get("bot_id") or auth.get("user_id")
    print(f"Bot ID: {bot_user_id}")

    # Page through channel history and collect top-level bot messages.
    parent_messages = []
    cursor = None
    while True:
        params = {"channel": channel, "limit": "200"}
        if cursor:
            params["cursor"] = cursor
        result = slack_get("conversations.history", params, token)
        if not result.get("ok"):
            print(f"conversations.history failed: {result}", file=sys.stderr)
            sys.exit(1)
        for msg in result.get("messages", []):
            if msg.get("bot_id") == bot_user_id or msg.get("user") == auth.get("user_id"):
                parent_messages.append(msg["ts"])
        cursor = result.get("response_metadata", {}).get("next_cursor")
        if not cursor:
            break

    print(f"Found {len(parent_messages)} top-level bot message(s) to delete.")

    for ts in parent_messages:
        # First delete all replies in the thread.
        replies_result = slack_get(
            "conversations.replies", {"channel": channel, "ts": ts}, token
        )
        if replies_result.get("ok"):
            messages = replies_result.get("messages", [])
            # Skip the first message (it's the parent itself, delete it last).
            for reply in messages[1:]:
                print(f"  deleting reply {reply['ts']}")
                delete_message(channel, reply["ts"], token)
                time.sleep(1.2)

        print(f"deleting parent {ts}")
        delete_message(channel, ts, token)
        time.sleep(1.2)

    # Reset state.json.
    empty_state = {
        "categories": {
            "software_engineering": {"posted_ids": [], "thread_ts": None},
            "product_management": {"posted_ids": [], "thread_ts": None},
        }
    }
    with open(STATE_FILE, "w") as f:
        json.dump(empty_state, f, indent=2)
    print("state.json reset.")


if __name__ == "__main__":
    main()
