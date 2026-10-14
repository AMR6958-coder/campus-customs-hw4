"""Append-only audit trail of agent loop activity.

Every run of either PydanticAI agent (the shopping assistant in agent.py and
the inventory assistant in inventory_agent.py) appends one JSON record to
``output/audit_trail.json``: who asked, what was asked, every model step and
tool call in the order it happened, retries raised by the output validator,
token usage, timing, and the final reply or the error. Records are only ever
added: the file is opened in append mode and nothing in the code base
rewrites, edits, or deletes it.

Format: JSON Lines, one complete JSON object per line. That is the only JSON
layout that can be appended to safely (a single array would have to be
rewritten on every run). Read it with ``read_trail()`` or from the command
line::

    cd backend && .venv\\Scripts\\python audit_trail.py --tail 5

The audit trail is local to this machine and includes the shopper's message
and email, so treat it like the chat history table.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel
from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    RetryPromptPart,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)

from db import PROJECT_ROOT

logger = logging.getLogger("campus_customs.audit")

TRAIL_PATH = Path(os.getenv("AUDIT_TRAIL_PATH") or PROJECT_ROOT / "output" / "audit_trail.json")
PREVIEW_CHARS = 400  # tool results are previewed, not copied in full; the database is the source of truth
FINAL_RESULT_TOOL = "final_result"  # the tool PydanticAI uses to deliver structured output

_lock = threading.Lock()


# --------------------------------------------------------------------------
# Small helpers
# --------------------------------------------------------------------------


def new_run_id() -> str:
    return uuid.uuid4().hex[:12]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _jsonable(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    return value


def _preview(value: Any) -> tuple[str, int]:
    """A short JSON preview of a tool result plus its full length in characters."""
    text = value if isinstance(value, str) else json.dumps(_jsonable(value), ensure_ascii=False, default=str)
    if len(text) > PREVIEW_CHARS:
        return text[:PREVIEW_CHARS] + "…", len(text)
    return text, len(text)


def _product_ids(value: Any) -> list[str] | None:
    """Product ids inside a tool result, when it carries any (search results, details, stock)."""
    results = getattr(value, "results", None)
    if isinstance(results, list):
        return [getattr(r, "product_id", None) for r in results if getattr(r, "product_id", None)]
    product_id = getattr(value, "product_id", None)
    return [product_id] if isinstance(product_id, str) else None


# --------------------------------------------------------------------------
# Reading the loop out of the run's messages
# --------------------------------------------------------------------------


def summarize_steps(messages: list[ModelMessage]) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Turn the messages exchanged during one run into an ordered list of steps.

    Step kinds: user_prompt, model_text, tool_call (with args and a result
    preview once the tool returns), final_output (the structured reply the
    model proposed), validator_retry (the output validator rejected that
    reply), tool_retry (a tool asked the model to try again).
    """
    steps: list[dict[str, Any]] = []
    pending: dict[str, dict[str, Any]] = {}
    counts = {"model_requests": 0, "tool_calls": 0, "retries": 0}

    for msg in messages:
        if isinstance(msg, ModelRequest):
            for part in msg.parts:
                if isinstance(part, UserPromptPart):
                    text = part.content if isinstance(part.content, str) else json.dumps(_jsonable(part.content), default=str)
                    steps.append({"kind": "user_prompt", "chars": len(text), "preview": text[:PREVIEW_CHARS]})
                elif isinstance(part, ToolReturnPart):
                    step = pending.pop(part.tool_call_id, None)
                    if step is None:
                        step = {"kind": "tool_return", "tool": part.tool_name}
                        steps.append(step)
                    if part.tool_name == FINAL_RESULT_TOOL:
                        step["accepted"] = True
                    else:
                        preview, chars = _preview(part.content)
                        step["result_type"] = type(part.content).__name__
                        step["result_chars"] = chars
                        step["result_preview"] = preview
                        ids = _product_ids(part.content)
                        if ids:
                            step["product_ids"] = ids
                elif isinstance(part, RetryPromptPart):
                    counts["retries"] += 1
                    reason = part.content if isinstance(part.content, str) else json.dumps(_jsonable(part.content), default=str)
                    rejected = pending.pop(part.tool_call_id, None) if part.tool_call_id else None
                    if rejected is not None:
                        rejected["accepted"] = False
                    kind = "validator_retry" if part.tool_name == FINAL_RESULT_TOOL else ("tool_retry" if part.tool_name else "retry")
                    steps.append({"kind": kind, "tool": part.tool_name, "reason": reason[:PREVIEW_CHARS]})
        elif isinstance(msg, ModelResponse):
            counts["model_requests"] += 1
            for part in msg.parts:
                if isinstance(part, TextPart):
                    if part.content.strip():
                        steps.append({"kind": "model_text", "chars": len(part.content), "preview": part.content[:PREVIEW_CHARS]})
                elif isinstance(part, ToolCallPart):
                    try:
                        args = part.args_as_dict()
                    except Exception:  # malformed JSON from the model; keep the raw text
                        args = {"_raw": str(part.args)[:PREVIEW_CHARS]}
                    if part.tool_name == FINAL_RESULT_TOOL:
                        step = {"kind": "final_output", "proposed": args}
                    else:
                        counts["tool_calls"] += 1
                        step = {"kind": "tool_call", "tool": part.tool_name, "args": args}
                    steps.append(step)
                    pending[part.tool_call_id] = step

    for n, step in enumerate(steps, 1):
        step["n"] = n
        # put "n" first for readability
        steps[n - 1] = {"n": n, **{k: v for k, v in step.items() if k != "n"}}
    return steps, counts


