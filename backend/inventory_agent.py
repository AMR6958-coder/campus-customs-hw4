"""The inventory assistant: a second PydanticAI agent that reviews stock and
shopper activity and sends notes to the store owner.

The rules and numbers come from inventory.py (plain Python). This agent's job
is judgment and wording: deciding which flagged products get which note and
writing it clearly. The send_owner_note tool enforces the guardrails: only
flagged products, no duplicate open notes, real product ids.

Run a review from the API (POST /api/owner/review), or from the command line::

    cd backend && .venv\\Scripts\\python inventory_agent.py
"""

from __future__ import annotations

import asyncio
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic_ai import Agent, RunContext, capture_run_messages

import audit_trail
import inventory
from agent import MODEL_NAME, AgentNotConfigured, get_model
from db import DB_PATH
from models import InventoryReport, NoteKind, OwnerNote, ReviewOutput, ReviewResult

BACKEND_DIR = Path(__file__).resolve().parent
PROMPT_PATH = BACKEND_DIR / "prompts" / "inventory_prompt.md"

_prompt_cache: tuple[float, str] | None = None


def load_prompt() -> str:
    """Return prompts/inventory_prompt.md, re-reading it whenever the file changes."""
    global _prompt_cache
    modified = PROMPT_PATH.stat().st_mtime
    if _prompt_cache is None or _prompt_cache[0] != modified:
        _prompt_cache = (modified, PROMPT_PATH.read_text(encoding="utf-8"))
    return _prompt_cache[1]


@dataclass
class InventoryDeps:
    conn: sqlite3.Connection
    report: InventoryReport
    created: list[OwnerNote] = field(default_factory=list)


agent: Agent[InventoryDeps, ReviewOutput] = Agent(
    name="inventory_assistant",
    deps_type=InventoryDeps,
    output_type=ReviewOutput,
    instructions=load_prompt,
    retries=2,
)


@agent.tool(sequential=True)
def get_inventory_report(ctx: RunContext[InventoryDeps]) -> InventoryReport:
    """The current report: low-stock sizes, per-product engagement, and which
    products are flagged for a reorder note or a do-not-reorder note."""
    return ctx.deps.report


@agent.tool(sequential=True)
def get_open_owner_notes(ctx: RunContext[InventoryDeps]) -> list[OwnerNote]:
    """Notes already sent to the owner that are still open. Do not send another
    note of the same kind for the same product."""
    return inventory.list_notes(ctx.deps.conn, include_resolved=False)


@agent.tool(sequential=True)
def send_owner_note(
    ctx: RunContext[InventoryDeps],
    kind: NoteKind,
    product_id: str,
    message: str,
    size: str | None = None,
) -> str:
    """Send one note to the store owner. kind is "reorder" or "do_not_reorder".
    size is optional: for reorder notes, the low sizes as "XS, XL". Refuses
    products that are not flagged for that kind, and duplicates of open notes."""
    report = ctx.deps.report
    flagged = report.flagged_reorder_products if kind == "reorder" else report.flagged_do_not_reorder_products
    if product_id not in flagged:
        return f"Refused: {product_id} is not flagged for a {kind} note in this report."
    if inventory.has_open_note(ctx.deps.conn, kind, product_id):
        return f"Refused: an open {kind} note already exists for {product_id}."
    if len(message.strip()) < 20:
        return "Refused: the message is too short to be useful. Include the product name and the numbers."
    note = inventory.create_note(ctx.deps.conn, kind, product_id, message, size)
    ctx.deps.created.append(note)
    return f"Sent note #{note.id} ({kind}) for {note.product_name}."


# --------------------------------------------------------------------------
# Running a review
# --------------------------------------------------------------------------


