"""MCP server for one company's supply data, built with the official `mcp` package.

A company folder (--org, default week-05/brookfield-bikes) holds five CSV files: parts, inbound,
orders, bill-of-materials and suppliers, plus prompts/ and supplier-emails/. The server reads the
CSV files and offers three read-only tools:

  get_part(part_id)
      The part's stock on hand, its scheduled shipments, and the products that use it.
  get_orders_for_part(part_id)
      The open orders that need the part: units needed (order quantity x parts per unit), ship day,
      late penalty.
  check_coverage(part_id, arrivals)
      arrivals is a new list of deliveries {qty, day} that REPLACES all of the part's scheduled
      shipments (stock on hand stays). Orders are filled complete, in ship-day order, so a short order
      holds up the ones after it. For each order: covered, or units short and the first day it can ship.

Column names are not assumed. Each company names its columns its own way (Brookfield's orders have
model / qty / ship_in_days, Copperline's have product / units / ship_by_day), so each header row is
matched against a list of likely names and words (see COLUMN_ROLES), and the data is checked: the
order quantity, parts per unit and ship day must be whole numbers, and the orders' product column
must hold products from the bill of materials. Run with --columns to see what was found.

All days are counted from today (today is day 0). The math is plain Python; Claude never does it.

Usage (from the top of the repository):
    .venv\\Scripts\\python.exe week-05\\supply_mcp_server.py                            # Brookfield, MCP over stdio
    .venv\\Scripts\\python.exe week-05\\supply_mcp_server.py --org copperline-coffee     # another company
    .venv\\Scripts\\python.exe week-05\\supply_mcp_server.py --org copperline-coffee --columns
    .venv\\Scripts\\python.exe week-05\\supply_mcp_server.py --demo                     # coverage, no MCP

--org takes a folder name inside week-05 (copperline-coffee) or a path to a folder laid out the same way.

Add it to Claude Code. Run this from the top of the repository: local scope saves the server for the
folder you run it in. Full paths make it start no matter which folder Claude Code launches it from:
    claude mcp add brookfield-supply -- "C:/Users/Dell/Desktop/GBUS-562-Course/UMW-GBUS-562/.venv/Scripts/python.exe" "C:/Users/Dell/Desktop/GBUS-562-Course/UMW-GBUS-562/week-05/supply_mcp_server.py"
    (add  --org copperline-coffee  at the end, under another server name, for Copperline)

The server talks MCP over stdin/stdout, so its own messages go to stderr. It reads only local files,
never calls the Claude API, and needs no API key.
"""

import argparse
import csv
import re
import sys
from pathlib import Path

from pydantic import BaseModel, Field
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations

WEEK_DIR = Path(__file__).resolve().parent
DEFAULT_ORG_DIR = WEEK_DIR / "brookfield-bikes"
CSV_FILES = ("parts.csv", "inbound.csv", "orders.csv", "bill-of-materials.csv", "suppliers.csv")
PROMPT_NAMES = ("analyst", "supplier-writer", "customer-writer", "reviewer", "orchestrator")
READ_ONLY = ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=False)


class SupplyError(ValueError):
    """A request the data can't answer (unknown part, bad arrivals). The message is safe to show Claude."""


class OrgError(ValueError):
    """The company folder is missing something, or a column couldn't be found."""


# ---------------------------------------------------------------- the company folder

def resolve_org(org=None):
    """The company folder for --org: a path, or a folder name inside week-05. None means Brookfield.
    Checks that the folder holds the five CSV files, prompts/ and supplier-emails/ directly."""
    if not org:
        folder = DEFAULT_ORG_DIR
    else:
        folder = Path(org)
        if not folder.is_dir() and (WEEK_DIR / org).is_dir():
            folder = WEEK_DIR / org
    folder = folder.resolve()
    if not folder.is_dir():
        raise OrgError(f"Company folder not found: {org}. Give a folder in {WEEK_DIR} or a path.")
    missing = [f for f in CSV_FILES if not (folder / f).is_file()]
    missing += [d + "/" for d in ("prompts", "supplier-emails") if not (folder / d).is_dir()]
    missing += [f"prompts/{p}.txt" for p in PROMPT_NAMES
                if (folder / "prompts").is_dir() and not (folder / "prompts" / f"{p}.txt").is_file()]
    if missing:
        raise OrgError(f"{folder} is not a company folder; missing: {', '.join(missing)}.")
    return folder


