#!/usr/bin/env python3
"""
Find the smallest channels (that I'm in) containing all given users.

Usage:
  slack_smallest_channels.py "Xavier Lamorlette" "oli@datadoghq.com"
  slack_smallest_channels.py -n 5 "Xavier Lamorlette"

Steps:
  1. Resolve each user -> Slack ID. A user arg may be a raw ID (U.../W...),
     an email (contains '@'), or a full name (mapped to the corporate email
     convention first.last@DOMAIN, looked up via users.lookupByEmail).
     If any user can't be resolved, report it and stop.
  2. List my channels (public + private I'm in) with member counts.
  3. Sort ascending by member count.
  4. Walk that list, checking membership; stop once N matches are found.
  5. Print the N smallest matches: count, public/private, name.

The Slack token is read straight from the Claude Code keychain entry, so no
token needs to be passed in. Only the final result is printed to stdout;
diagnostics go to stderr. Add -v for progress.
"""

import argparse
import json
import subprocess
import sys
import time
import unicodedata
import urllib.error, urllib.parse, urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any, Final

API: Final[str] = "https://slack.com/api/"
DOMAIN: Final[str] = "datadoghq.com"
KEYCHAIN_SERVICE: Final[str] = "Claude Code-credentials"


def log(verbose: bool, *messages: object) -> None:
    if verbose:
        print(*messages, file=sys.stderr, flush=True)


