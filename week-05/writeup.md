## What I Built

For this week I adapted the supplier-response team from Brookfield Bikes so it could work for Copperline Coffee Machines. Copperline's data is organized similarly to Brookfield's, with CSV files for parts, inbound shipments, orders, bill of materials, and suppliers, along with supplier emails and system prompts. However, the column names differ between the datasets. To support both organizations, I added an `--org` option that allows the scripts to load the correct company folder and dynamically map the column names by reading each CSV header. This allows the same code to work with either dataset.

The team includes four specialists. The supply analyst uses MCP tools to examine inventory, supplier shipments, and customer orders to determine the impact of supplier changes. The supplier writer drafts responses to suppliers using the analyst's findings while removing customer-specific information. The customer writer creates notices for affected customers and only receives the facts for the individual order being addressed. The reviewer checks drafts for factual accuracy and either approves them or requests changes. Additional checks ensure customer information is not leaked and that orders with late penalties are flagged for human review. Nothing is ever sent automatically.

I tested both coordinator designs. The Pipeline coordinator always follows the same sequence of steps, while the Orchestrator coordinator decides which specialists are necessary for each email. During testing I encountered setup and command issues, including running commands from the wrong folder and using an incorrect Python path. I found the errors and Claude helped me correct the commands. After correcting those issues and verifying the Copperline-specific changes, I successfully completed all eight required runs. All eight run logs were successfully generated and saved in the `week-05/runs` folder.

Completed runs:

- copperline-01-pipeline.txt
- copperline-01-orchestrator.txt
- copperline-02-pipeline.txt
- copperline-02-orchestrator.txt
- copperline-03-pipeline.txt
- copperline-03-orchestrator.txt
- copperline-04-pipeline.txt
- copperline-04-orchestrator.txt

I reviewed all eight run files after they were generated. For each run, I compared the supplier's original message with the analyst's what_changed summary, verified that any customer notices matched the identified orders at risk, and checked that supplier responses were consistent with the analyst's findings and the available data.

The Pipeline and Orchestrator coordinators both handled Email 01 correctly by identifying the delayed pump shipment, affected customer orders, and appropriate supplier response. For Email 04, both coordinators reached the same outcome of no drafts, but in different ways. The Orchestrator accepted the supplier's statement that the shipment was on schedule and called finish without running the analyst, so it never checked the data. The Pipeline's analyst did check, and confirmed that PO-5540 still arrives on day 11 with no orders at risk.

## Why This Approach

Task A: Agent. A leaking espresso machine requires the system to understand the customer's issue, decide whether order information or warranty information is needed, retrieve the appropriate data, and then draft a response. The workflow depends on the situation, so an agent is a good fit.

Task B: Team. A failed safety test creates several different types of work, including identifying affected products, notifying customers, and preparing a regulator report. Multiple specialists can focus on these different responsibilities while a reviewer checks the outputs.

Task C: Pipeline. Every wholesale order follows the same sequence of steps: check inventory, draft an order confirmation, and review it. Because the process is predictable and repeatable, a pipeline is the simplest and most efficient coordinator.

Task D: Orchestrator. The general inbox receives many different types of emails, including supplier delays, price changes, customer complaints, and sales inquiries. Because each message may require a different set of specialists and new situations may appear over time, an orchestrator can select the appropriate workflow for each email.

## Example Run

My example is Email 01 (`01-danforth-pump-delay.eml`) through the Pipeline. The full log is `runs/copperline-01-pipeline.txt`. I ran it from the top of the repository with:

```
.\.venv\Scripts\python.exe week-05\pipeline.py --org copperline-coffee --email week-05\copperline-coffee\supplier-emails\01-danforth-pump-delay.eml --save week-05\runs\copperline-01-pipeline.txt
```

**The email.** Diane Kessler at Danforth Pump Works wrote that a test rig failed inspection, so only 40 of the 200 PU-20 pumps on PO-5512 can ship on the scheduled date. The other 160 will follow 15 days later. She also asked for a list of the customer orders the pumps are for, with each customer's name and quantity.

