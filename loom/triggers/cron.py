"""Morning digest generator — builds and renders a summary of recent instances."""

from __future__ import annotations

from typing import Optional

OVER_BUDGET_THRESHOLD = 5.0


def build_digest(store, since: str | None = None) -> dict:
    """Query instances and return a digest dict.

    Parameters
    ----------
    store : Store
        An open Store instance.
    since : str | None
        Optional ISO datetime string; only instances with created_at >= since
        are included.  If None, all instances are included.

    Returns
    -------
    dict with keys: total, by_status, total_cost_usd, over_budget, instances.
    """
    if since is not None:
        rows = store.conn.execute(
            "SELECT id, title, status, cost_usd, template_id FROM instances "
            "WHERE created_at >= ? ORDER BY created_at",
            (since,),
        ).fetchall()
    else:
        rows = store.conn.execute(
            "SELECT id, title, status, cost_usd, template_id FROM instances "
            "ORDER BY created_at"
        ).fetchall()

    instances = [
        {
            "id": r["id"],
            "title": r["title"],
            "status": r["status"],
            "cost_usd": r["cost_usd"],
            "template_id": r["template_id"],
        }
        for r in rows
    ]

    by_status: dict[str, int] = {}
    total_cost = 0.0
    over_budget = []

    for inst in instances:
        st = inst["status"]
        by_status[st] = by_status.get(st, 0) + 1
        total_cost += inst["cost_usd"]
        if inst["cost_usd"] >= OVER_BUDGET_THRESHOLD:
            over_budget.append(inst)

    return {
        "total": len(instances),
        "by_status": by_status,
        "total_cost_usd": total_cost,
        "over_budget": over_budget,
        "instances": instances,
    }


def render_digest(digest: dict) -> str:
    """Render a digest dict into a human-readable plain-text report.

    Over-budget instances are marked with ``**RED (OVER BUDGET)`` so the
    highlight is visible and testable.
    """
    lines: list[str] = []
    lines.append("# Morning Digest")
    lines.append("")
    lines.append(f"**Total instances:** {digest['total']}")
    lines.append(f"**Total cost:** ${digest['total_cost_usd']:.2f}")
    lines.append("")

    # By-status summary
    lines.append("## Status Summary")
    for status, count in sorted(digest["by_status"].items()):
        lines.append(f"- {status}: {count}")
    lines.append("")

    # Instance list
    lines.append("## Instances")
    over_budget_ids = {inst["id"] for inst in digest["over_budget"]}
    for inst in digest["instances"]:
        marker = " **RED (OVER BUDGET)**" if inst["id"] in over_budget_ids else ""
        lines.append(
            f"- [{inst['id']}] {inst['title']} "
            f"(status={inst['status']}, cost=${inst['cost_usd']:.2f}){marker}"
        )
    lines.append("")

    return "\n".join(lines)