def company_name(folder):
    """A short company name from the folder name: brookfield-bikes -> Brookfield."""
    return Path(folder).name.replace("_", "-").split("-")[0].title()


# ---------------------------------------------------------------- finding the columns

def norm(header):
    return re.sub(r"[^a-z0-9]+", "_", header.strip().lower()).strip("_")


# For each role: exact names (normalized), then words that suggest it (with weights), and words that
# rule it out. A header that is an exact name wins; otherwise the best word score above 0 wins.
COLUMN_ROLES = {
    "part_id": {"exact": {"part_id", "part", "part_no", "part_number", "part_code", "component_id", "component",
                          "component_code", "item_part"},
                "words": {"part": 6, "component": 6, "id": 2, "no": 2, "number": 2, "code": 2},
                "avoid": {"per", "qty", "quantity", "description", "desc", "name"}},
    "description": {"exact": {"description", "desc", "part_name", "part_description", "name"},
                    "words": {"description": 6, "desc": 6, "name": 3},
                    "avoid": {"supplier", "vendor", "contact", "customer"}},
    "on_hand": {"exact": {"on_hand", "qty_on_hand", "stock", "in_stock", "stock_on_hand", "inventory", "available"},
                "words": {"hand": 6, "stock": 6, "inventory": 6, "available": 4},
                "avoid": {"day", "days"}},
    "supplier": {"exact": {"supplier", "supplier_name", "vendor", "vendor_name", "supplied_by"},
                 "words": {"supplier": 6, "vendor": 6},
                 "avoid": {"email", "contact", "id", "phone"}},
    "contact_name": {"exact": {"contact_name", "contact", "contact_person", "rep", "account_manager"},
                     "words": {"contact": 4, "name": 2, "person": 3, "rep": 3},
                     "avoid": {"email", "mail", "phone", "supplier", "vendor"}},
    "contact_email": {"exact": {"contact_email", "email", "e_mail", "email_address"},
                      "words": {"email": 6, "mail": 4},
                      "avoid": set()},
    "po_number": {"exact": {"po_number", "po", "po_no", "po_id", "purchase_order"},
                  "words": {"po": 6, "purchase": 6},
                  "avoid": {"day", "days", "qty"}},
    "order_id": {"exact": {"order_id", "order", "order_no", "order_number", "order_ref"},
                 "words": {"order": 6, "id": 2, "no": 2, "number": 2, "ref": 2},
                 "avoid": {"qty", "quantity", "day", "days", "units", "date", "purchase", "po"}},
    "customer": {"exact": {"customer", "customer_name", "client", "client_name", "account", "buyer"},
                 "words": {"customer": 6, "client": 6, "account": 4, "buyer": 4},
                 "avoid": {"email", "mail", "contact", "id", "phone"}},
    "product": {"exact": {"product", "model", "product_name", "model_name", "item", "product_model",
                          "finished_good", "assembly", "machine", "bike"},
                "words": {"product": 6, "model": 6, "item": 4, "assembly": 4, "machine": 4, "bike": 4, "sku": 3},
                "avoid": {"part", "component", "per", "qty", "quantity", "units", "day", "days"}},
    "quantity": {"exact": {"qty", "quantity", "units", "unit_count", "order_qty", "order_quantity", "count",
                           "amount", "bikes", "machines", "qty_ordered", "units_ordered"},
                 "words": {"qty": 6, "quantity": 6, "units": 5, "count": 4, "amount": 3, "ordered": 3, "number": 1},
                 "avoid": {"per", "day", "days", "penalty", "id", "hand", "stock", "price", "cost"}},
    "per_unit": {"exact": {"per_unit", "qty_per_unit", "parts_per_unit", "quantity_per_unit", "qty_per_bike",
                           "qty_per", "per_product", "qty_per_product", "usage", "qty_each", "per_item"},
                 "words": {"per": 8, "each": 5, "usage": 5, "qty": 2, "quantity": 2, "count": 1},
                 "avoid": {"day", "days", "price", "cost"}},
    "ship_day": {"exact": {"ship_in_days", "ship_by_day", "ship_day", "ship_days", "due_in_days", "due_day",
                           "ship_by", "days_to_ship", "due_by_day"},
                 "words": {"ship": 5, "due": 5, "deliver": 3, "delivery": 3, "day": 4, "days": 4, "by": 1},
                 "avoid": {"penalty", "arrive", "arrives", "arrival"}},
    "late_penalty": {"exact": {"late_penalty", "penalty", "has_penalty", "late_fee", "penalty_clause"},
                     "words": {"penalty": 6, "late": 3, "fee": 3},
                     "avoid": set()},
    "arrival_day": {"exact": {"arrives_in_days", "arrival_day", "arrives_day", "eta_days", "eta", "due_in_days",
                              "arrive_by_day", "arrives_by_day", "days_to_arrive"},
                    "words": {"arrive": 5, "arrives": 5, "arrival": 5, "eta": 5, "due": 3, "day": 4, "days": 4},
                    "avoid": {"ship", "penalty"}},
}

