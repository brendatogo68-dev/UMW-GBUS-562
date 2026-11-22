"""MCP server for Brookfield Bicycle Company's supply data (read-only, local CSV files only).

Tools (all built on supply_data.py, so the math is plain Python, never Claude):
- get_part(part_id): stock on hand, scheduled inbound shipments, and the bike models that use the part.
- get_orders_for_part(part_id): the open customer orders that need the part, earliest ship date first.
- check_coverage(part_id, po_number?, new_schedule?): which orders ship on time under a delivery schedule.

The supply analyst in specialists.py starts this server over stdio, the same way the Week 4 agent
started hr_mcp_server.py. It can also be started by hand to check that it loads:
    .venv\\Scripts\\python.exe week-05\\supply_mcp_server.py

The server talks MCP over stdin/stdout, so its own messages go to stderr. It never calls the
Claude API and needs no API key.
"""

import argparse
import sys
from pathlib import Path

from pydantic import BaseModel, Field
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations

from supply_data import DATA_DIR, SupplyData, SupplyError

READ_ONLY = ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=False)


class Delivery(BaseModel):
    qty: int = Field(description="Units in this delivery.")
    arrives_in_days: int = Field(description="Day the delivery arrives, counted from today (today is day 0).")


def build_server(data):
    server = MCPServer(
        name="brookfield-supply",
        instructions="Brookfield Bicycle Company supply tools: parts, open orders and coverage. "
                     "Read-only; uses only local files.",
        log_level="WARNING",
    )

    def safe(fn, *args):
        try:
            return fn(*args)
        except SupplyError as e:
            raise ToolError(str(e)) from None

    @server.tool(annotations=READ_ONLY, description=(
        "Look up one part: its description, units on hand today, its supplier, its scheduled inbound "
        "shipments (purchase order number, quantity, arrives_in_days counted from today), and the bike "
        "models that use it."))
    def get_part(part_id: str) -> dict:
        return safe(data.get_part, part_id)

    @server.tool(annotations=READ_ONLY, description=(
        "List the open customer orders that need one part, earliest ship date first. For each order: "
        "order_id, customer, model, bikes, parts_needed (bikes x parts per bike), ship_day (days from today) "
        "and late_penalty (true if the customer contract has a penalty for shipping late)."))
    def get_orders_for_part(part_id: str) -> dict:
        return safe(data.get_orders_for_part, part_id)

    @server.tool(annotations=READ_ONLY, description=(
        "Work out which orders for a part can ship on time under a delivery schedule. Use this for every "
        "coverage question; never work coverage out yourself.\n\n"
        "Without po_number and new_schedule, it checks the current schedule. To test a change from a "
        "supplier, give the purchase order number and new_schedule: the deliveries that replace that "
        "order's shipment, each with qty and arrives_in_days counted from today (convert phrases such as "
        "'three weeks after the scheduled date' to days from today first). Stock on hand and other "
        "shipments stay as they are. To compare options, call once per option.\n\n"
        "Rule: parts go to orders by earliest ship date, and an order ships only when complete. Returns "
        "every order with ready_day and on_time, and orders_at_risk with units_short and days_late. "
        "ready_day null means no scheduled delivery covers the order."))
    def check_coverage(part_id: str, po_number: str | None = None,
                       new_schedule: list[Delivery] | None = None) -> dict:
        schedule = None if new_schedule is None else [d.model_dump() for d in new_schedule]
        return safe(data.check_coverage, part_id, po_number, schedule)

    return server


def main():
    parser = argparse.ArgumentParser(description="Brookfield supply MCP server (stdio).")
    parser.add_argument("--data", metavar="FOLDER", default=str(DATA_DIR),
                        help="folder with the five CSV files (default: week-05/brookfield-bikes)")
    args = parser.parse_args()
    data = SupplyData(Path(args.data))
    print(f"Brookfield supply server: {len(data.parts)} parts, {len(data.orders)} orders.", file=sys.stderr)
    build_server(data).run("stdio")


if __name__ == "__main__":
    main()