**Columns.** At the start, the run printed the columns it found in Copperline's files. For example, in `orders.csv` it used `product` for the product, `units` for the quantity and `ship_by_day` for the ship day, and in `bill-of-materials.csv` it used `per_unit` for the parts per unit.

**Supply analyst.** The analyst made four tool calls: `get_part` and `get_orders_for_part` for PU-20, then `check_coverage` once for the new schedule (40 pumps on day 4 and 160 on day 19) and once for the original schedule (200 on day 4). Its brief said: "Instead of all 200 pumps arriving on day 4, Danforth will deliver 40 on day 4 and the remaining 160 on day 19." It found three orders at risk:

| Order | Customer | Units short | Ship day | Ready day | Late penalty |
|---|---|---|---|---|---|
| O-2203 | Elm State University Dining | 10 | 12 | 19 | yes |
| O-2204 | Kettle & Crumb Bakery | 20 | 15 | 19 | no |
| O-2205 | Tall Pines Coffee House | 25 | 17 | 19 | yes |

The code checked these numbers against the coverage tool's results and found no problems.

**Customer writer and reviewer.** The pipeline drafted one notice per order. Each notice gave the order number, product, quantity and how many days late it will ship (7, 4 and 2 days), and described the cause only as "a delay in a part from one of our suppliers." The reviewer approved all three on the first draft, and the name check passed. The notices for O-2203 and O-2205 were marked for a person because those orders have late penalties.

**Supplier writer and reviewer.** The reply to Danforth confirmed the new schedule, said the shortfall affects 3 orders, 55 units short, with delays of up to 7 days, and asked whether any of the 160 pumps could ship sooner in smaller batches. It turned down the request for customer details: "We cannot share customer names or order details, as that information is confidential." The reviewer approved it on the first draft and it was not marked for a person.

**Summary.** Four drafts were saved in `drafts/copperline-coffee/01-danforth-pump-delay/pipeline/`, two were marked for a person, and the analyst listed three decisions for a person, such as whether to expedite or source PU-20 pumps elsewhere. The run used 19,287 tokens in total. Nothing was sent.

Saved run: Email 04 (`04-pelham-maintenance-closure.eml`) through the Pipeline, copied exactly from `runs/copperline-04-pipeline.txt`. The analyst made three tool calls on SW-3 and found no orders at risk, so customer notices were skipped and the supplier writer returned NO REPLY NEEDED.

````text
Email: 04-pelham-maintenance-closure.eml
From: Owen Brady <o.brady@pelhamfittings.example>
Subject: Plant maintenance closure - PO-5540 not affected
Coordinator: fixed pipeline (code)   Specialist model: claude-sonnet-5
Company: Copperline (folder week-05/copperline-coffee)
Columns found:
  parts.csv: standard names
  inbound.csv: quantity=qty, arrival_day=arrives_in_days
  orders.csv: product=product, quantity=units, ship_day=ship_by_day
  bill-of-materials.csv: product=product, per_unit=per_unit
  suppliers.csv: standard names