def _template_review(deps: InventoryDeps) -> ReviewResult:
    """Fallback without a model: the same rules, template wording."""
    report = deps.report
    both = set(report.reorder_queue) & set(report.do_not_reorder_queue)
    skipped = 0

    for pid in report.do_not_reorder_queue:
        if inventory.has_open_note(deps.conn, "do_not_reorder", pid):
            skipped += 1
            continue
        line = next(e for e in report.engagement if e.product_id == pid)
        lows = [l for l in report.low_stock if l.product_id == pid]
        extra = ""
        if lows:
            extra = " It is also low in " + ", ".join(f"{l.size} ({l.quantity} left)" for l in lows) + ", but hold off restocking for now."
        msg = (
            f"{line.name} had {line.views} views and {line.clicks} card clicks in the last "
            f"{report.window_days} days with no add-to-carts. Recommend not reordering yet; "
            f"try better placement or a markdown and watch it for another week.{extra}"
        )
        deps.created.append(inventory.create_note(deps.conn, "do_not_reorder", pid, msg))

    for pid in report.reorder_queue:
        if pid in both or inventory.has_open_note(deps.conn, "reorder", pid):
            skipped += 1
            continue
        lows = [l for l in report.low_stock if l.product_id == pid]
        sizes = ", ".join(l.size for l in lows)
        detail = "; ".join(f"{l.size} has {l.quantity} left ({l.percent_of_par:g}% of par)" for l in lows)
        suggest = ", ".join(f"{l.size} +{report.par_level - l.quantity}" for l in lows)
        msg = (
            f"{lows[0].name} needs a reorder: {detail}. Suggested order to return to par: {suggest}."
        )
        deps.created.append(inventory.create_note(deps.conn, "reorder", pid, msg, sizes))

    kinds = {k: sum(1 for n in deps.created if n.kind == k) for k in ("reorder", "do_not_reorder")}
    summary = (
        f"Template review (no LLM key configured): sent {kinds['reorder']} reorder and "
        f"{kinds['do_not_reorder']} do-not-reorder notes; skipped {skipped}. "
        f"Backlog for next time: {report.reorder_backlog} reorder, {report.do_not_reorder_backlog} do-not-reorder."
    )
    return ReviewResult(notes_created=deps.created, summary=summary, used_agent=False)


def _audit_request(report: InventoryReport) -> dict[str, Any]:
    return {
        "flagged_reorder_products": len(report.flagged_reorder_products),
        "flagged_do_not_reorder_products": len(report.flagged_do_not_reorder_products),
        "reorder_queue": list(report.reorder_queue),
        "do_not_reorder_queue": list(report.do_not_reorder_queue),
    }


def _audit_output(result: ReviewResult) -> dict[str, Any]:
    return {
        "summary": result.summary,
        "notes_created": [{"id": n.id, "kind": n.kind, "product_id": n.product_id, "size": n.size} for n in result.notes_created],
    }


async def run_review(conn: sqlite3.Connection) -> ReviewResult:
    """Build the report and let the inventory agent send the owner's notes.

    Every review appends one record to output/audit_trail.json, whether the
    agent ran (mode "agent"), the plain-Python fallback wrote the notes
    (mode "template"), or there was nothing to do (mode "nothing_to_do").
    """
    report = inventory.build_report(conn)
    deps = InventoryDeps(conn=conn, report=report)
    run_id, started_at, clock = audit_trail.new_run_id(), audit_trail.utc_now(), time.perf_counter()
    audit = dict(agent="inventory_assistant", run_id=run_id, started_at=started_at, model=MODEL_NAME,
                 prompt_file=PROMPT_PATH, actor={"role": "store_owner"}, request=_audit_request(report))

    def elapsed() -> int:
        return int((time.perf_counter() - clock) * 1000)

    if not report.reorder_queue and not report.do_not_reorder_queue:
        if report.flagged_reorder_products or report.flagged_do_not_reorder_products:
            summary = "Every flagged product already has an open note. Resolve notes as you act on them and run again."
        else:
            summary = (
                "Nothing to flag: no size is at or below the reorder line and no product is being "
                "viewed without being added to a cart."
            )
        result = ReviewResult(notes_created=[], summary=summary, used_agent=False)
        audit_trail.record(**audit, duration_ms=elapsed(), messages=[], output=_audit_output(result), mode="nothing_to_do")
        return result

    try:
        model = get_model()
    except AgentNotConfigured:
        result = _template_review(deps)
        audit_trail.record(**audit, duration_ms=elapsed(), messages=[], output=_audit_output(result), mode="template")
        return result

    with capture_run_messages() as messages:
        try:
            run = await agent.run(
                "Review the current inventory report and send the owner every note the rules call for.",
                deps=deps,
                model=model,
            )
        except Exception as exc:
            audit_trail.record(**audit, duration_ms=elapsed(), messages=list(messages), error=exc)
            raise
    result = ReviewResult(notes_created=deps.created, summary=run.output.summary, used_agent=True)
    audit_trail.record(**audit, duration_ms=elapsed(), messages=run.new_messages(), usage=run.usage, output=_audit_output(result))
    return result


# --------------------------------------------------------------------------
# Command line
# --------------------------------------------------------------------------


async def _cli() -> None:
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    inventory.ensure_schema(conn)
    result = await run_review(conn)
    print(result.summary)
    for note in result.notes_created:
        print(f"\n[{note.kind}] {note.product_name}" + (f" ({note.size})" if note.size else ""))
        print(note.message)
    conn.close()


if __name__ == "__main__":
    asyncio.run(_cli())