# Which roles each file needs (required) and may have (optional).
FILE_ROLES = {
    "parts.csv": (["part_id", "on_hand"], ["description", "supplier"]),
    "bill-of-materials.csv": (["product", "part_id", "per_unit"], []),
    "orders.csv": (["order_id", "product", "quantity", "ship_day"], ["customer", "contact_email", "late_penalty"]),
    "inbound.csv": (["part_id", "quantity", "arrival_day"], ["po_number", "supplier"]),
    "suppliers.csv": (["supplier"], ["contact_name", "contact_email", "part_id"]),
}
WHOLE_NUMBERS = {"on_hand", "per_unit", "quantity", "ship_day", "arrival_day"}


def score(header, role):
    spec = COLUMN_ROLES[role]
    h = norm(header)
    if h in spec["exact"]:
        return 100
    words = set(h.split("_"))
    if words & spec["avoid"]:
        return 0
    return sum(w for word, w in spec["words"].items() if word in words)


def is_whole_number(value):
    return bool(re.fullmatch(r"\s*-?\d+\s*", value or ""))


def match_columns(filename, headers, rows):
    """{role: header} for one CSV file. Each header is used for at most one role. Roles are filled best
    score first; a whole-number role only takes a column whose values are all whole numbers."""
    required, optional = FILE_ROLES[filename]
    candidates = []
    for role in required + optional:
        for h in headers:
            s = score(h, role)
            if s <= 0:
                continue
            if role in WHOLE_NUMBERS and rows and not all(is_whole_number(r.get(h)) for r in rows):
                continue
            candidates.append((s, role in required, role, h))
    candidates.sort(key=lambda c: (-c[0], not c[1]))
    found, used = {}, set()
    for _, _, role, h in candidates:
        if role not in found and h not in used:
            found[role], used = h, used | {h}
    return found


