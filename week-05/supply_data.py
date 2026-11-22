"""Brookfield Bicycle Company supply data: plain Python, no Claude.

Reads the five CSV files in week-05/brookfield-bikes/ and answers three questions:
  get_part(part_id)            stock on hand and scheduled inbound shipments for one part
  get_orders_for_part(part_id) the open customer orders that need that part
  check_coverage(...)          which of those orders can ship on time under a delivery schedule

Coverage rule (Brookfield's allocation policy):
  - Parts go to orders in order of ship date, earliest first (ties: lower order number first).
  - An order ships only when all of its parts are in hand; no partial shipments.
  - Stock on hand is available on day 0. All days are counted from today.
  So order k is ready on the first day when everything that has arrived covers orders 1..k.
  It is at risk if that day is after its ship day.

Run this file directly to print the coverage for the three sample supplier emails:
    .venv\\Scripts\\python.exe week-05\\supply_data.py
"""

import csv
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent / "brookfield-bikes"


class SupplyError(ValueError):
    """A request the data can't answer (unknown part, bad schedule). The message is safe to show Claude."""


def _read(name, data_dir):
    with open(Path(data_dir) / name, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


class SupplyData:
    def __init__(self, data_dir=DATA_DIR):
        self.data_dir = Path(data_dir)
        self.parts = {r["part_id"]: r for r in _read("parts.csv", data_dir)}
        self.bom = _read("bill-of-materials.csv", data_dir)
        self.inbound = _read("inbound.csv", data_dir)
        self.orders = _read("orders.csv", data_dir)
        self.suppliers = _read("suppliers.csv", data_dir)

    # ------------------------------------------------------------ lookups

    def _part(self, part_id):
        key = (part_id or "").strip().upper()
        if key not in self.parts:
            raise SupplyError(f"No part with id {part_id!r}. Known parts: {', '.join(sorted(self.parts))}.")
        return key

    def get_part(self, part_id):
        key = self._part(part_id)
        p = self.parts[key]
        shipments = [
            {"po_number": r["po_number"], "qty": int(r["qty"]), "arrives_in_days": int(r["arrives_in_days"]),
             "supplier": r["supplier"]}
            for r in self.inbound if r["part_id"] == key
        ]
        return {
            "part_id": key,
            "description": p["description"],
            "on_hand": int(p["on_hand"]),
            "supplier": p["supplier"],
            "scheduled_shipments": sorted(shipments, key=lambda s: s["arrives_in_days"]),
            "used_in_models": sorted({b["model"] for b in self.bom if b["part_id"] == key}),
        }

    def get_orders_for_part(self, part_id):
        key = self._part(part_id)
        per_bike = {b["model"]: int(b["qty_per_bike"]) for b in self.bom if b["part_id"] == key}
        orders = [
            {
                "order_id": o["order_id"],
                "customer": o["customer"],
                "model": o["model"],
                "bikes": int(o["qty"]),
                "parts_needed": int(o["qty"]) * per_bike[o["model"]],
                "ship_day": int(o["ship_in_days"]),
                "late_penalty": o["late_penalty"].strip().lower() == "yes",
            }
            for o in self.orders if o["model"] in per_bike
        ]
        orders.sort(key=lambda o: (o["ship_day"], o["order_id"]))
        return {"part_id": key, "orders": orders}

    def order(self, order_id):
        for o in self.orders:
            if o["order_id"] == order_id:
                return o
        return None

    # ------------------------------------------------------------ coverage

    def check_coverage(self, part_id, po_number=None, new_schedule=None):
        """Coverage of every order that needs part_id.

        Without po_number/new_schedule: the current schedule from inbound.csv.
        With them: the shipment(s) for po_number are replaced by new_schedule, a list of
        {"qty": int, "arrives_in_days": int}. Other shipments and stock on hand are unchanged.
        """
        part = self.get_part(part_id)
        key = part["part_id"]

        arrivals = [{"qty": part["on_hand"], "day": 0, "source": "on hand"}]
        replaced = None
        if new_schedule is not None or po_number:
            if not po_number or new_schedule is None:
                raise SupplyError("To change a shipment, give both po_number and new_schedule.")
            po = po_number.strip().upper()
            matches = [s for s in part["scheduled_shipments"] if s["po_number"].upper() == po]
            if not matches:
                known = ", ".join(s["po_number"] for s in part["scheduled_shipments"]) or "none"
                raise SupplyError(f"{po_number} is not a scheduled shipment of {key}. Shipments of {key}: {known}.")
            replaced = matches[0]
            if not new_schedule:
                raise SupplyError("new_schedule is empty. List each delivery as {qty, arrives_in_days}.")
            total = 0
            for i, d in enumerate(new_schedule, 1):
                try:
                    qty, day = int(d["qty"]), int(d["arrives_in_days"])
                except (KeyError, TypeError, ValueError):
                    raise SupplyError(f"Delivery {i} in new_schedule needs whole numbers qty and arrives_in_days.")
                if qty <= 0 or day < 0:
                    raise SupplyError(f"Delivery {i}: qty must be above 0 and arrives_in_days 0 or more.")
                total += qty
                arrivals.append({"qty": qty, "day": day, "source": po})
            if total != replaced["qty"]:
                note = f"new_schedule totals {total} units; {po} was for {replaced['qty']}."
            else:
                note = None
        for s in part["scheduled_shipments"]:
            if replaced is None or s["po_number"] != replaced["po_number"]:
                arrivals.append({"qty": s["qty"], "day": s["arrives_in_days"], "source": s["po_number"]})
        arrivals.sort(key=lambda a: a["day"])

        def supply_by(day):
            return sum(a["qty"] for a in arrivals if a["day"] <= day)

        def ready_day(needed):
            running = 0
            for a in arrivals:
                running += a["qty"]
                if running >= needed:
                    return a["day"]
            return None  # never covered by any scheduled delivery

        results, cumulative = [], 0
        for o in self.get_orders_for_part(key)["orders"]:
            before = cumulative
            cumulative += o["parts_needed"]
            ready = ready_day(cumulative)
            on_time = ready is not None and ready <= o["ship_day"]
            row = {
                "order_id": o["order_id"],
                "customer": o["customer"],
                "model": o["model"],
                "bikes": o["bikes"],
                "parts_needed": o["parts_needed"],
                "ship_day": o["ship_day"],
                "ready_day": ready,
                "on_time": on_time,
                "late_penalty": o["late_penalty"],
            }
            if not on_time:
                available = max(0, supply_by(o["ship_day"]) - before)
                row["units_short"] = o["parts_needed"] - min(available, o["parts_needed"])
                row["days_late"] = None if ready is None else ready - o["ship_day"]
            results.append(row)

        result = {
            "part_id": key,
            "rule": "Parts go to orders by earliest ship date; an order ships only when complete. Days are from today.",
            "schedule_used": [{"qty": a["qty"], "arrives_in_days": a["day"], "source": a["source"]} for a in arrivals],
            "orders": results,
            "orders_at_risk": [r for r in results if not r["on_time"]],
        }
        if replaced is not None and note:
            result["warning"] = note
        return result


if __name__ == "__main__":
    data = SupplyData()

    def show(title, res):
        print(f"\n{title}")
        for r in res["orders"]:
            flag = "ON TIME" if r["on_time"] else f"LATE {r['days_late']}d, short {r['units_short']}"
            print(f"  {r['order_id']} {r['customer']:<28} need {r['parts_needed']:>3} ship d{r['ship_day']:<3}"
                  f" ready d{r['ready_day']}  {flag}{'  (penalty)' if r['late_penalty'] else ''}")

    show("MC-500, current schedule", data.check_coverage("MC-500"))
    show("Email 1 - Northgate: 120 on day 5, 280 on day 26",
         data.check_coverage("MC-500", "PO-7781", [{"qty": 120, "arrives_in_days": 5},
                                                  {"qty": 280, "arrives_in_days": 26}]))
    show("Email 2 - Kendall option 1: 160 on day 8, 240 on day 22",
         data.check_coverage("TR-29", "PO-7795", [{"qty": 160, "arrives_in_days": 8},
                                                 {"qty": 240, "arrives_in_days": 22}]))
    show("Email 2 - Kendall option 2: 400 on day 12",
         data.check_coverage("TR-29", "PO-7795", [{"qty": 400, "arrives_in_days": 12}]))
    show("Email 3 - Keystone: BP-48 on schedule", data.check_coverage("BP-48"))
