# harness-bench

Profile coding-agent hosts on real, delegated work. Only the host changes between arms.

The first comparison is [T3 Code](https://github.com/pingdotgg/t3code) against
[herdr](https://herdr.dev), both running Claude Code. Every arm uses the same `claude` binary,
the same Claude config (settings, agents, hooks, skills, plugins), the same login, and the same
workload, turns and repository snapshot. Models and effort come only from that config. The
benchmark never passes a model, effort or agent override.

## What stays the same, and what does not

| Same in every arm | Part of the host, and so measured |
| --- | --- |
| `claude` binary and version | How the host drives Claude: Agent SDK (T3 Code) or the terminal UI (herdr) |
| `~/.claude` config, agents and their models and effort | The host's own instructions, tools and integrations, such as T3 Code's MCP tools or herdr's state hook and skill |
| Shell startup files and tools | Extra model calls the host makes, such as thread titles |
| Workload prompt, turns and repo snapshot | Host process CPU and memory, and when a turn counts as done |

## Lab HOME

Each run gets a new lab HOME. Your real setup is never written to:

- All config is copied: `~/.claude` (except transcripts, sessions and caches), shell startup
  files and git config. A host may install hooks or skills into its lab, and that stays there.
- Only the macOS keychain (your Claude login) and executables are linked. Bin folders get one
  link per file, so a new file lands in the lab.
- `~/.claude.json` is copied without per-folder history.
- A manifest hashes the real setup before and after. It fails on any change, and on traces of a
  lab folder in the real install's history.

## Use

```sh
uv run harness-bench check            # build a throwaway lab and prove isolation
uv run harness-bench check --login    # also send one "ok" prompt as the explorer agent
uv run harness-bench lab-home runs/x  # build a lab HOME
uv run harness-bench run-in runs/x -- claude --version
uv run harness-bench snapshot before.json   # hash the real setup; `diff` compares two
```

If your shell startup or hooks read other paths under HOME, copy `lab.example.toml` to
`lab.toml` and list them. `check` reports files your shell could not find.

## Subscription terms

This lab runs your own Claude subscription in the way its terms allow:

- Only the official, unmodified `claude` binary runs, signed in with your own login from the
  keychain. The lab never reads, copies, stores or forwards a token, and routes no request
  through another service.
- It runs on your own machine, for your own evaluation, at a capped volume of ordinary
  individual use. Do not share an account or run it as a service for others.
- Outputs are not used to train or distill models.
- Publish code and aggregate numbers only, not transcripts.

Check the current terms before you run it:
[Consumer Terms](https://www.anthropic.com/legal/consumer-terms) and the
[Claude Code legal and compliance page](https://docs.claude.com/en/docs/claude-code/legal-and-compliance).

## Status

Done: lab HOME, manifest and setup check. Next: workloads, host drivers, metrics and the report.

## License

MIT
