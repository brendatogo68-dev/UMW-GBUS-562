"""MCP server for Hartwell Foods HR: policy search and leave balance lookup.

Tools:
- search_policy(query): the 4 HR document sections closest to the query, with source files.
- get_leave_balance: an employee's vacation, sick and personal days left (from employees.csv).
    Default (HR staff) mode:  get_leave_balance(employee_email)
    Employee mode:            started with --as-employee ADDRESS, the tool takes no inputs and
                              only ever returns that one employee's balance.

Usage (from the top of the repository):
    .venv\\Scripts\\python.exe Week-04\\hr_mcp_server.py                         # HR staff mode (stdio)
    .venv\\Scripts\\python.exe Week-04\\hr_mcp_server.py --as-employee dana.whitfield@hartwellfoods.example
    .venv\\Scripts\\python.exe Week-04\\hr_mcp_server.py --rebuild               # rebuild the search database, then exit

The server talks MCP over stdin/stdout, so all its own messages go to stderr.
It reads only local files and never calls the Claude API, so it needs no API key.
"""

import argparse
import csv
import sys
from email.utils import parseaddr
from pathlib import Path

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations

import hr_search

SCRIPT_DIR = Path(__file__).resolve().parent
EMPLOYEES_CSV = SCRIPT_DIR / "hartwell-hr" / "employees.csv"
TOP_K = 4

READ_ONLY = ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=False)

SEARCH_DESCRIPTION = """Search Hartwell Foods' HR policy documents (leave, parental and family leave, remote work, benefits, reporting workplace concerns).

Returns the 4 document sections closest to the query. Each result has its rank, a similarity score from 0 to 1 (higher is closer; scores below about 0.35 usually mean the policies don't cover the question), the source file, the document title and version, the section heading, and the full section text.

Use only these results for policy facts, and cite the source file for each fact."""

HR_BALANCE_DESCRIPTION = """Look up one employee's leave balance by their work email address: vacation, sick and personal days left, from employees.csv.

Pass the exact email address of the employee whose balance you need (for an email, the sender's address). One employee per call. If no record matches, the tool returns an error, and you must not state any balance for that person."""


def normalize_email(value):
    """Accept 'name@x', ' Name@X ' or 'Name <name@x>' and return 'name@x' (lowercase)."""
    address = parseaddr(value or "")[1].strip().lower()
    return address if "@" in address else ""


def not_found(what):
    return ToolError(
        f"No employee record matches {what}. Do not state any leave balance, number of days, "
        "or estimate for this person. Tell the sender that HR could not find their leave record "
        "and that a person from HR will follow up."
    )


def lookup_balance(email):
    address = normalize_email(email)
    if not address:
        raise not_found(f"'{email}' (not a valid email address)")
    with EMPLOYEES_CSV.open(newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            if (row.get("email") or "").strip().lower() == address:
                try:
                    return {
                        "email": address,
                        "name": row["name"],
                        "department": row["department"],
                        "vacation_days_left": int(row["vacation_days_left"]),
                        "sick_days_left": int(row["sick_days_left"]),
                        "personal_days_left": int(row["personal_days_left"]),
                        "source": EMPLOYEES_CSV.name,
                    }
                except (KeyError, ValueError):
                    raise ToolError(
                        f"The leave record for {address} is incomplete or unreadable. Do not state "
                        "any balance; tell the sender a person from HR will follow up."
                    )
    raise not_found(address)


def build_server(as_employee=None):
    collection = hr_search.open_collection()

    server = MCPServer(
        name="hartwell-hr",
        instructions="Hartwell Foods HR tools: search the HR policy documents and look up leave balances. "
                     "Read-only; uses only local files.",
        log_level="WARNING",
    )

    @server.tool(description=SEARCH_DESCRIPTION, annotations=READ_ONLY)
    def search_policy(query: str) -> dict:
        if not query or not query.strip():
            raise ToolError("The search query is empty. Pass the policy question or topic to search for.")
        return {"query": query, "results": hr_search.search(collection, query, TOP_K)}

    if as_employee:
        address = normalize_email(as_employee)

        def get_leave_balance() -> dict:
            return lookup_balance(address or as_employee)

        server.add_tool(
            get_leave_balance,
            name="get_leave_balance",
            description=(
                f"Look up the leave balance (vacation, sick and personal days left) of the employee this "
                f"assistant is serving, {address or as_employee}. Takes no inputs. This is the only balance "
                "available; balances of other employees cannot be looked up. If no record matches, the tool "
                "returns an error, and you must not state any balance."
            ),
            annotations=READ_ONLY,
        )
    else:
        def get_leave_balance(employee_email: str) -> dict:
            return lookup_balance(employee_email)

        server.add_tool(get_leave_balance, name="get_leave_balance",
                        description=HR_BALANCE_DESCRIPTION, annotations=READ_ONLY)
    return server


def main():
    parser = argparse.ArgumentParser(description="Hartwell Foods HR MCP server (stdio).")
    parser.add_argument("--as-employee", metavar="EMAIL",
                        help="serve one employee: get_leave_balance takes no inputs and returns only this "
                             "employee's balance")
    parser.add_argument("--rebuild", action="store_true",
                        help="rebuild the HR document search database, then exit")
    args = parser.parse_args()

    if args.rebuild:
        hr_search.build_database()
        return

    if args.as_employee:
        try:
            lookup_balance(args.as_employee)
            hr_search.log(f"Employee mode: get_leave_balance is limited to {normalize_email(args.as_employee)}.")
        except ToolError:
            hr_search.log(f"Warning: no employee record matches --as-employee {args.as_employee!r}; "
                          "get_leave_balance will return an error.")

    build_server(args.as_employee).run("stdio")


if __name__ == "__main__":
    main()
