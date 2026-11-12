"""Prove a run left the user's real setup unchanged.

A snapshot hashes every file the lab copies from, including what links point to, the T3
settings, and the places hosts write to when they run against the real HOME. Other live
sessions keep writing runtime data, so the leak check looks only for traces of the lab's own
folders there.
"""

import hashlib
import json
import re
from fnmatch import fnmatch
from pathlib import Path

from harness_bench.lab_home import CLAUDE_JSON_DROP, Layout, claude_config_entries, claude_dir

# Places a host writes to when it runs against the real HOME instead of a lab.
HOST_STATE = (".config/herdr", ".t3/userdata/settings.json")
# Files that live sessions and shells rewrite on their own: plugin and policy refreshes, caches.
VOLATILE = (
    "plugins/known_marketplaces.json",
    "plugins/plugin-directory-cache*",
    "plugins/store/*",
    "plugins/*.lock",
    ".last-cleanup",
    ".last-update-result.json",
    "policy-limits.json*",
    "remote-settings.json*",
    ".oh-my-zsh/cache/*",
    ".oh-my-zsh/log/*",
    "*/.DS_Store",
)


def _hash_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _walk(path: Path, key: str, out: dict[str, str], seen: frozenset[Path] = frozenset()) -> None:
    """Hash files under `path`, following links, keyed by their path as the lab sees it."""
    if any(fnmatch(key, pattern) or fnmatch(key, "*/" + pattern) for pattern in VOLATILE):
        return
    target = path.resolve()
    if not target.exists() or target in seen:
        return
    if target.is_dir():
        for entry in sorted(target.iterdir()):
            _walk(entry, f"{key}/{entry.name}", out, seen | {target})
    else:
        out[key] = _hash_file(target)


def snapshot(real_home: Path, layout: Layout = Layout()) -> dict[str, str]:
    out: dict[str, str] = {}
    real_claude, claude_rel = claude_dir(real_home)
    for name in claude_config_entries(real_claude):
        _walk(real_claude / name, f"{claude_rel}/{name}", out)
    for rel in layout.all_copies() + HOST_STATE:
        _walk(real_home / rel, rel, out)
    real_json = real_home / ".claude.json"
    if real_json.exists():
        data = json.loads(real_json.read_text())
        # Only the keys a lab copies and could be blamed for; the rest churns with live sessions.
        stable = {k: data.get(k) for k in ("mcpServers", "oauthAccount")}
        out[".claude.json#stable"] = hashlib.sha256(
            json.dumps(stable, sort_keys=True).encode()
        ).hexdigest()
    return out


def diff(before: dict[str, str], after: dict[str, str]) -> list[str]:
    changes = []
    for key in sorted(before.keys() | after.keys()):
        if key not in after:
            changes.append(f"removed {key}")
        elif key not in before:
            changes.append(f"added {key}")
        elif before[key] != after[key]:
            changes.append(f"changed {key}")
    return changes


def project_key(path: Path) -> str:
    """The folder name Claude Code gives a working directory's transcripts."""
    return re.sub(r"[^A-Za-z0-9]", "-", str(path))


def _paths_in(value: object) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [v for v in value if isinstance(v, str)]
    return []


def leaks(real_home: Path, lab_paths: list[Path]) -> list[str]:
    """Traces of a lab or its workload folders in the real install's runtime data."""
    found = []
    prefixes = [str(p) for p in lab_paths]
    keys = [project_key(p) for p in lab_paths]
    real_claude, _ = claude_dir(real_home)
    projects = real_claude / "projects"
    if projects.is_dir():
        for entry in projects.iterdir():
            if any(entry.name.startswith(k) for k in keys):
                found.append(f"transcripts {entry}")
    real_json = real_home / ".claude.json"
    if real_json.exists():
        data = json.loads(real_json.read_text())
        for drop in CLAUDE_JSON_DROP:
            for key, value in (data.get(drop) or {}).items():
                if any(p.startswith(prefix) for p in [key, *_paths_in(value)] for prefix in prefixes):
                    found.append(f"~/.claude.json {drop} {key}")
    history = real_claude / "history.jsonl"
    if history.exists():
        for line in history.read_text().splitlines():
            try:
                project = json.loads(line).get("project") or ""
            except (ValueError, AttributeError):
                continue  # a line a live session is still writing
            if any(project.startswith(p) for p in prefixes):
                found.append(f"history.jsonl entry {project}")
                break
    return found