class SupplyData:
    """The five CSV files, read into rows with standard field names, and the three questions the
    tools answer. self.columns records which header each field came from, per file."""

    def __init__(self, data_dir=DEFAULT_ORG_DIR):
        self.folder = Path(data_dir)
        self.name = company_name(self.folder)
        self.columns = {}
        tables = {f: self._read(f) for f in CSV_FILES}
        self._fix_order_product(tables)
        for f, (headers, rows) in tables.items():
            missing = [r for r in FILE_ROLES[f][0] if r not in self.columns[f]]
            if missing:
                raise OrgError(f"{self.folder.name}/{f}: can't tell which column holds {', '.join(missing)} "
                               f"(headers: {', '.join(headers)}). Rename that column to one of the names "
                               f"in COLUMN_ROLES in supply_mcp_server.py.")

        def rows_of(f):
            cols = self.columns[f]
            out = []
            for r in tables[f][1]:
                row = {role: (r.get(h) or "").strip() for role, h in cols.items()}
                for role in WHOLE_NUMBERS & set(row):
                    row[role] = int(row[role])
                out.append(row)
            return out

        self.parts = {r["part_id"].upper(): r for r in rows_of("parts.csv")}
        self.bom = rows_of("bill-of-materials.csv")
        self.inbound = rows_of("inbound.csv")
        self.orders = rows_of("orders.csv")
        self.suppliers = rows_of("suppliers.csv")
        for o in self.orders:
            o.setdefault("customer", o["order_id"])
            o.setdefault("contact_email", "")
            o["late_penalty"] = str(o.get("late_penalty", "")).strip().lower() in {"yes", "y", "true", "1", "x"}
        for p in self.parts.values():
            p.setdefault("description", "")
            p.setdefault("supplier", "")

    def _read(self, filename):
        with open(self.folder / filename, newline="", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            headers = [h for h in (reader.fieldnames or []) if h]
        self.columns[filename] = match_columns(filename, headers, rows)
        return headers, rows

    def _fix_order_product(self, tables):
        """The orders' product column must hold products from the bill of materials. If the header match
        missed it or chose wrongly, take the column whose values best match the BOM's products."""
        bom_col = self.columns["bill-of-materials.csv"].get("product")
        if not bom_col:
            return
        products = {(r.get(bom_col) or "").strip().lower() for r in tables["bill-of-materials.csv"][1]}
        headers, rows = tables["orders.csv"]
        cols = self.columns["orders.csv"]

        def overlap(h):
            return sum((r.get(h) or "").strip().lower() in products for r in rows)

        current = cols.get("product")
        if current and overlap(current) > 0:
            return
        taken = {h for role, h in cols.items() if role != "product"}
        best = max((h for h in headers if h not in taken), key=overlap, default=None)
        if best and overlap(best) > 0:
            cols["product"] = best

    def describe_columns(self):
        """One line per file: field <- header (only where they differ, plus the four key fields)."""
        key = {"product", "quantity", "per_unit", "ship_day"}
        lines = []
        for f in CSV_FILES:
            cols = self.columns[f]
            shown = [f"{role}={h}" for role, h in cols.items() if role in key or norm(h) != role]
            lines.append(f"  {f}: " + (", ".join(shown) if shown else "standard names"))
        return "\n".join(lines)

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
            ({"po_number": r.get("po_number", ""), "supplier": r.get("supplier", p["supplier"]), "qty": r["quantity"],
              "day": r["arrival_day"]} for r in self.inbound if r["part_id"].upper() == key),
            key=lambda s: s["day"])
        return {
            "part_id": key,
            "description": p["description"],
            "supplier": p["supplier"],
            "on_hand": p["on_hand"],
            "scheduled_shipments": shipments,
            "used_in_products": [{"product": b["product"], "parts_per_unit": b["per_unit"]}
                                 for b in self.bom if b["part_id"].upper() == key],
        }

    # ------------------------------------------------------------ get_orders_for_part

    def get_orders_for_part(self, part_id):
        key = self._key(part_id)
        per_unit = {b["product"].lower(): b["per_unit"] for b in self.bom if b["part_id"].upper() == key}
        orders = [
            {
                "order_id": o["order_id"],
                "customer": o["customer"],
                "product": o["product"],
                "quantity": o["quantity"],
                "parts_per_unit": per_unit[o["product"].lower()],
                "units_needed": o["quantity"] * per_unit[o["product"].lower()],
                "ship_day": o["ship_day"],
                "late_penalty": o["late_penalty"],
            }
            for o in self.orders if o["product"].lower() in per_unit
        ]
        # Ship-day order; ties go to the lower order number.
        orders.sort(key=lambda o: (o["ship_day"], o["order_id"]))
        return {"part_id": key, "orders": orders}

    # ------------------------------------------------------------ check_coverage

    def check_coverage(self, part_id, arrivals):
        key = self._key(part_id)
        on_hand = self.parts[key]["on_hand"]

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
            row = {k: o[k] for k in ("order_id", "customer", "product", "quantity", "units_needed", "ship_day",
                                     "late_penalty")}
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
    example = next(iter(sorted(data.parts)), "P-1")
    server = MCPServer(
        name=f"{data.folder.name}-supply",
        instructions=f"{data.name} supply tools: parts, open orders, and order coverage. "
                     "Read-only; uses only local CSV files. Days are counted from today (day 0).",
        log_level="WARNING",
    )

    def safe(fn, *args):
        try:
            return fn(*args)
        except SupplyError as e:
            raise ToolError(str(e)) from None

    @server.tool(annotations=READ_ONLY, description=(
        f"Look up one part by part_id (e.g. {example}): its description, supplier, stock on hand today, its "
        "scheduled shipments (po_number, qty, day counted from today), and the products that use it "
        "with parts per unit."))
    def get_part(part_id: str) -> dict:
        return safe(data.get_part, part_id)

    @server.tool(annotations=READ_ONLY, description=(
        "List the open customer orders that need one part, in ship-day order. For each order: order_id, "
        "customer, product, quantity (units of the product ordered), parts_per_unit, units_needed (quantity x "
        "parts per unit), ship_day (days from today) and late_penalty (true if the contract has a penalty "
        "for shipping late)."))
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
        "(parts missing on its ship day), first_ship_day (null if the arrivals never cover it) and "
        "days_late. orders_short lists the orders that aren't covered."))
    def check_coverage(part_id: str, arrivals: list[Arrival]) -> dict:
        return safe(data.check_coverage, part_id, [a.model_dump() for a in arrivals])

    return server


