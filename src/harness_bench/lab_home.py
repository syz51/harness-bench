"""Build an isolated HOME that runs the user's exact agent setup without writing to it.

Config is copied, so anything a host or Claude Code writes stays in the lab. Only the login
(the macOS keychain) and executables are linked. Bin folders get one link per file, so a new
file created there lands in the lab, and only the unmodified `claude` binary reads the login.
"""

import json
import os
import shutil
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

# Runtime data under ~/.claude: history, transcripts and caches of the real install.
CLAUDE_RUNTIME = frozenset(
    {
        "projects",
        "sessions",
        "session-env",
        "shell-snapshots",
        "history.jsonl",
        "paste-cache",
        "cache",
        "downloads",
        "backups",
        "telemetry",
        "todos",
        "file-history",
        "debug",
        "statsig",
        "ide",
        "stats-cache.json",
        "mcp-needs-auth-cache.json",
        "state",
        ".claude.json",
    }
)
CLAUDE_RUNTIME_SUFFIXES = (".stamp.json", ".synced-at", ".lock")
# Per-folder history and trust of the real install; a lab starts with none.
CLAUDE_JSON_DROP = ("projects", "githubRepoPaths")


@dataclass(frozen=True)
class Layout:
    """What a lab takes from the real HOME, relative to it."""

    copies: tuple[str, ...] = (
        ".zshenv",
        ".zshrc",
        ".zprofile",
        ".zlogin",
        ".bashrc",
        ".bash_profile",
        ".profile",
        ".gitconfig",
        ".config/git",
        ".oh-my-zsh",
        ".cargo/env",
        ".config/atuin",
    )
    bin_dirs: tuple[str, ...] = (".local/bin", ".bun/bin", ".cargo/bin", ".atuin/bin", "bin")
    links: tuple[str, ...] = ("Library/Keychains",)
    extra_copies: tuple[str, ...] = field(default=())

    @classmethod
    def load(cls, config: Path | None) -> "Layout":
        if config is None or not config.exists():
            return cls()
        data = tomllib.loads(config.read_text())
        return cls(extra_copies=tuple(data.get("copy", ())))

    def all_copies(self) -> tuple[str, ...]:
        return self.copies + self.extra_copies


@dataclass(frozen=True)
class LabHome:
    path: Path
    real_home: Path

    def env(self, path_var: str) -> dict[str, str]:
        """A clean environment for a host process: no variables leak from the calling session."""
        real = str(self.real_home)
        lab_path = [
            str(self.path) + p[len(real) :] if p == real or p.startswith(real + "/") else p
            for p in path_var.split(os.pathsep)
        ]
        return {
            "HOME": str(self.path),
            "USER": self.real_home.name,
            "LOGNAME": self.real_home.name,
            "SHELL": "/bin/zsh",
            "TERM": "xterm-256color",
            "LANG": "en_US.UTF-8",
            "PATH": os.pathsep.join(lab_path),
            # Pins the binary for the whole run; the updater would otherwise download into the lab.
            "DISABLE_AUTOUPDATER": "1",
        }


def claude_dir(real_home: Path) -> tuple[Path, str]:
    """The real Claude config folder and where it sits relative to HOME (it may be a link)."""
    link = real_home / ".claude"
    target = link.resolve()
    try:
        return target, str(target.relative_to(real_home))
    except ValueError:
        return target, ".claude"


def claude_config_entries(real_claude: Path) -> list[str]:
    return sorted(
        e.name
        for e in real_claude.iterdir()
        if e.name not in CLAUDE_RUNTIME and not e.name.endswith(CLAUDE_RUNTIME_SUFFIXES)
    )


def _copy(src: Path, dst: Path) -> None:
    if not src.exists() and not src.is_symlink():
        return
    dst.parent.mkdir(parents=True, exist_ok=True)
    if src.is_dir() and not src.is_symlink():
        shutil.copytree(src, dst, symlinks=True)
    else:
        shutil.copy2(src, dst, follow_symlinks=False)


def _link_each(src: Path, dst: Path) -> None:
    if not src.is_dir():
        return
    dst.mkdir(parents=True, exist_ok=True)
    for entry in src.iterdir():
        (dst / entry.name).symlink_to(entry)


def build(lab: Path, real_home: Path, layout: Layout = Layout()) -> LabHome:
    if lab.exists() and any(lab.iterdir()):
        raise FileExistsError(f"lab home {lab} is not empty")
    lab.mkdir(parents=True, exist_ok=True)

    real_claude, claude_rel = claude_dir(real_home)
    for name in claude_config_entries(real_claude):
        _copy(real_claude / name, lab / claude_rel / name)
    if claude_rel != ".claude":
        (lab / ".claude").symlink_to(claude_rel)

    for rel in layout.all_copies():
        _copy(real_home / rel, lab / rel)
    for rel in layout.bin_dirs:
        _link_each(real_home / rel, lab / rel)
    for rel in layout.links:
        if (real_home / rel).exists():
            (lab / rel).parent.mkdir(parents=True, exist_ok=True)
            (lab / rel).symlink_to(real_home / rel)

    real_json = real_home / ".claude.json"
    if real_json.exists():
        data = json.loads(real_json.read_text())
        for key in CLAUDE_JSON_DROP:
            data.pop(key, None)
        (lab / ".claude.json").write_text(json.dumps(data, indent=2))
        (lab / ".claude.json").chmod(0o600)
    return LabHome(path=lab, real_home=real_home)