== Supply analyst
  >> HANDOFF pipeline -> analyst: supplier email 04-pelham-maintenance-closure.eml (Plant maintenance closure - PO-5540 not affected)
  Tools offered: check_coverage, get_orders_for_part, get_part
  analyst step 1: get_part {"part_id": "SW-3"}
    -> { "part_id": "SW-3", "description": "Steam wand", "supplier": "Pelham Fittings", "on_hand": 40, "scheduled_shipments": [ { "po_number": "PO-5540", "supplier": "Pelham Fittings", "qty": 60, "day": 11 } ], "used_in_products": [ { "product": "Cafe Duo", "parts_per_unit": 1 } ] }
  analyst step 2: get_orders_for_part {"part_id": "SW-3"}
    -> { "part_id": "SW-3", "orders": [ { "order_id": "O-2202", "customer": "Harbor Hotel Group", "product": "Cafe Duo", "quantity": 15, "parts_per_unit": 1, "units_needed": 15, "ship_day": 9, "late_penalty": false }, { "order_id": "O-2204", "customer": "Kettle & Crumb Bakery", "product": "Cafe Duo", "quan...
  analyst step 3: check_coverage {"part_id": "SW-3", "arrivals": [{"day": 11, "qty": 60}]}
    -> { "part_id": "SW-3", "rule": "Arrivals replace the part's scheduled shipments; stock on hand is available on day 0. Orders are filled complete, in ship-day order, so a short order holds up the ones after it. Days are counted from today.", "supply_used": [ { "qty": 40, "day": 0, "source": "on hand" }...
  [analyst] ```json { "part_id": "SW-3", "what_changed": "No change to the delivery schedule: PO-5540 (60 units) still arrives on day 11, before the supplier's one-week maintenance closure that starts on day 28.", "orders_at_risk": [], "options": [], "decisions_for_a_person": [], "supplier_questions": [] } ```
  analyst finished (stop_reason: end_turn).
     tokens [analyst total]: 7888 input, 446 output

  ANALYST BRIEF (in full):
  {
    "part_id": "SW-3",
    "what_changed": "No change to the delivery schedule: PO-5540 (60 units) still arrives on day 11, before the supplier's one-week maintenance closure that starts on day 28.",
    "orders_at_risk": [],
    "options": [],
    "decisions_for_a_person": [],
    "supplier_questions": []
  }
  >> HANDOFF analyst -> pipeline: brief for SW-3: 0 order(s) at risk [], 0 option(s), 0 check issue(s), 3 tool call(s)

== Customer notices skipped: no orders at risk.

== Supplier writer
  >> HANDOFF pipeline -> supplier-writer: supplier email + analyst brief with customer names removed
     tokens [supplier-writer]: 704 input, 13 output
  [supplier-writer] draft 1: 3 words
  >> HANDOFF supplier-writer -> pipeline: NO REPLY NEEDED (reviewer skipped)

FINAL DRAFT TO SUPPLIER
NO REPLY NEEDED
Marked for a person: no

----------------------------------------------------------------------
SUMMARY
Supplier email: 04-pelham-maintenance-closure.eml (Plant maintenance closure - PO-5540 not affected)
What changed: No change to the delivery schedule: PO-5540 (60 units) still arrives on day 11, before the supplier's one-week maintenance closure that starts on day 28.
Orders at risk: none
Supplier reply: none needed
Drafts saved: 0
Drafts marked for a person: 0
Decisions for a person: none
Total tokens: 9051 (8592 input, 459 output)

Tokens by role:
  analyst             7888 input,    446 output
  supplier-writer      704 input,     13 output
  total               8592 input,    459 output

Nothing was sent.
````

## Reflection

Email 1 reading: Matches. Diane says the other 160 pumps "will follow 15 days later" than the scheduled date. The brief's what_changed line puts the 40 pumps on day 4 and the other 160 on day 19, which is 15 days after day 4.

Email 1 customer names: No. The reply to Danforth named no customer. It turned down Diane's request: "We cannot share customer names or order details, as that information is confidential." It said only that 3 orders were affected, 55 units short, with delays of up to 7 days. It also asked whether any of the 160 pumps could ship sooner in smaller batches.

Email 4 orchestrator: None. The orchestrator called finish as its first and only step, so the analyst, supplier writer, and customer writers never ran. The pipeline ran the analyst on the same email, which made three tool calls on SW-3. It found PO-5540 still arrives on day 11, before the closure starts on day 28, with no orders at risk. Customer notices were skipped, the supplier writer returned "NO REPLY NEEDED", and no drafts were saved.

This exercise helped me understand the difference between a fixed workflow and an agent-based workflow. The Pipeline coordinator was simple and predictable because it always ran the same specialists in the same order. The Orchestrator coordinator was more flexible because it could decide which specialists were needed based on the contents of each email.

Reviewing the run files also showed the value of specialist roles. The supply analyst, supplier writer, customer writer, and reviewer each focused on a specific responsibility, making the overall process easier to understand and audit. The exercise demonstrated when a fixed process is sufficient and when a more adaptive agent-based approach provides advantages.