# Coverage for each sample supplier email, worked out by hand from the email (no MCP, no Claude).
DEMO_SCENARIOS = {
    "brookfield-bikes": [
        ("Email 1, Northgate: MC-500, 120 on day 5 and 280 on day 26", "MC-500",
         [{"qty": 120, "day": 5}, {"qty": 280, "day": 26}]),
        ("Email 2, Kendall option 1: TR-29, 160 on day 8 and 240 on day 22", "TR-29",
         [{"qty": 160, "day": 8}, {"qty": 240, "day": 22}]),
        ("Email 2, Kendall option 2: TR-29, 400 on day 12", "TR-29", [{"qty": 400, "day": 12}]),
        ("Email 3, Keystone: BP-48 on schedule, 150 on day 6", "BP-48", [{"qty": 150, "day": 6}]),
    ],
    "copperline-coffee": [
        ("Email 1, Danforth: PU-20, 40 on day 4 and 160 on day 19", "PU-20",
         [{"qty": 40, "day": 4}, {"qty": 160, "day": 19}]),
    ],
}


def demo(data):
    """Print coverage under each part's current schedule, then for any sample-email scenarios above."""
    def show(title, part_id, arrivals):
        res = data.check_coverage(part_id, arrivals)
        print(f"\n{title}")
        for r in res["orders"]:
            status = "covered" if r["covered"] else \
                f"SHORT {r['units_short']}, first ship day {r['first_ship_day']} ({r['days_late']} days late)"
            print(f"  {r['order_id']} {r['customer']:<28} needs {r['units_needed']:>3}, ship day {r['ship_day']:>2}: "
                  f"{status}{'  [late penalty]' if r['late_penalty'] else ''}")

    print(f"{data.name} ({data.folder.name}): {len(data.parts)} parts, {len(data.orders)} orders.")
    print("Columns found:\n" + data.describe_columns())
    for part_id in sorted(data.parts):
        sched = [{"qty": s["qty"], "day": s["day"]} for s in data.get_part(part_id)["scheduled_shipments"]]
        show(f"{part_id}, current schedule: {sched}", part_id, sched)
    for title, part_id, arrivals in DEMO_SCENARIOS.get(data.folder.name, []):
        show(title, part_id, arrivals)


def main():
    parser = argparse.ArgumentParser(description="Supply MCP server for one company (stdio).")
    parser.add_argument("--org", "--data", dest="org", metavar="FOLDER",
                        help="company folder: a name inside week-05 or a path (default: brookfield-bikes)")
    parser.add_argument("--demo", action="store_true", help="print coverage for the sample emails, then exit")
    parser.add_argument("--columns", action="store_true", help="print which column holds each field, then exit")
    args = parser.parse_args()

    try:
        data = SupplyData(resolve_org(args.org))
    except OrgError as e:
        sys.exit(str(e))
    if args.demo:
        demo(data)
        return
    if args.columns:
        print(f"{data.name} ({data.folder}):\n" + data.describe_columns())
        return
    print(f"{data.name} supply server: {len(data.parts)} parts, {len(data.orders)} orders.", file=sys.stderr)
    build_server(data).run("stdio")


if __name__ == "__main__":
    main()
