"""P6 — subagent env-scrub false positive.

Discovery: rc.8 adds `feat(subagent): make Claude Code / Codex provider
directly installable`. The env forwarded to subagent children first passes
through `scrubbedParentEnv()` in `@deepseek-ai/dsh-subprocess`
(`packages/subprocess/subprocess/src/index.ts:60`), which strips *any*
variable whose name matches:

    SENSITIVE_ENV_PATTERN = /KEY|PASSWORD|SECRET|TOKEN/i

That regex is a substring match, so it also silently strips user-defined
vars whose names contain those substrings — e.g. `MY_SERVICE_KEY`,
`AWS_ACCESS_KEY_ID`, `GITHUB_TOKEN`, `MY_API_TOKEN`. No warning; the child
just sees a hole where the var used to be.

This probe surveys the current environment, flags any names that will be
scrubbed, and lists them. It does not spawn anything — the check is
against a re-implemented regex faithful to the compiled artifact.
"""
from __future__ import annotations

import os
import re

from . import Probe, Verdict


_SCRUB_RE = re.compile(r"KEY|PASSWORD|SECRET|TOKEN", re.IGNORECASE)

# Well-known credentials that SHOULD be scrubbed; not user surprises.
_EXPECTED = {
    "DEEPSEEK_API_KEY", "ANTHROPIC_API_KEY", "OPENAI_API_KEY",
    "GITHUB_TOKEN", "GH_TOKEN", "NPM_TOKEN", "PYPI_TOKEN",
    "TWINE_PASSWORD", "AWS_SESSION_TOKEN",
    # Common CI / auth handles that are expected to be treated as credentials
    "HUGGINGFACE_TOKEN", "HF_TOKEN", "CODEX_API_KEY", "CLAUDE_API_KEY",
}


def _run(ctx: dict) -> Verdict:
    env = ctx["env"]
    all_scrubbed = [k for k in env if _SCRUB_RE.search(k)]
    surprises = sorted(k for k in all_scrubbed if k.upper() not in _EXPECTED)

    ev = {
        "regex": r"/KEY|PASSWORD|SECRET|TOKEN/i (substring match)",
        "regex_source": (
            "packages/subprocess/subprocess/src/index.ts:44 "
            "(SENSITIVE_ENV_PATTERN) — reachable via subagent-claude-code / "
            "subagent-codex spawn paths"
        ),
        "total_scrubbed": len(all_scrubbed),
        "expected_credential_scrubs": sorted(
            k for k in all_scrubbed if k.upper() in _EXPECTED
        ),
        "surprising_scrubs": surprises,
    }

    if not surprises:
        return Verdict(
            "pass",
            f"nothing surprising will be scrubbed "
            f"({len(all_scrubbed)} vars match, all known credentials)",
            evidence=ev,
        )
    return Verdict(
        "warn",
        f"{len(surprises)} user-defined env var(s) will be silently stripped from subagent children",
        detail="These names match the subprocess scrub regex, but are not "
               "canonical credential handles. Subagent CLIs (Claude Code / "
               "Codex / any that go through @deepseek-ai/dsh-subprocess) "
               "will not see them. Rename to avoid the substrings "
               "KEY/PASSWORD/SECRET/TOKEN, or forward them explicitly in the "
               "subagent Profile's `env:` block. Names: " + ", ".join(surprises),
        evidence=ev,
    )


PROBE = Probe(
    id="P6-subagent-env-scrub",
    title="user env vars containing KEY/TOKEN/... are not silently stripped from subagent children",
    run=_run,
)
