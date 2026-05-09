#!/usr/bin/env bash
# Sweep the most informative probes against deepseek-v4-flash to compare with v4-pro.
# Output goes to findings/raw/probe_11_v4flash/<probe_name>/<utc>.jsonl via PROBE_FINDINGS_DIR.

set -e
cd "$(dirname "$0")/.."

export DEEPSEEK_MODEL=deepseek-v4-flash
export DEEPSEEK_REASONER_MODEL=deepseek-v4-flash
export PROBE_FINDINGS_DIR=findings/raw/probe_11_v4flash

mkdir -p "$PROBE_FINDINGS_DIR"

echo "============================================================"
echo "  V4-Flash sweep — model=$DEEPSEEK_MODEL"
echo "============================================================"

echo
echo ">>> probe_1 streaming basic"
python probes/probe_1_streaming_basic.py --n 3

echo
echo ">>> probe_2 reasoning lifecycle"
python probes/probe_2_reasoning_lifecycle.py --n 3

echo
echo ">>> probe_3 tool-call leakage thinking-OFF"
python probes/probe_3_tool_call_leakage.py --n 30

echo
echo ">>> probe_3b tool-call leakage thinking-ON"
python probes/probe_3b_tool_call_leakage_thinking.py --n 20

echo
echo ">>> probe_5 cache prefix sensitivity"
python probes/probe_5_cache_prefix_sensitivity.py --n 8

echo
echo ">>> probe_7 parallel tool streaming"
python probes/probe_7_tool_streaming_chunks.py --n 3

echo
echo ">>> probe_10 multiturn agentic loop"
python probes/probe_10_multiturn_agentic_loop.py

echo
echo "================ V4-Flash sweep DONE =================="
echo "raw → $PROBE_FINDINGS_DIR/"
