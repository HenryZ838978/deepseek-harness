"""Shared scaffolding for probes: env loading, raw dumps, fixtures."""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import pathlib
import sys
import time
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from typing import Any, Iterable

from dotenv import load_dotenv
from openai import OpenAI


# reports/probes/_common.py -> reports/  -> deepseek-harness/  (repo root)
REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
# Ensure the in-tree core lib is importable when probes are executed directly.
sys.path.insert(0, str(REPO_ROOT / "packages" / "core"))


def env_loaded() -> dict:
    load_dotenv(REPO_ROOT / ".env")
    return {
        "api_key": os.getenv("DEEPSEEK_API_KEY"),
        "base_url": os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
        "model": os.getenv("DEEPSEEK_MODEL", "deepseek-v4-pro"),
        "reasoner_model": os.getenv("DEEPSEEK_REASONER_MODEL", "deepseek-v4-pro"),
        "default_n": int(os.getenv("PROBE_DEFAULT_N", "10")),
        "repo_root": REPO_ROOT,
        "dump_raw": os.getenv("PROBE_DUMP_RAW", "1") not in ("0", "false", "False"),
        "findings_dir": REPO_ROOT / os.getenv("PROBE_FINDINGS_DIR", "reports/raw"),
    }


def make_client() -> OpenAI:
    cfg = env_loaded()
    if not cfg["api_key"]:
        print(
            "[probe] FATAL: DEEPSEEK_API_KEY not set. Copy .env.example to .env and fill it.",
            file=sys.stderr,
        )
        raise SystemExit(2)
    return OpenAI(api_key=cfg["api_key"], base_url=cfg["base_url"])


def make_client_beta() -> OpenAI:
    """Beta endpoint — required to trigger #1069 strict-mode bug."""
    cfg = env_loaded()
    if not cfg["api_key"]:
        raise SystemExit(2)
    base = cfg["base_url"].rstrip("/") + "/beta"
    return OpenAI(api_key=cfg["api_key"], base_url=base)


def parse_n_arg(default: int | None = None) -> int:
    cfg = env_loaded()
    p = argparse.ArgumentParser()
    p.add_argument("--n", type=int, default=default if default is not None else cfg["default_n"])
    p.add_argument("--no-dump", action="store_true")
    args, _ = p.parse_known_args()
    if args.no_dump:
        os.environ["PROBE_DUMP_RAW"] = "0"
    return args.n


# ----------------------------------------------------------------------------
# Raw dump helpers
# ----------------------------------------------------------------------------


@contextmanager
def raw_writer(probe_name: str):
    cfg = env_loaded()
    out_dir = cfg["findings_dir"] / probe_name
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = _dt.datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    out_path = out_dir / f"{ts}.jsonl"
    if cfg["dump_raw"]:
        fh = out_path.open("w")
    else:
        fh = None
    try:
        def write(row: dict):
            if fh is not None:
                fh.write(json.dumps(row, ensure_ascii=False, default=_json_fallback) + "\n")
                fh.flush()
        yield write, out_path
    finally:
        if fh is not None:
            fh.close()


def _json_fallback(obj: Any):
    if hasattr(obj, "model_dump"):
        return obj.model_dump()
    if hasattr(obj, "to_dict"):
        return obj.to_dict()
    if hasattr(obj, "__dict__"):
        return {k: v for k, v in obj.__dict__.items() if not k.startswith("_")}
    return repr(obj)


# ----------------------------------------------------------------------------
# Common fixtures used across probes
# ----------------------------------------------------------------------------


# Per probe-0 connectivity test: deepseek-v4-pro DEFAULTS to thinking-enabled,
# burning ~30 reasoning tokens on trivial prompts. Probes that don't need
# reasoning_content should pass `extra_body=THINKING_OFF` to keep tokens cheap
# and outputs deterministic.
THINKING_OFF = {"thinking": {"type": "disabled"}}
THINKING_ON = {"thinking": {"type": "enabled"}}


SYSTEM_PROMPT = (
    "You are a meticulous research assistant. When the user asks for a calculation "
    "or a lookup, ALWAYS call the appropriate tool exactly once. Never answer from memory. "
    "After the tool returns, summarise the result in one short sentence."
)


CALCULATOR_TOOL = {
    "type": "function",
    "function": {
        "name": "calculator",
        "description": "Evaluate a basic arithmetic expression and return the numeric result.",
        "parameters": {
            "type": "object",
            "properties": {
                "expression": {
                    "type": "string",
                    "description": "Arithmetic expression e.g. '2*(3+4)' — only +-*/() and digits.",
                }
            },
            "required": ["expression"],
        },
    },
}


SEARCH_TOOL = {
    "type": "function",
    "function": {
        "name": "web_search",
        "description": "Search the public web for a query and return top 3 result snippets.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query"},
                "lang": {"type": "string", "enum": ["en", "zh"], "description": "Language hint"},
            },
            "required": ["query"],
        },
    },
}


def calc_user_msg(seed: int = 0) -> dict:
    """A user prompt that DEFINITELY warrants a tool call (avoid trivial answers)."""
    return {
        "role": "user",
        "content": (
            f"What is the result of (97 + {17 + seed}) * 31 - {89 + seed * 2}? "
            "Use the calculator tool — do not estimate."
        ),
    }


def long_prefix_messages(token_target: int = 1500) -> list[dict]:
    """Construct a system+user pair whose token count comfortably exceeds 1024.

    The minimum effective prefix for DeepSeek caching is ~1024 tokens; we go to 1500
    by default so the cache definitely engages.
    """
    filler = (
        "Background context block (do not summarise — used for cache-prefix testing). "
        * 80
    )
    return [
        {"role": "system", "content": filler[: token_target * 4]},  # ~4 chars/token rough
        {"role": "user", "content": "Reply with the single word OK."},
    ]


# ----------------------------------------------------------------------------
# Trial record
# ----------------------------------------------------------------------------


@dataclass
class TrialRecord:
    probe: str
    trial_idx: int
    started_at: str = field(default_factory=lambda: _dt.datetime.utcnow().isoformat() + "Z")
    latency_ms: float | None = None
    status: str = "ok"
    finish_reason: str | None = None
    usage: dict | None = None
    salvage: dict | None = None
    error: dict | None = None
    notes: dict = field(default_factory=dict)
    raw_excerpt: dict | None = None

    def to_jsonable(self) -> dict:
        return asdict(self)


@contextmanager
def time_trial(rec: TrialRecord):
    t0 = time.perf_counter()
    try:
        yield
    except Exception as e:  # noqa: BLE001
        rec.status = "error"
        rec.error = {"type": type(e).__name__, "message": str(e)}
    finally:
        rec.latency_ms = round((time.perf_counter() - t0) * 1000, 2)


def banner(probe_name: str, n: int):
    cfg = env_loaded()
    print("=" * 72)
    print(f"[{probe_name}]  n={n}  base_url={cfg['base_url']}  model={cfg['model']}")
    print("=" * 72)


def summarise_inplace(rows: Iterable[dict]):
    rows = list(rows)
    n = len(rows)
    ok = sum(1 for r in rows if r.get("status") == "ok")
    err = n - ok
    salvages = sum(1 for r in rows if r.get("salvage"))
    print(f"\n[summary] trials={n}  ok={ok}  err={err}  salvages={salvages}")
    if salvages:
        print(f"[summary] tool-call leakage / salvage rate: {salvages/n:.1%}")
