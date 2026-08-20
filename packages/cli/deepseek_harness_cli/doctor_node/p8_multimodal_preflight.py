"""P8 — llm-deepseek multimodal readiness preflight.

Discovery: rc.8 adds `feat(llm-deepseek): support multimodal requests`.
Path in `packages/llm/llm-deepseek/src/adapter.ts:235-250`:

    const hasImages = options.messages.some(m => contentHasImage(m.content))
    if (hasImages) {
      const model = connection.models.find(entry => entry.id === options.model)
      if (model?.inputModalities?.includes('image') !== true) {
        throw new LlmError('DeepSeek model "..." does not accept image input.',
          'UNSUPPORTED_CONTENT')
      }
      attachments = this.config.resolveAttachments?.()
      if (attachments === undefined) {
        throw new LlmError('DeepSeek image conversion requires the durable
          attachment service.', 'UNSUPPORTED_CONTENT')
      }
    }

The throw happens inside `adapter.stream()`, which agent-loop
(`packages/core/agent-loop/src/agent.ts:346`) calls **after** appending
the user turn to the session log. Consequence: the user's image-bearing
message is durable, the assistant response is `UNSUPPORTED_CONTENT`, and
the session re-loads next time showing an unanswered image. The user
resends. Repeated upload quota, and the harness never surfaces a
composition-level diagnostic pointing at the missing attachment service.

This probe scans reachable dsh Profile/composition files for:
  (a) any llm-deepseek row declaring an image-capable model
  (b) presence of an attachment provider (attachment-local etc.)
If (a) is present without (b) — or without inputModalities including
'image' on the referenced model — flag it.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

from . import Probe, Verdict


_PROFILE_ROOTS = [
    "~/.dsh/profiles",
    "~/.deepseek-harness/profiles",
    "~/.config/dsh/profiles",
    "./.dsh/profiles",
    "./dsh.yaml",
    "./composition.yaml",
]

_IMAGE_MODEL_HINTS = ("vl2", "vision", "vl-")  # deepseek vl2, vision variants


def _iter_config_files() -> list[Path]:
    seen: set[Path] = set()
    out: list[Path] = []
    for root in _PROFILE_ROOTS:
        p = Path(os.path.expanduser(root))
        if not p.exists():
            continue
        if p.is_file():
            out.append(p)
            continue
        for f in p.rglob("*.yaml"):
            rp = f.resolve()
            if rp in seen:
                continue
            seen.add(rp)
            out.append(f)
    return out


def _read(path: Path) -> str:
    try:
        return path.read_text(errors="replace")
    except OSError:
        return ""


def _run(_ctx: dict) -> Verdict:
    files = _iter_config_files()
    if not files:
        return Verdict(
            "skip",
            "no dsh profile or composition file found",
            detail=f"looked at: {', '.join(_PROFILE_ROOTS)}",
            evidence={"roots": _PROFILE_ROOTS},
        )

    has_llm_deepseek = False
    has_attachment_provider = False
    image_model_refs: list[tuple[str, str]] = []  # (file, model id)
    inputmodalities_seen: list[tuple[str, str]] = []

    for f in files:
        text = _read(f)
        if "@deepseek-ai/dsh-llm-deepseek" in text or "llm-deepseek" in text:
            has_llm_deepseek = True
        if "attachment-local" in text or "attachment/" in text:
            has_attachment_provider = True
        for m in re.finditer(r"\bid[:\s'\"]+([a-z0-9._-]*(?:vl2|vision|vl-)[a-z0-9._-]*)", text, re.IGNORECASE):
            image_model_refs.append((str(f), m.group(1)))
        # very loose: any yaml block with inputModalities mentioning image
        if re.search(r"inputModalities[^]]*image", text):
            inputmodalities_seen.append((str(f), "declared"))

    ev = {
        "files_scanned": [str(p) for p in files],
        "has_llm_deepseek": has_llm_deepseek,
        "has_attachment_provider": has_attachment_provider,
        "image_model_refs": image_model_refs,
        "input_modalities_declared": inputmodalities_seen,
    }

    if not has_llm_deepseek:
        return Verdict(
            "skip",
            "no llm-deepseek row in scanned profile/composition",
            evidence=ev,
        )
    if image_model_refs and not has_attachment_provider:
        return Verdict(
            "fail",
            f"llm-deepseek references an image-capable model ({image_model_refs[0][1]}) but no attachment provider is mounted",
            detail="At agent-loop.stream() time, the user's image-bearing turn "
                   "is already appended to the session log. adapter.ts:245 "
                   "then throws UNSUPPORTED_CONTENT. The session reloads with "
                   "an unanswered image; the user resends. Mount "
                   "@deepseek-ai/dsh-attachment-local in your composition, "
                   "or drop the vision model until you do.",
            evidence=ev,
        )
    if image_model_refs and not inputmodalities_seen:
        return Verdict(
            "warn",
            "image-capable model referenced but no `inputModalities: [image]` declaration found",
            detail="The adapter checks model.inputModalities.includes('image') "
                   "and throws UNSUPPORTED_CONTENT if not declared, even when "
                   "the model actually supports it. Add "
                   "`inputModalities: [text, image]` to the model config.",
            evidence=ev,
        )
    if has_attachment_provider:
        return Verdict(
            "pass",
            "llm-deepseek + attachment provider both mounted",
            evidence=ev,
        )
    return Verdict(
        "pass",
        "llm-deepseek row present; no image-capable model referenced (text-only path OK)",
        evidence=ev,
    )


PROBE = Probe(
    id="P8-multimodal-preflight",
    title="llm-deepseek multimodal composition is complete (image model + attachment service)",
    run=_run,
)
