"""P3 — 2573: dsh web silently spins on non-loopback Origin.

Mechanism (confirmed 2026-08-17):
  loopback Host    → GET / 200, /api/events.mux 101   (works)
  non-loopback Host → GET / 200, /api/events.mux 403  (front loaded, data 403)

Symptom: the frontend loads (HTML+JS come back 200), then every data-layer
call is 403'd. The page stays on "Select a workspace" with no console error.
It's the fence doing its job — but with no user-visible failure mode.

This probe hits the running `dsh web` on --url, first with the natural Host,
then with an Origin the fence should reject, and diffs the outcomes.
"""
from __future__ import annotations

import socket
import urllib.error
import urllib.parse
import urllib.request

from . import Probe, Verdict


def _get(url: str, headers: dict) -> int:
    req = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=3) as resp:
            return resp.status
    except urllib.error.HTTPError as e:
        return e.code
    except (urllib.error.URLError, socket.timeout, ConnectionError):
        return 0


def _run(ctx: dict) -> Verdict:
    url = ctx["dsh_url"].rstrip("/")
    parsed = urllib.parse.urlparse(url)

    # First: is the server up at all?
    home = _get(url + "/", {})
    if home == 0:
        return Verdict(
            "skip",
            f"no server responding at {url}",
            detail="Start `dsh web` first, or pass --url. This probe is a "
                   "live check.",
            evidence={"url": url, "home_status": 0},
        )

    # Loopback baseline
    loop_mux = _get(url + "/api/events.mux", {})

    # Cross-origin probe: same URL but Origin lies.
    evil_mux = _get(url + "/api/events.mux", {"Origin": "https://evil.example"})

    ev = {
        "url": url,
        "home_status": home,
        "loopback_mux_status": loop_mux,
        "cross_origin_mux_status": evil_mux,
    }

    if home == 200 and loop_mux in (101, 200, 404) and evil_mux == 403:
        return Verdict(
            "pass",
            f"fence active (mux loop={loop_mux}, cross-origin={evil_mux})",
            detail="Serve health is correct. Note the fence is silent — if a "
                   "user reports the page hangs on 'Select a workspace', check "
                   "whether they hit the server via a non-loopback hostname.",
            evidence=ev,
        )
    if home == 200 and evil_mux != 403:
        return Verdict(
            "fail",
            f"fence NOT active for cross-origin (mux={evil_mux})",
            detail="Data layer accepts a lying Origin — this is a security "
                   "regression.",
            evidence=ev,
        )
    return Verdict(
        "warn",
        f"unexpected status combo (home={home}, mux={loop_mux}, cross={evil_mux})",
        evidence=ev,
    )


PROBE = Probe(
    id="P3-serve",
    title="dsh web fence: cross-origin data path is rejected (#2573)",
    run=_run,
)
