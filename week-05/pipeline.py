"""Fixed pipeline: prepares Brookfield's response to one supplier email, always in the same steps.

  1. Supply analyst (agent with the supply MCP tools) writes a brief; code checks it against the tool results.
  2. Supplier writer drafts a reply (or says NO REPLY NEEDED); the reviewer checks it.
  3. If the supplier offers options, stop here: customer notices wait until a person chooses.
     Otherwise, the customer writer drafts one notice per order at risk; the reviewer checks each.
  4. A summary for the purchasing manager is written by code from the results above.

Nothing is sent. Drafts go to week-05/drafts/<email>/pipeline/, the run log to week-05/runs/.

Usage (from the top of the repository):
    .venv\\Scripts\\python.exe week-05\\pipeline.py --email week-05\\brookfield-bikes\\supplier-emails\\01-northgate-controller-delay.eml
    .venv\\Scripts\\python.exe week-05\\pipeline.py --all
"""

import shutil

from common import DRAFTS_DIR, MODEL, REPO_ROOT, Usage, parse_email, run_cli
import specialists as sp

COORDINATOR = "pipeline"


async def run_one(client, email_path):
    email = parse_email(email_path)
    usage = Usage()
    out_dir = DRAFTS_DIR / email["stem"] / COORDINATOR
    shutil.rmtree(out_dir, ignore_errors=True)  # this folder holds only this script's previous output

    print(f"Email: {email['file']}")
    print(f"From: {email['from_header']}")
    print(f"Subject: {email['subject']}")
    print(f"Coordinator: fixed pipeline   Model: {MODEL}")

    analysis = await sp.run_analyst(client, usage, email)
    brief = analysis["brief"]
    sp.save_json(out_dir, "analyst-brief.json",
                 {"brief": brief, "check_issues": analysis["issues"], "coverage_runs": analysis["coverage_runs"]})
    print(f"\n  Brief: {brief.get('what_changed')}")
    for issue in analysis["issues"]:
        print(f"  CHECK FAILED: {issue}")

    saved = []
    supplier = await sp.draft_supplier(client, usage, email, analysis)
    if supplier["verdict"] != "NO REPLY NEEDED":
        saved.append((sp.save_draft(out_dir, "supplier-reply.txt", supplier, email["file"], COORDINATOR), supplier))

    rows = sp.verified_at_risk(analysis)
    held = bool(brief.get("options"))
    if held:
        print("\n== Customer notices held: the supplier offers options, so a person must choose first.")
    else:
        for row in rows:
            notice = await sp.draft_customer(client, usage, row)
            path = sp.save_draft(out_dir, f"customer-{row['order_id']}.txt", notice, email["file"], COORDINATOR)
            saved.append((path, notice))

    # Summary for the purchasing manager, written by code.
    decisions = list(brief.get("decisions_for_a_person") or [])
    if analysis["issues"]:
        decisions.append("The analyst's brief did not match the coverage tool; check the numbers before using the drafts.")
    if any(d["needs_person"] for _, d in saved):
        decisions.append("At least one draft still failed review after one revision; a person must fix it.")
    lines = [f"Supplier email: {email['file']} ({email['subject']})",
             f"What changed: {brief.get('what_changed')}",
             "Orders at risk:" if rows else "Orders at risk: none"]
    for r in rows:
        late = "no delivery covers it yet" if r["days_late"] is None else f"{r['days_late']} days late"
        lines.append(f"  - {r['order_id']} {r['customer']}: {r['units_short']} {brief.get('part_id')} short, {late}"
                     + (", LATE PENALTY" if r["late_penalty"] else ""))
    for o in brief.get("options") or []:
        ids = o.get("order_ids") or o.get("order_ids_at_risk") or []
        name = str(o.get("name", ""))
        label = name if name.lower().startswith("option") else f"Option {name}"
        lines.append(f"{label}: puts at risk {', '.join(ids) if ids else 'no orders'}")
    if held:
        lines.append("Customer notices: held until a person chooses an option.")
    lines.append(f"Supplier reply: {'none needed' if supplier['verdict'] == 'NO REPLY NEEDED' else 'drafted'}")
    lines.append(f"Drafts saved: {len(saved)}")
    for path, d in saved:
        flag = "NEEDS A PERSON" if d["needs_person"] else d["verdict"]
        lines.append(f"  - {path.relative_to(REPO_ROOT).as_posix()} [{flag}]")
    lines.append("Decision needed by a person: " + ("YES" if decisions else "no"))
    for d in decisions:
        lines.append(f"  - {d}")
    summary = "\n".join(lines)
    (out_dir / "summary.txt").write_text(summary + "\n", encoding="utf-8")

    print("\n" + "-" * 70)
    print(summary)
    print("\nNothing was sent.")
    print("Tokens:\n" + usage.report())


if __name__ == "__main__":
    run_cli("Fixed pipeline: Brookfield's response to supplier emails (drafts only).", COORDINATOR, run_one)
