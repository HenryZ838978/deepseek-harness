"""P3 — 2573: dsh web silently spins on non-loopback Origin.

Mechanism (confirmed 2026-08-17, rc.6 through 0.1.1-rc.2):
  loopback Host    → GET / 200, /api/events.mux 101   (works)
  non-loopback Host → GET / 200, /api/events.mux 403  (front loaded, data 403)

Symptom: the frontend loads (HTML+JS come back 200), then every data-layer
call is 403'd. The page stays on "Select a workspace" with no console error.
It's the fence doing its job — but with no user-visible failure mode.

**Upstream state as of 0.1.2-alpha.1 (2026-08-27, tag cd5ef81): ADDRESSED.**
`client/connection/src/api-request-trust.ts` no longer compares the Host
header with a literal `host ===`. It now parses the authority through WHATWG
(`parseAuthority`), matches it against a configured `trustedHosts` allowlist
(`isTrustedAuthority`, port-less entries matching any port), rejects an
explicit `sec-fetch-site: cross-site`, and keeps the Origin fence. Config
entries are validated at load by `assertTrustedAuthority`, which refuses
non-canonical spellings (`0x7f.0.0.1`, percent-encoding, unbracketed IPv6,
zero-padded ports, `host/path`, `user@host`).

A second fence was added alongside it: `rpc-host.ts:requestRejection` returns
403 when the Host/Origin fence fails and **401** when the browser-session
cookie is absent or invalid (`client/connection/src/browser-auth.ts`, new in
this release: HMAC-SHA256 signed cookie, `timingSafeEqual` compare,
authority-bound payload, HttpOnly + SameSite=Strict, one-time launch token
exchanged at `/?token=` then 303-redirected to a clean `/`).

So on 0.1.2-alpha.1 an unauthenticated loopback data-layer call answers 401,
not 101/200/404. This probe therefore accepts 401 as a healthy loopback
baseline and reports which fence generation the server is running.

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

    # 0.1.2-alpha.1+ answers 401 to an unauthenticated data-layer call (the
    # browser-session cookie fence); rc.6..rc.2 answered 101/200/404 there.
    cookie_fence = loop_mux == 401
    ev = {
        "url": url,
        "home_status": home,
        "loopback_mux_status": loop_mux,
        "cross_origin_mux_status": evil_mux,
        "cookie_fence_detected": cookie_fence,
    }

    if home == 200 and cookie_fence and evil_mux in (401, 403):
        return Verdict(
            "pass",
            f"host+cookie fences active (mux loop=401, cross-origin={evil_mux})",
            detail="This server runs the 0.1.2-alpha.1-generation fence: the "
                   "Host header is normalized through WHATWG and matched "
                   "against a trustedHosts allowlist, and the data layer "
                   "additionally requires the signed browser-session cookie "
                   "(401 without it). The literal `host ===` compare this "
                   "probe was written for (#2573) is gone. Reach the UI "
                   "through the tokenized URL that `dsh web` prints — opening "
                   "a bare host:port now yields 401, by design.",
            evidence=ev,
        )
    if home == 200 and loop_mux in (101, 200, 404) and evil_mux == 403:
        return Verdict(
            "warn",
            f"legacy host-only fence (mux loop={loop_mux}, cross-origin={evil_mux})",
            detail="The Origin fence rejects cross-origin, but the loopback "
                   "data layer answers without any browser-session cookie — "
                   "this is the pre-0.1.2-alpha.1 fence. On that generation "
                   "the failure mode is silent: a user reaching the server "
                   "via a non-loopback hostname gets a loaded frontend whose "
                   "every data call 403s, with the page stuck on 'Select a "
                   "workspace' and nothing in the console. Upgrade to "
                   "0.1.2-alpha.1 or later.",
            evidence=ev,
        )
    if home == 200 and evil_mux not in (401, 403):
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
    title="dsh web fence: host normalization + browser-session cookie "
          "(#2573 — addressed upstream in 0.1.2-alpha.1)",
    run=_run,
)
