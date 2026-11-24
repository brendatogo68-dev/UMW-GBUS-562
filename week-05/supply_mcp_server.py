"""MCP server for Brookfield Bicycle Company's supply data, built with the official `mcp` package.

It reads the CSV files in week-05/brookfield-bikes/ (parts, inbound, orders, bill-of-materials,
suppliers) and offers three read-only tools:

  get_part(part_id)
      The part's stock on hand, its scheduled shipments, and the bike models that use it.
  get_orders_for_part(part_id)
      The open orders that need the part: units needed (bikes x parts per bike), ship day, late penalty.
  check_coverage(part_id, arrivals)
      arrivals is a new list of deliveries {qty, day} that REPLACES all of the part's scheduled
      shipments (stock on hand stays). Orders are filled complete, in ship-day order, so a short order
      holds up the ones after it. For each order: covered, or units short and the first day it can ship.

All days are counted from today (today is day 0). The math is plain Python; Claude never does it.

Usage (from the top of the repository):
    .venv\\Scripts\\python.exe week-05\\supply_mcp_server.py           # run the server (MCP over stdio)
    .venv\\Scripts\\python.exe week-05\\supply_mcp_server.py --demo    # print coverage for the sample emails

Add it to Claude Code. Run this from the top of the repository: local scope saves the server for the
folder you run it in. Full paths make it start no matter which folder Claude Code launches it from:
    claude mcp add brookfield-supply -- "C:/Users/Dell/Desktop/GBUS-562-Course/UMW-GBUS-562/.venv/Scripts/python.exe" "C:/Users/Dell/Desktop/GBUS-562-Course/UMW-GBUS-562/week-05/supply_mcp_server.py"

The server talks MCP over stdin/stdout, so its own messages go to stderr. It reads only local files,
never calls the Claude API, and needs no API key.
"""

import argparse
import csv
import sys
from pathlib import Path

from pydantic import BaseModel, Field
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations

DATA_DIR = Path(__file__).resolve().parent / "brookfield-bikes"
READ_ONLY = ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=False)


class SupplyError(ValueError):
    """A request the data can't answer (unknown part, bad arrivals). The message is safe to show Claude."""


def read_csv(path):
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


