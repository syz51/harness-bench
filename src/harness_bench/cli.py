import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from harness_bench import lab_home, manifest

REPO = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG = REPO / "lab.toml"


def _layout(args: argparse.Namespace) -> lab_home.Layout:
    return lab_home.Layout.load(Path(args.config) if args.config else DEFAULT_CONFIG)


def _run_in(lab: lab_home.LabHome, cmd: list[str], cwd: Path | None = None, **kw):
    env = lab.env(os.environ.get("PATH", os.defpath))
    return subprocess.run(cmd, env=env, cwd=cwd or lab.path, text=True, **kw)


def cmd_lab_home(args: argparse.Namespace) -> int:
    lab = lab_home.build(Path(args.dir).resolve(), Path.home(), _layout(args))
    print(lab.path)
    return 0


def cmd_run_in(args: argparse.Namespace) -> int:
    lab = lab_home.LabHome(path=Path(args.dir).resolve(), real_home=Path.home())
    return _run_in(lab, args.cmd).returncode


def cmd_snapshot(args: argparse.Namespace) -> int:
    snap = manifest.snapshot(Path.home(), _layout(args))
    Path(args.out).write_text(json.dumps(snap, indent=1, sort_keys=True))
    print(f"{len(snap)} entries")
    return 0


def cmd_diff(args: argparse.Namespace) -> int:
    before = json.loads(Path(args.before).read_text())
    after = json.loads(Path(args.after).read_text())
    changes = manifest.diff(before, after)
    print("\n".join(changes) or "unchanged")
    return 1 if changes else 0


def _shell_errors(lab: lab_home.LabHome) -> list[str]:
    res = _run_in(lab, ["/bin/zsh", "-i", "-l", "-c", "true"], capture_output=True, timeout=60)
    return [l for l in res.stderr.splitlines() if "no such file" in l.lower() or "not found" in l]


def _login_model(lab: lab_home.LabHome) -> str:
    res = _run_in(
        lab,
        ["claude", "--agent", "explorer", "-p", "Reply with ok.", "--output-format", "json"],
        capture_output=True,
        timeout=300,
    )
    if res.returncode != 0:
        raise RuntimeError(f"claude failed in the lab: {res.stdout[-400:]} {res.stderr[-400:]}")
    out = json.loads(res.stdout)
    return ",".join(sorted(out.get("modelUsage", {}))) + f" -> {out.get('result', '').strip()!r}"


def cmd_check(args: argparse.Namespace) -> int:
    """Build a throwaway lab, prove it runs the user's setup, and prove the real setup is untouched."""
    layout = _layout(args)
    home = Path.home()
    before = manifest.snapshot(home, layout)
    (REPO / "runs").mkdir(exist_ok=True)
    root = Path(tempfile.mkdtemp(prefix="lab-", dir=REPO / "runs"))
    failures: list[str] = []
    try:
        lab = lab_home.build(root / "home", home, layout)
        version = _run_in(lab, ["claude", "--version"], capture_output=True).stdout.strip()
        print(f"claude in lab: {version}")
        for line in _shell_errors(lab):
            failures.append(f"shell startup: {line}")
        if args.login:
            print(f"login: {_login_model(lab)}")
    finally:
        shutil.rmtree(root)
    after = manifest.snapshot(home, layout)
    failures += [f"real setup {c}" for c in manifest.diff(before, after)]
    failures += [f"leak {l}" for l in manifest.leaks(home, [root])]
    print("\n".join(failures) or "ok: the real setup is unchanged")
    return 1 if failures else 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="harness-bench")
    p.add_argument("--config", help="lab layout TOML (default: lab.toml in the repo)")
    sub = p.add_subparsers(required=True)

    s = sub.add_parser("lab-home", help="build a lab HOME in an empty folder")
    s.add_argument("dir")
    s.set_defaults(fn=cmd_lab_home)

    s = sub.add_parser("run-in", help="run a command with a lab HOME's clean environment")
    s.add_argument("dir")
    s.add_argument("cmd", nargs=argparse.REMAINDER)
    s.set_defaults(fn=cmd_run_in)

    s = sub.add_parser("snapshot", help="hash the real setup")
    s.add_argument("out")
    s.set_defaults(fn=cmd_snapshot)

    s = sub.add_parser("diff", help="compare two snapshots")
    s.add_argument("before")
    s.add_argument("after")
    s.set_defaults(fn=cmd_diff)

    s = sub.add_parser("check", help="build a throwaway lab and verify isolation")
    s.add_argument("--login", action="store_true", help="also send one Haiku prompt as the explorer agent")
    s.set_defaults(fn=cmd_check)

    args = p.parse_args(argv)
    if getattr(args, "cmd", None) and args.cmd[:1] == ["--"]:
        args.cmd = args.cmd[1:]
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