def _usage_dict(usage: Any) -> dict[str, Any] | None:
    if usage is None:
        return None
    if callable(usage):  # older PydanticAI versions expose result.usage() as a method
        usage = usage()
    out = {}
    for key in ("requests", "tool_calls", "input_tokens", "output_tokens", "cache_read_tokens"):
        value = getattr(usage, key, None)
        if value:
            out[key] = value
    return out or None


# --------------------------------------------------------------------------
# Writing
# --------------------------------------------------------------------------


def build_record(
    *,
    agent: str,
    run_id: str,
    started_at: str,
    duration_ms: int,
    model: str | None,
    prompt_file: Path | None,
    actor: dict[str, Any],
    request: dict[str, Any],
    messages: list[ModelMessage],
    output: dict[str, Any] | None = None,
    usage: Any = None,
    error: BaseException | None = None,
    mode: str = "agent",
) -> dict[str, Any]:
    steps, counts = summarize_steps(messages)
    record: dict[str, Any] = {
        "ts": started_at,
        "agent": agent,
        "run_id": run_id,
        "mode": mode,
        "outcome": "error" if error is not None else "ok",
        "duration_ms": duration_ms,
        "model": model,
        "prompt": None,
        "actor": actor,
        "request": request,
        "counts": counts,
        "usage": _usage_dict(usage),
        "steps": steps,
        "output": output,
        "error": None if error is None else {"type": type(error).__name__, "message": str(error)[:PREVIEW_CHARS]},
    }
    if prompt_file is not None and prompt_file.exists():
        modified = datetime.fromtimestamp(prompt_file.stat().st_mtime, tz=timezone.utc)
        record["prompt"] = {"file": prompt_file.name, "modified": modified.isoformat(timespec="seconds").replace("+00:00", "Z")}
    return record


def record(**kwargs: Any) -> None:
    """Build a record from build_record's arguments and append it. Never raises."""
    try:
        append(build_record(**kwargs))
    except Exception:  # pragma: no cover - defensive
        logger.exception("Could not build an audit record")


def append(record: dict[str, Any]) -> None:
    """Append one record as a single line. Never raises: an audit problem must not break a chat."""
    try:
        line = json.dumps(record, ensure_ascii=False, default=str)
        with _lock:
            TRAIL_PATH.parent.mkdir(parents=True, exist_ok=True)
            with TRAIL_PATH.open("a", encoding="utf-8") as f:
                f.write(line + "\n")
    except Exception:  # pragma: no cover - defensive
        logger.exception("Could not append to the audit trail")


# --------------------------------------------------------------------------
# Reading
# --------------------------------------------------------------------------


def read_trail(limit: int | None = None) -> list[dict[str, Any]]:
    """All records in order (or the last ``limit``). Corrupt lines are skipped, not raised."""
    if not TRAIL_PATH.exists():
        return []
    records: list[dict[str, Any]] = []
    with TRAIL_PATH.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                logger.warning("Skipping a corrupt audit line")
    return records[-limit:] if limit else records


def describe(record: dict[str, Any]) -> str:
    """One readable paragraph per record, for the command line."""
    actor = record.get("actor") or {}
    who = actor.get("email") or ("guest" if actor.get("guest") else actor.get("role", "?"))
    req = record.get("request") or {}
    counts = record.get("counts") or {}
    head = (f"{record.get('ts')}  {record.get('agent')}  run {record.get('run_id')}  {record.get('outcome')}  "
            f"{record.get('duration_ms', 0) / 1000:.1f}s  mode={record.get('mode')}  who={who}")
    lines = [head]
    if "message" in req:
        lines.append(f"  asked: {req['message'][:120]!r}" + (f"  (page: {req['page_product_id']})" if req.get("page_product_id") else ""))
    for step in record.get("steps", []):
        kind = step["kind"]
        if kind == "tool_call":
            result = f" -> {step.get('result_type', '?')}"
            if step.get("product_ids"):
                result += f" ({len(step['product_ids'])} product ids)"
            lines.append(f"  {step['n']:>2}. {step['tool']}({json.dumps(step.get('args', {}), ensure_ascii=False)}){result}")
        elif kind == "final_output":
            lines.append(f"  {step['n']:>2}. final output proposed" + (" (rejected)" if step.get("accepted") is False else ""))
        elif kind in ("validator_retry", "tool_retry", "retry"):
            lines.append(f"  {step['n']:>2}. {kind}: {step.get('reason', '')[:140]}")
    lines.append(f"  model requests {counts.get('model_requests', 0)}, tool calls {counts.get('tool_calls', 0)}, "
                 f"retries {counts.get('retries', 0)}" + (f", tokens in/out {record['usage'].get('input_tokens', '?')}/{record['usage'].get('output_tokens', '?')}" if record.get("usage") else ""))
    out = record.get("output") or {}
    if "reply" in out:
        lines.append(f"  reply: {out['reply'][:160]!r}" + (f"  products: {out.get('product_ids')}" if out.get("product_ids") else ""))
    elif "summary" in out:
        lines.append(f"  summary: {out['summary'][:160]!r}")
    if record.get("error"):
        lines.append(f"  error: {record['error']['type']}: {record['error']['message'][:160]}")
    return "\n".join(lines)


def main(argv: list[str]) -> int:
    limit = 10
    if "--tail" in argv:
        limit = int(argv[argv.index("--tail") + 1])
    records = read_trail(limit=limit)
    total = len(read_trail())
    print(f"{TRAIL_PATH}: {total} records (showing last {len(records)})\n")
    for record in records:
        print(describe(record))
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
