"""One function, complete(system, user) -> text, backed by the Anthropic API or the Claude Code CLI.

ANTHROPIC_API_KEY set: Messages API via the `anthropic` SDK. Otherwise: `claude -p` in headless mode with
no tools and no project settings, so the model sees exactly the prompt given and nothing else.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

MODEL = os.environ.get("EVAL_MODEL", "claude-sonnet-5-5")


def _claude_exe() -> str:
    exe = shutil.which("claude")
    if exe and exe.lower().endswith((".cmd", ".ps1")):   # Windows npm shim: call the binary, not cmd.exe
        native = Path(exe).parent / "node_modules" / "@anthropic-ai" / "claude-code" / "bin" / "claude.exe"
        exe = str(native) if native.exists() else exe
    if not exe:
        raise RuntimeError("set ANTHROPIC_API_KEY or install the Claude Code CLI")
    return exe


def complete(system: str, user: str, model: str = MODEL) -> dict:
    t0 = time.time()
    if os.environ.get("ANTHROPIC_API_KEY"):
        import anthropic  # optional dependency

        client = anthropic.Anthropic()
        msg = client.messages.create(model=model, max_tokens=2000, system=system,
                                     messages=[{"role": "user", "content": user}])
        text = "".join(b.text for b in msg.content if b.type == "text")
        return {"text": text, "ms": int((time.time() - t0) * 1000), "backend": "api", "model": model}

    exe = _claude_exe()
    with tempfile.TemporaryDirectory() as cwd:   # empty folder: no CLAUDE.md, no project context
        sp = Path(cwd) / "system.txt"
        sp.write_text(system, encoding="utf-8")
        # prompt on stdin and system prompt from a file: long schemas exceed Windows command line limits
        r = subprocess.run([exe, "-p", "--model", model, "--output-format", "json", "--tools", "",
                            "--system-prompt-file", str(sp), "--no-session-persistence", "--setting-sources", ""],
                           input=user, capture_output=True, text=True, encoding="utf-8", timeout=600, cwd=cwd)
    if r.returncode:
        raise RuntimeError(f"claude CLI failed: {r.stderr[:500]}")
    d = json.loads(r.stdout)
    if isinstance(d, list):   # some CLI versions return the full message list; the result is the last entry
        d = next(x for x in reversed(d) if isinstance(x, dict) and x.get("type") == "result")
    if d.get("is_error"):
        raise RuntimeError(f"claude CLI error: {str(d.get('result'))[:300]}")
    return {"text": d.get("result", ""), "ms": int((time.time() - t0) * 1000), "backend": "claude-cli",
            "model": next(iter(d.get("modelUsage", {})), model), "cost_usd": d.get("total_cost_usd")}