class SupplyData:
    """The five CSV files, and the three questions the tools answer."""

    def __init__(self, data_dir=DATA_DIR):
        data_dir = Path(data_dir)
        self.parts = {r["part_id"]: r for r in read_csv(data_dir / "parts.csv")}
        self.bom = read_csv(data_dir / "bill-of-materials.csv")
        self.inbound = read_csv(data_dir / "inbound.csv")
        self.orders = read_csv(data_dir / "orders.csv")
        self.suppliers = read_csv(data_dir / "suppliers.csv")

    def _key(self, part_id):
        key = (part_id or "").strip().upper()
        if key not in self.parts:
            raise SupplyError(f"No part with id {part_id!r}. Known parts: {', '.join(sorted(self.parts))}.")
        return key

    def order(self, order_id):
        return next((o for o in self.orders if o["order_id"] == order_id), None)

    # ------------------------------------------------------------ get_part

    def get_part(self, part_id):
        key = self._key(part_id)
        p = self.parts[key]
        shipments = sorted(
            ({"po_number": r["po_number"], "supplier": r["supplier"], "qty": int(r["qty"]),
              "day": int(r["arrives_in_days"])} for r in self.inbound if r["part_id"] == key),
            key=lambda s: s["day"])
        return {
            "part_id": key,
            "description": p["description"],
            "supplier": p["supplier"],
            "on_hand": int(p["on_hand"]),
            "scheduled_shipments": shipments,
            "used_in_models": [{"model": b["model"], "parts_per_bike": int(b["qty_per_bike"])}
                               for b in self.bom if b["part_id"] == key],
        }

    # ------------------------------------------------------------ get_orders_for_part

    def get_orders_for_part(self, part_id):
        key = self._key(part_id)
        per_bike = {b["model"]: int(b["qty_per_bike"]) for b in self.bom if b["part_id"] == key}
        orders = [
            {
                "order_id": o["order_id"],
                "customer": o["customer"],
                "model": o["model"],
                "bikes": int(o["qty"]),
                "parts_per_bike": per_bike[o["model"]],
                "units_needed": int(o["qty"]) * per_bike[o["model"]],
                "ship_day": int(o["ship_in_days"]),
                "late_penalty": o["late_penalty"].strip().lower() == "yes",
            }
            for o in self.orders if o["model"] in per_bike
        ]
        # Ship-day order; ties go to the lower order number.
        orders.sort(key=lambda o: (o["ship_day"], o["order_id"]))
        return {"part_id": key, "orders": orders}

    # ------------------------------------------------------------ check_coverage

    def check_coverage(self, part_id, arrivals):
        key = self._key(part_id)
        on_hand = int(self.parts[key]["on_hand"])

        if not isinstance(arrivals, list):
            raise SupplyError("arrivals must be a list of deliveries, each {qty, day}. Use [] for no deliveries.")
        supply = [{"qty": on_hand, "day": 0, "source": "on hand"}]
        for i, a in enumerate(arrivals, 1):
            try:
                qty, day = int(a["qty"]), int(a["day"])
            except (KeyError, TypeError, ValueError):
                raise SupplyError(f"Arrival {i} needs whole numbers qty and day.") from None
            if qty <= 0 or day < 0:
                raise SupplyError(f"Arrival {i}: qty must be above 0 and day must be 0 or more.")
            supply.append({"qty": qty, "day": day, "source": "arrival"})
        supply.sort(key=lambda s: s["day"])

        def supply_by(day):
            return sum(s["qty"] for s in supply if s["day"] <= day)

        def first_day_covering(total):
            running = 0
            for s in supply:
                running += s["qty"]
                if running >= total:
                    return s["day"]
            return None  # the arrivals never cover it

        # Orders are filled complete, in ship-day order. Parts are held for an earlier order until it
        # ships, so order k can ship once everything delivered covers orders 1..k together; a short
        # order therefore holds up every order after it.
        results, needed_before = [], 0
        for o in self.get_orders_for_part(key)["orders"]:
            needed_through = needed_before + o["units_needed"]
            first_day = first_day_covering(needed_through)
            row = {k: o[k] for k in ("order_id", "customer", "model", "bikes", "units_needed", "ship_day", "late_penalty")}
            row["covered"] = first_day is not None and first_day <= o["ship_day"]
            if not row["covered"]:
                left_for_this = max(0, supply_by(o["ship_day"]) - needed_before)
                row["units_short"] = o["units_needed"] - min(left_for_this, o["units_needed"])
                row["first_ship_day"] = first_day
                row["days_late"] = None if first_day is None else first_day - o["ship_day"]
            results.append(row)
            needed_before = needed_through

        short = [r for r in results if not r["covered"]]
        return {
            "part_id": key,
            "rule": ("Arrivals replace the part's scheduled shipments; stock on hand is available on day 0. Orders "
                     "are filled complete, in ship-day order, so a short order holds up the ones after it. "
                     "Days are counted from today."),
            "supply_used": [{"qty": s["qty"], "day": s["day"], "source": s["source"]} for s in supply],
            "total_supply": sum(s["qty"] for s in supply),
            "total_needed": needed_before,
            "orders": results,
            "orders_short": short,
            "all_covered": not short,
        }


# ---------------------------------------------------------------- the MCP server

class Arrival(BaseModel):
    qty: int = Field(description="Quantity of the part in this delivery.")
    day: int = Field(description="Day the delivery arrives, counted from today (today is day 0).")


