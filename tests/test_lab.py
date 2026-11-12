import json
from pathlib import Path

import pytest

from harness_bench import lab_home, manifest


@pytest.fixture
def real(tmp_path: Path) -> Path:
    """A fake real HOME shaped like a dotfiles setup: ~/.claude links into ~/.config/claude."""
    home = tmp_path / "real"
    claude = home / ".config/claude"
    (claude / "hooks").mkdir(parents=True)
    (claude / "hooks/guard.js").write_text("guard")
    (claude / "settings.json").write_text("{}")
    (claude / "projects/-x").mkdir(parents=True)
    (claude / "history.jsonl").write_text("")
    (claude / "remote-settings.json.synced-at").write_text("1")
    (home / ".claude").symlink_to(".config/claude")
    # A skill installed elsewhere and linked in by an absolute path, as skill managers do.
    (home / ".agents/skills/tool").mkdir(parents=True)
    (home / ".agents/skills/tool/SKILL.md").write_text("skill")
    (claude / "skills").mkdir()
    (claude / "skills/tool").symlink_to(home / ".agents/skills/tool")
    (claude / "skills/alias").symlink_to("tool")
    (claude / "plugins").mkdir()
    (claude / "plugins/known_marketplaces.json").write_text("{}")
    (home / ".zshrc").write_text("source $HOME/.config/shell/x.zsh")
    (home / ".config/shell").mkdir(parents=True)
    (home / ".config/shell/x.zsh").write_text("x")
    (home / ".local/bin").mkdir(parents=True)
    (home / ".local/bin/claude").write_text("bin")
    (home / "Library/Keychains").mkdir(parents=True)
    (home / ".claude.json").write_text(
        json.dumps({"mcpServers": {"board": {}}, "oauthAccount": {"a": 1}, "projects": {"/p": {}}})
    )
    return home


LAYOUT = lab_home.Layout(extra_copies=(".config/shell",))


def test_lab_copies_config_and_links_only_login_and_binaries(real: Path, tmp_path: Path):
    lab = lab_home.build(tmp_path / "lab", real, LAYOUT).path

    assert (lab / ".claude").readlink() == Path(".config/claude")
    hook = lab / ".config/claude/hooks/guard.js"
    assert not hook.is_symlink() and hook.read_text() == "guard"
    for runtime in ("projects", "history.jsonl", "remote-settings.json.synced-at"):
        assert not (lab / ".config/claude" / runtime).exists()
    skill = lab / ".config/claude/skills/tool"
    assert not skill.is_symlink() and (skill / "SKILL.md").read_text() == "skill"
    assert (lab / ".config/claude/skills/alias").readlink() == Path("tool")
    assert not (lab / ".config/shell/x.zsh").is_symlink()
    assert (lab / ".local/bin").is_dir() and not (lab / ".local/bin").is_symlink()
    assert (lab / ".local/bin/claude").readlink() == real / ".local/bin/claude"
    assert (lab / "Library/Keychains").readlink() == real / "Library/Keychains"
    data = json.loads((lab / ".claude.json").read_text())
    assert "projects" not in data and data["oauthAccount"] == {"a": 1}


def test_lab_refuses_a_non_empty_folder(real: Path, tmp_path: Path):
    (tmp_path / "lab").mkdir()
    (tmp_path / "lab/x").write_text("")
    with pytest.raises(FileExistsError):
        lab_home.build(tmp_path / "lab", real, LAYOUT)


def test_writes_in_the_lab_leave_the_real_setup_unchanged(real: Path, tmp_path: Path):
    before = manifest.snapshot(real, LAYOUT)
    lab = lab_home.build(tmp_path / "lab", real, LAYOUT).path
    (lab / ".claude/hooks/herdr-agent-state.sh").write_text("hook")
    (lab / ".claude/settings.json").write_text('{"hooks": {}}')
    (lab / ".claude/skills/tool/SKILL.md").write_text("edited in the lab")
    (lab / ".config/herdr").mkdir()
    (lab / ".local/bin/new-tool").write_text("")
    assert manifest.diff(before, manifest.snapshot(real, LAYOUT)) == []
    assert not (real / ".local/bin/new-tool").exists()


def test_manifest_reports_host_writes_to_the_real_setup(real: Path):
    before = manifest.snapshot(real, LAYOUT)
    (real / ".claude/hooks/herdr-agent-state.sh").write_text("hook")
    (real / ".claude/settings.json").write_text('{"hooks": {}}')
    (real / ".agents/skills/tool/SKILL.md").write_text("edited through the link")
    (real / ".claude/plugins/known_marketplaces.json").write_text('{"refreshed": 1}')
    (real / ".config/herdr").mkdir()
    (real / ".config/herdr/herdr-server.log").write_text("")
    # Live sessions churn the rest of ~/.claude.json; only the copied keys count.
    data = json.loads((real / ".claude.json").read_text())
    (real / ".claude.json").write_text(json.dumps(data | {"numStartups": 9}))
    assert manifest.diff(before, manifest.snapshot(real, LAYOUT)) == [
        "added .config/claude/hooks/herdr-agent-state.sh",
        "changed .config/claude/settings.json",
        "changed .config/claude/skills/alias/SKILL.md",
        "changed .config/claude/skills/tool/SKILL.md",
        "added .config/herdr/herdr-server.log",
    ]


def test_leaks_find_lab_folders_in_real_runtime_data(real: Path, tmp_path: Path):
    lab = tmp_path / "runs/lab-a_b1"
    assert manifest.leaks(real, [lab]) == []
    # Claude Code turns every character but letters and digits into "-".
    (real / ".claude/projects" / str(lab / "my.repo").replace("/", "-").replace(".", "-").replace("_", "-")).mkdir()
    data = json.loads((real / ".claude.json").read_text())
    data["projects"][str(lab / "repo")] = {}
    data["githubRepoPaths"] = {"owner/repo": [str(lab / "repo")]}
    (real / ".claude.json").write_text(json.dumps(data))
    # A half-written line from a live session is skipped, not fatal.
    (real / ".claude/history.jsonl").write_text('{"proj\n' + json.dumps({"project": str(lab / "repo")}) + "\n")
    assert len(manifest.leaks(real, [lab])) == 4


def test_snapshot_handles_claude_config_outside_home(tmp_path: Path):
    home, outside = tmp_path / "home", tmp_path / "volume/claude"
    (outside / "agents").mkdir(parents=True)
    (outside / "agents/a.md").write_text("a")
    home.mkdir()
    (home / ".claude").symlink_to(outside)
    assert manifest.snapshot(home, lab_home.Layout(copies=())) == {".claude/agents/a.md": manifest.snapshot(home, lab_home.Layout(copies=()))[".claude/agents/a.md"]}
    lab = lab_home.build(tmp_path / "lab", home, lab_home.Layout(copies=())).path
    assert (lab / ".claude/agents/a.md").read_text() == "a"
