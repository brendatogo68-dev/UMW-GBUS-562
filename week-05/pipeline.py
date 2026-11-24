"""Fixed pipeline: prepares a company's response to one supplier email, always in the same order.

  1. Supply analyst (agent with the supply MCP tools) writes a brief; code checks it against the tool results.
  2. Customer writer: one notice for each order at risk (skipped if there are none).
  3. Supplier writer: a reply to the supplier (or NO REPLY NEEDED).

Every draft goes through the review step in specialists.py (reviewer, up to 2 revisions, then a name
check in code). At the end a summary lists the drafts saved, the drafts marked for a person, the
decisions for a person, and the tokens used. Nothing is sent. Drafts go to
week-05/drafts/<company folder>/<email>/pipeline/.

--org names the company folder (its CSV data and prompts); without it, week-05/brookfield-bikes is used.

Usage (from the top of the repository):
    .venv\\Scripts\\python.exe week-05\\pipeline.py --email week-05\\brookfield-bikes\\supplier-emails\\01-northgate-controller-delay.eml
    .venv\\Scripts\\python.exe week-05\\pipeline.py --email <file.eml> --save week-05\\runs\\northgate.txt
    .venv\\Scripts\\python.exe week-05\\pipeline.py --org copperline-coffee --email week-05\\copperline-coffee\\supplier-emails\\01-danforth-pump-delay.eml
"""

import shutil

from common import DRAFTS_DIR, SPECIALIST_MODEL, Usage, parse_email, run_cli
import specialists as sp

COORDINATOR = "pipeline"
BRIEF_MISMATCH = "the analyst's brief did not match the coverage tool"


async def run_one(client, email_path):
    email = parse_email(email_path)
    usage = Usage()
    out_dir = sp.drafts_dir(DRAFTS_DIR, email, COORDINATOR)
    shutil.rmtree(out_dir, ignore_errors=True)  # this folder holds only this script's previous output

    print(f"Email: {email['file']}")
    print(f"From: {email['from_header']}")
    print(f"Subject: {email['subject']}")
    print(f"Coordinator: fixed pipeline (code)   Specialist model: {SPECIALIST_MODEL}")
    print(sp.org_header())

    # 1. Supply analyst
    analysis = await sp.run_analyst(client, usage, email, caller=COORDINATOR)
    brief = analysis["brief"]
    sp.save_json(out_dir, "analyst-brief.json",
                 {"brief": brief, "check_issues": analysis["issues"], "coverage_runs": analysis["coverage_runs"]})
    for issue in analysis["issues"]:
        print(f"  CHECK FAILED: {issue}")
    extra = [BRIEF_MISMATCH] if analysis["issues"] else []

    # 2. Customer notices, one per order at risk
    drafts = []
    rows = sp.verified_at_risk(analysis)
    options = brief.get("options") or []
    if not rows:
        print("\n== Customer notices skipped: no orders at risk.")
    for row in rows:
        # If the supplier offers options, whether this order is late depends on the choice.
        notice_extra = extra + (["the supplier offers options; send only if the chosen option delays this order"]
                                if options else [])
        drafts.append(await sp.customer_notice_step(client, usage, row, email["file"], out_dir, COORDINATOR,
                                                    notice_extra))

    # 3. Reply to the supplier
    supplier = await sp.supplier_reply_step(client, usage, email, brief, out_dir, COORDINATOR, extra)
    if supplier["path"]:
        drafts.append(supplier)

    sp.print_summary(email, out_dir, analysis, supplier, drafts, usage)


if __name__ == "__main__":
    run_cli("Fixed pipeline: a company's response to one supplier email (drafts only, nothing is sent).", run_one)