def build_server(data):
    server = MCPServer(
        name="brookfield-supply",
        instructions="Brookfield Bicycle Company supply tools: parts, open orders, and order coverage. "
                     "Read-only; uses only local CSV files. Days are counted from today (day 0).",
        log_level="WARNING",
    )

    def safe(fn, *args):
        try:
            return fn(*args)
        except SupplyError as e:
            raise ToolError(str(e)) from None

    @server.tool(annotations=READ_ONLY, description=(
        "Look up one part by part_id (e.g. MC-500): its description, supplier, stock on hand today, its "
        "scheduled shipments (po_number, qty, day counted from today), and the bike models that use it "
        "with parts per bike."))
    def get_part(part_id: str) -> dict:
        return safe(data.get_part, part_id)

    @server.tool(annotations=READ_ONLY, description=(
        "List the open customer orders that need one part, in ship-day order. For each order: order_id, "
        "customer, model, bikes, parts_per_bike, units_needed (bikes x parts per bike), ship_day (days from "
        "today) and late_penalty (true if the contract has a penalty for shipping late)."))
    def get_orders_for_part(part_id: str) -> dict:
        return safe(data.get_orders_for_part, part_id)

    @server.tool(annotations=READ_ONLY, description=(
        "Check which orders for a part can ship on time under a list of arrivals. Use this for every "
        "coverage question; never work coverage out yourself.\n\n"
        "arrivals REPLACES all of the part's scheduled shipments, so list every delivery you expect, each "
        "with qty and day counted from today (convert phrases such as 'three weeks after the scheduled "
        "date' to days from today first). Stock on hand is added for you on day 0. To check the current "
        "schedule, pass the scheduled shipments from get_part. To compare options, call once per option.\n\n"
        "Orders are filled complete, in ship-day order, so a short order holds up the ones after it. "
        "Returns every order with covered true or false; an order that isn't covered also has units_short "
        "(units missing on its ship day), first_ship_day (null if the arrivals never cover it) and "
        "days_late. orders_short lists the orders that aren't covered."))
    def check_coverage(part_id: str, arrivals: list[Arrival]) -> dict:
        return safe(data.check_coverage, part_id, [a.model_dump() for a in arrivals])

    return server


def demo(data):
    """Print coverage for the three sample supplier emails (no MCP, no Claude)."""
    def show(title, part_id, arrivals):
        res = data.check_coverage(part_id, arrivals)
        print(f"\n{title}")
        for r in res["orders"]:
            status = "covered" if r["covered"] else \
                f"SHORT {r['units_short']}, first ship day {r['first_ship_day']} ({r['days_late']} days late)"
            print(f"  {r['order_id']} {r['customer']:<28} needs {r['units_needed']:>3}, ship day {r['ship_day']:>2}: "
                  f"{status}{'  [late penalty]' if r['late_penalty'] else ''}")

    show("Email 1, Northgate: MC-500, 120 on day 5 and 280 on day 26", "MC-500",
         [{"qty": 120, "day": 5}, {"qty": 280, "day": 26}])
    show("Email 2, Kendall option 1: TR-29, 160 on day 8 and 240 on day 22", "TR-29",
         [{"qty": 160, "day": 8}, {"qty": 240, "day": 22}])
    show("Email 2, Kendall option 2: TR-29, 400 on day 12", "TR-29", [{"qty": 400, "day": 12}])
    show("Email 3, Keystone: BP-48 on schedule, 150 on day 6", "BP-48", [{"qty": 150, "day": 6}])


def main():
    parser = argparse.ArgumentParser(description="Brookfield supply MCP server (stdio).")
    parser.add_argument("--data", metavar="FOLDER", default=str(DATA_DIR),
                        help="folder with the CSV files (default: week-05/brookfield-bikes)")
    parser.add_argument("--demo", action="store_true", help="print coverage for the sample emails, then exit")
    args = parser.parse_args()

    data = SupplyData(args.data)
    if args.demo:
        demo(data)
        return
    print(f"Brookfield supply server: {len(data.parts)} parts, {len(data.orders)} orders.", file=sys.stderr)
    build_server(data).run("stdio")


if __name__ == "__main__":
    main()
