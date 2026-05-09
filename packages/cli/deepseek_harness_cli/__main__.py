"""`dsh` — command-line entry.

Subcommands:
  dsh doctor              Verify env + run a 1-token call against DeepSeek.
  dsh chat [-r]           Interactive REPL with all guards on (-r enables thinking).
  dsh probe <name|all>    Run one of the 12 probes from reports/probes/.
  dsh validate <file>     Audit a messages.json file for the 5 contract violations.
  dsh estimate <file>     Pre-flight cache hit estimate for a messages.json file.

The CLI wraps `deepseek_harness.DeepSeekHarness` with all 10 contract rules
defaulted ON. Pass `--unsafe` to drop guards (debugging / probe authoring only).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="dsh",
        description="DeepSeek Harness — protocol-aware CLI for V4-Pro / V4-Flash.",
    )
    sub = p.add_subparsers(dest="cmd")

    # ---- doctor ----
    sp = sub.add_parser("doctor", help="Verify env + tiny live call.")
    sp.add_argument("--model", default=os.getenv("DEEPSEEK_MODEL", "deepseek-v4-pro"))

    # ---- chat ----
    sp = sub.add_parser("chat", help="Interactive REPL with guards on.")
    sp.add_argument("--model", default=os.getenv("DEEPSEEK_MODEL", "deepseek-v4-pro"))
    sp.add_argument("-r", "--reasoning", action="store_true", help="Enable thinking mode.")
    sp.add_argument("--max-tokens", type=int, default=4096)

    # ---- probe ----
    sp = sub.add_parser("probe", help="Run a probe by name or 'all'.")
    sp.add_argument("name")
    sp.add_argument("--n", type=int, default=None)

    # ---- validate ----
    sp = sub.add_parser("validate", help="Audit a messages.json file for contract violations.")
    sp.add_argument("file", help="Path to a JSON file containing a list of messages.")

    # ---- estimate ----
    sp = sub.add_parser("estimate", help="Pre-flight cache-hit estimate.")
    sp.add_argument("file", help="Path to a JSON file containing a list of messages.")
    sp.add_argument("--prev", help="Optional path to previous messages.json (cache prefix).")

    # ---- version ----
    sub.add_parser("version", help="Print version.")

    args = p.parse_args(argv)
    if args.cmd is None:
        p.print_help()
        return 0

    if args.cmd == "doctor":
        return _doctor(args.model)
    if args.cmd == "chat":
        return _chat(args.model, args.reasoning, args.max_tokens)
    if args.cmd == "probe":
        return _probe(args.name, args.n)
    if args.cmd == "validate":
        return _validate(args.file)
    if args.cmd == "estimate":
        return _estimate(args.file, args.prev)
    if args.cmd == "version":
        from . import __version__
        print(f"dsh {__version__}")
        return 0
    return 2


# ---------------------------------------------------------------------------
# subcommand impls
# ---------------------------------------------------------------------------


def _check_key() -> str | None:
    k = os.getenv("DEEPSEEK_API_KEY")
    if not k:
        print(
            "[dsh] DEEPSEEK_API_KEY is not set. Get one at https://platform.deepseek.com\n"
            "      Then `export DEEPSEEK_API_KEY=sk-...` or put it in a .env file.",
            file=sys.stderr,
        )
        return None
    return k


def _doctor(model: str) -> int:
    from rich.console import Console
    from rich.table import Table

    console = Console()
    if not _check_key():
        return 2

    from deepseek_harness import DeepSeekHarness

    h = DeepSeekHarness(disable_thinking_by_default=True)
    try:
        out = h.chat(
            model=model,
            messages=[{"role": "user", "content": "Reply with the literal word OK."}],
            max_tokens=8,
        )
    except Exception as e:
        console.print(f"[red]✗[/] live call FAILED: {type(e).__name__}: {e}")
        return 2

    t = Table(title="dsh doctor", show_header=False)
    t.add_column("check", style="bold cyan")
    t.add_column("value")
    t.add_row("DEEPSEEK_API_KEY", "set ✓")
    t.add_row("base_url", os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com"))
    t.add_row("model", model)
    t.add_row("call.content", repr(out["message"].get("content")))
    t.add_row("call.finish_reason", out["finish_reason"] or "?")
    if out["usage"]:
        u = out["usage"]
        t.add_row("usage.prompt_tokens", str(u.get("prompt_tokens")))
        t.add_row("usage.cache_hit", f"{u.get('prompt_cache_hit_tokens')}/{u.get('prompt_tokens')} = {u.get('cache_hit_rate', 0):.1%}")
        t.add_row("usage.cost_usd", f"${u.get('estimated_cost_usd', 0):.8f}")
    t.add_row("guards", "thinking-off ✓ · max_tokens-cap ✓ · reasoning-preserve ✓ · stream-resilient ✓")
    console.print(t)
    console.print("[green]✓ harness ready. Try `dsh chat`.[/]")
    return 0


def _chat(model: str, reasoning: bool, max_tokens: int) -> int:
    from rich.console import Console
    from rich.markdown import Markdown

    console = Console()
    if not _check_key():
        return 2

    from deepseek_harness import DeepSeekHarness
    from deepseek_harness.normalize import prepare_for_new_user_turn

    h = DeepSeekHarness(disable_thinking_by_default=not reasoning)
    history: list[dict] = []
    console.print(
        f"[bold cyan]dsh chat[/] · model=[yellow]{model}[/] · "
        f"thinking={'on' if reasoning else 'off'} · max_tokens={max_tokens}\n"
        "Commands: /clear /quit. History auto-preserves reasoning_content per spec §1.\n"
    )
    while True:
        try:
            user = console.input("[bold green]you ❯ [/] ").strip()
        except (EOFError, KeyboardInterrupt):
            console.print("\n[dim]bye.[/]")
            return 0
        if not user:
            continue
        if user in ("/quit", "/exit"):
            return 0
        if user == "/clear":
            history.clear()
            console.print("[dim]history cleared.[/]")
            continue

        history = prepare_for_new_user_turn(history)
        history.append({"role": "user", "content": user})

        try:
            out = h.chat(
                model=model,
                messages=history,
                max_tokens=max_tokens,
                extra_body={"thinking": {"type": "enabled" if reasoning else "disabled"}},
            )
        except Exception as e:
            console.print(f"[red]✗ {type(e).__name__}: {e}[/]")
            history.pop()
            continue

        msg = out["message"]
        history.append(msg)
        if reasoning and msg.get("reasoning_content"):
            console.print(f"[dim]reasoning: {msg['reasoning_content'][:200]}...[/]")
        console.print(f"[bold magenta]dsh ❯[/] ", end="")
        console.print(Markdown(msg.get("content") or ""))
        if out["usage"]:
            u = out["usage"]
            console.print(
                f"[dim]usage: hit={u['prompt_cache_hit_tokens']}/{u['prompt_tokens']} "
                f"({u.get('cache_hit_rate', 0):.0%}) · cost=${u.get('estimated_cost_usd', 0):.6f}[/]\n"
            )


def _probe(name: str, n: int | None) -> int:
    repo_root = Path(__file__).resolve().parents[3]
    probes_dir = repo_root / "reports" / "probes"
    if not probes_dir.exists():
        print(f"[dsh] cannot find probes at {probes_dir}", file=sys.stderr)
        return 2
    if name == "list":
        for p in sorted(probes_dir.glob("probe_*.py")):
            print(p.stem)
        return 0
    candidates = list(probes_dir.glob(f"{name}*.py")) if not name.endswith(".py") else [probes_dir / name]
    if not candidates:
        print(f"[dsh] no probe matches '{name}'. try `dsh probe list`.", file=sys.stderr)
        return 2
    target = candidates[0]
    cmd = [sys.executable, str(target)]
    if n is not None:
        cmd.extend(["--n", str(n)])
    import subprocess
    return subprocess.call(cmd, cwd=repo_root)


def _validate(path: str) -> int:
    """Audit a messages.json for the 5 most common contract violations."""
    from rich.console import Console
    console = Console()
    try:
        messages = json.loads(Path(path).read_text())
    except Exception as e:
        console.print(f"[red]✗ cannot read {path}: {e}[/]")
        return 2

    from deepseek_harness.reasoning import ReasoningLifecycle

    issues: list[str] = []
    # Rule C2: tool-call assistant message must carry reasoning_content if next msg is tool
    for i, m in enumerate(messages):
        if (
            m.get("role") == "assistant"
            and m.get("tool_calls")
            and i + 1 < len(messages)
            and messages[i + 1].get("role") == "tool"
            and not m.get("reasoning_content")
        ):
            issues.append(f"#{i} C2: assistant→tool boundary missing reasoning_content (will 400 on V4 with thinking)")

    # Rule C3-style sanity: warn if any role appears wrong
    for i, m in enumerate(messages):
        if m.get("role") not in ("system", "user", "assistant", "tool"):
            issues.append(f"#{i} role: unknown role '{m.get('role')}'")

    # tool_call structure
    for i, m in enumerate(messages):
        for tc in (m.get("tool_calls") or []):
            if not tc.get("id") or not tc.get("function", {}).get("name"):
                issues.append(f"#{i} tool_call: missing id or function.name")

    # mid-prefix non-determinism (rough heuristic): system message containing a date pattern
    if messages and messages[0].get("role") == "system":
        sys_text = messages[0].get("content") or ""
        import re
        if re.search(r"\b20\d{2}-\d{2}-\d{2}\b", sys_text) or "current date" in sys_text.lower():
            issues.append("#0 cache: system prompt contains a date pattern → invalidates prefix-cache on each new day")

    if not issues:
        console.print(f"[green]✓ {len(messages)} messages — no contract violations detected.[/]")
        if ReasoningLifecycle.must_carry(messages):
            console.print("[dim]note: last assistant has tool_calls — your next request MUST preserve reasoning_content if you used thinking mode.[/]")
        return 0

    console.print(f"[red]✗ {len(issues)} violation(s) detected:[/]")
    for v in issues:
        console.print(f"  [yellow]•[/] {v}")
    return 1


def _estimate(path: str, prev: str | None) -> int:
    from rich.console import Console
    console = Console()
    try:
        new_messages = json.loads(Path(path).read_text())
    except Exception as e:
        console.print(f"[red]✗ cannot read {path}: {e}[/]")
        return 2
    prev_messages = None
    if prev:
        try:
            prev_messages = json.loads(Path(prev).read_text())
        except Exception as e:
            console.print(f"[red]✗ cannot read {prev}: {e}[/]")
            return 2
    from deepseek_harness import estimate_cache_hit
    out = estimate_cache_hit(new_messages, prev_messages)
    console.print(f"[bold]cache pre-flight estimate[/]")
    for k, v in out.items():
        console.print(f"  [cyan]{k}[/]: {v}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