@dataclass
class ChannelInfo:
    id: str
    name: str
    is_private: bool
    num_members: int = 0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("users", nargs="+", help="names, emails, or Slack IDs")
    parser.add_argument(
        "-n", type=int, default=3, dest="nb_wanted", help="how many matches (default 3)"
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    access_token: str = get_access_token(args.verbose)
    team_id: str = get_team_id(access_token)
    user_ids: list[str] = get_user_ids(access_token, args.users, args.verbose)
    my_channels: list[ChannelInfo] = fetch_my_channels(access_token, team_id, args.verbose)
    smallest_channels: list[ChannelInfo] = find_smallest_channels(
        access_token, my_channels, user_ids, args.nb_wanted, args.verbose
    )

    if not smallest_channels:
        print(f"No channels contain all {len(user_ids)} users.")
    else:
        print(
            f"{len(smallest_channels)} smallest channel(s) containing all {len(user_ids)} users:"
        )
        for channel in smallest_channels:
            kind = "private" if channel.is_private else "public "
            print(f"{channel.num_members:>5}  {kind:<7}  {channel.name}")


def get_access_token(verbose: bool) -> str:
    for token in get_candidate_access_tokens():
        response = call_api(token, "auth.test")
        if response.get("ok"):
            log(
                verbose,
                f"auth ok as {response.get('user')} on team {response.get('team')}",
            )
            return token
    sys.exit(
        "FATAL: no working Slack token in keychain. Run any Slack MCP "
        "command once to refresh auth, then retry."
    )


def get_candidate_access_tokens() -> list[str]:
    """Slack OAuth access tokens cached by Claude Code, freshest first."""
    raw = subprocess.run(
        ["security", "find-generic-password", "-s", KEYCHAIN_SERVICE, "-w"],
        capture_output=True,
        text=True,
    ).stdout
    entries = (json.loads(raw).get("mcpOAuth") or {}) if raw.strip() else {}
    candidates = []
    for key, entry in entries.items():
        name = (entry.get("serverName") or "") + "|" + key
        if "slack" in name.lower() and entry.get("accessToken"):
            candidates.append((entry.get("expiresAt") or 0, entry["accessToken"]))
    candidates.sort(reverse=True)
    seen, ordered = set(), []
    for _expirationDate, token in candidates:
        if token not in seen:
            seen.add(token)
            ordered.append(token)
    return ordered


def get_team_id(access_token: str) -> str:
    response = call_api(access_token, "auth.teams.list", limit="100")
    teams = response.get("teams") or []
    if not teams:
        sys.exit("FATAL: auth.teams.list returned no workspace.")
    return teams[0]["id"]


def call_api(token: str, method: str, **params: str) -> dict[str, Any]:
    """Slack Web API GET with rate-limit/backoff. Returns parsed JSON."""
    for attempt in range(8):
        url = API + method + "?" + urllib.parse.urlencode(params)
        request = urllib.request.Request(
            url, headers={"Authorization": "Bearer " + token}
        )
        try:
            response = json.load(urllib.request.urlopen(request, timeout=30))
        except urllib.error.HTTPError as error:
            if error.code == 429:
                time.sleep(int(error.headers.get("Retry-After", "2")) + 1)
                continue
            raise
        except urllib.error.URLError:
            time.sleep(1 + attempt)
            continue
        if not response.get("ok") and response.get("error") == "ratelimited":
            time.sleep(2)
            continue
        return response
    return {"ok": False, "error": "retries_exhausted"}


def get_user_ids(access_token: str, user_args: list[str], verbose: bool) -> list[str]:
    user_ids = []
    users_not_found = []
    for user_arg in user_args:
        if is_user_id(user_arg):
            user_ids.append(user_arg)
            continue
        emails = [user_arg] if "@" in user_arg else build_emails_from_name(user_arg)
        found_user_id = None
        for email in emails:
            response = call_api(access_token, "users.lookupByEmail", email=email)
            if response.get("ok"):
                found_user_id = response["user"]["id"]
                break
        if found_user_id:
            user_ids.append(found_user_id)
            log(verbose, f"resolved {user_arg} -> {found_user_id}")
        else:
            users_not_found.append(user_arg)
    if users_not_found:
        sys.exit(
            "FATAL: could not resolve user(s): "
            + ", ".join(users_not_found)
            + "\n(pass an explicit email or Slack ID for these)"
        )
    return user_ids


def is_user_id(arg: str) -> bool:
    return arg[:1] in "UW" and arg[1:].isalnum() and arg.upper() == arg


def build_emails_from_name(name: str) -> list[str]:
    base = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    words = [word for word in base.replace("'", "").replace(".", " ").split() if word]
    if not words:
        return []
    words = [word.lower() for word in words]
    emails = []
    if len(words) >= 2:
        emails.append(f"{words[0]}.{words[-1]}@{DOMAIN}")  # first.last
        emails.append(f"{'.'.join(words)}@{DOMAIN}")  # first.middle.last
    else:
        emails.append(f"{words[0]}@{DOMAIN}")
    return list(dict.fromkeys(emails))


def fetch_my_channels(access_token: str, team_id: str, verbose: bool) -> list[ChannelInfo]:
    channels = []
    cursor = ""
    while True:
        params = {
            "types": "public_channel,private_channel",
            "exclude_archived": "true",
            "limit": "200",
            "team_id": team_id,
        }
        if cursor:
            params["cursor"] = cursor
        response = call_api(access_token, "users.conversations", **params)
        if not response.get("ok"):
            sys.exit("FATAL: users.conversations: " + str(response.get("error")))
        channels += response.get("channels", [])
        cursor = (response.get("response_metadata") or {}).get("next_cursor", "")
        if not cursor:
            break
    log(verbose, f"{len(channels)} channels; fetching member counts...")

    def fetch_channel_summary(channel: dict[str, Any]) -> ChannelInfo:
        response = call_api(
            access_token,
            "conversations.info",
            channel=channel["id"],
            include_num_members="true",
            team_id=team_id,
        )
        return ChannelInfo(
            id=channel["id"],
            name=channel["name"],
            is_private=bool(channel.get("is_private")),
            num_members=(response.get("channel") or {}).get("num_members") or 0,
        )

    with ThreadPoolExecutor(max_workers=10) as executor:
        return list(executor.map(fetch_channel_summary, channels))


def find_smallest_channels(
    access_token: str,
    channels: list[ChannelInfo],
    user_ids: list[str],
    nb_wanted: int,
    verbose: bool,
) -> list[ChannelInfo]:
    channels_sorted_by_size = sorted(
        channels, key=lambda channel: (channel.num_members, channel.name)
    )

    def channel_if_all_users_present(channel: ChannelInfo) -> ChannelInfo | None:
        return (
            channel
            if are_all_users_in_channel(access_token, channel.id, user_ids)
            else None
        )

    matching_channels = []
    batch_size = 12
    for start in range(0, len(channels_sorted_by_size), batch_size):
        group = channels_sorted_by_size[start : start + batch_size]
        with ThreadPoolExecutor(max_workers=batch_size) as executor:
            matches_in_batch = [
                channel
                for channel in executor.map(channel_if_all_users_present, group)
                if channel is not None
            ]
        for channel in matches_in_batch:
            log(verbose, f"match: {channel.name} ({channel.num_members})")
        matching_channels.extend(matches_in_batch)
        if len(matching_channels) >= nb_wanted:
            break
    return sorted(
        matching_channels, key=lambda channel: (channel.num_members, channel.name)
    )[:nb_wanted]


def are_all_users_in_channel(token: str, channel_id: str, user_ids: list[str]) -> bool:
    needed_user_ids = set(user_ids)
    cursor = ""
    while True:
        params = {"channel": channel_id, "limit": "1000"}
        if cursor:
            params["cursor"] = cursor
        response = call_api(token, "conversations.members", **params)
        if not response.get("ok"):
            return False
        needed_user_ids -= set(response.get("members", []))
        if not needed_user_ids:
            return True
        cursor = (response.get("response_metadata") or {}).get("next_cursor", "")
        if not cursor:
            return False


if __name__ == "__main__":
    main()
