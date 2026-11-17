"""MCP server for an organization's HR team: policy search and leave balance lookup.

Works for any organization folder laid out like this (default: Week-04/hartwell-hr):
    <org>/hr-docs/            the HR policy documents
    <org>/employees.csv       one row per employee
    <org>/sample-emails/      example emails (used by agent.py, not by this server)
    <org>/system_prompt.txt   the agent's system prompt (used by agent.py)

The employee file's column names are not assumed. They are worked out from the header row:
the email column (a header with "email"/"e-mail"/"mail" in it, or else the column whose values
look like addresses), the name column, and the balance columns (numeric columns whose header
mentions days, hours, PTO, vacation, sick, personal, leave, remaining, left, balance...).

Tools:
- search_policy(query): the 4 HR document sections closest to the query, with source files.
- get_leave_balance: one employee's leave balances.
    Default (HR staff) mode:  get_leave_balance(employee_email)
    Employee mode:            started with --as-employee ADDRESS, the tool takes no inputs and
                              only ever returns that one employee's balance.

Usage (from the top of the repository):
    .venv\\Scripts\\python.exe Week-04\\hr_mcp_server.py                                   # Hartwell, HR staff mode
    .venv\\Scripts\\python.exe Week-04\\hr_mcp_server.py --org ridgeline-hotels            # another organization
    .venv\\Scripts\\python.exe Week-04\\hr_mcp_server.py --as-employee dana.whitfield@hartwellfoods.example
    .venv\\Scripts\\python.exe Week-04\\hr_mcp_server.py --org ridgeline-hotels --rebuild  # rebuild its search database

--org takes a folder name inside Week-04 or a path. Each organization has its own search
database in Week-04/chroma-db/<folder name>/ (kept out of Git).

The server talks MCP over stdin/stdout, so all its own messages go to stderr.
It reads only local files and never calls the Claude API, so it needs no API key.
"""

import argparse
import csv
import re
import sys
from email.utils import parseaddr
from pathlib import Path

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations

import hr_search

TOP_K = 4
READ_ONLY = ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=False)

BALANCE_WORDS = ("day", "days", "hour", "hours", "pto", "vacation", "holiday", "annual", "sick",
                 "personal", "leave", "remaining", "left", "balance", "available", "accrued", "floating")
NOT_BALANCE_WORDS = ("id", "number", "no", "phone", "zip", "postal", "year", "salary", "rate", "age")


def normalize_email(value):
    """Accept 'name@x', ' Name@X ' or 'Name <name@x>' and return 'name@x' (lowercase)."""
    address = parseaddr(value or "")[1].strip().lower()
    return address if "@" in address else ""


def words(header):
    return re.sub(r"[^a-z0-9]+", " ", header.lower()).split()


def snake(header):
    return "_".join(words(header)) or "column"


def to_number(value):
    value = (value or "").strip()
    if not re.fullmatch(r"-?\d+(\.\d+)?", value):
        raise ValueError(value)
    number = float(value)
    return int(number) if number.is_integer() else number


def org_display_name(org_dir):
    """The organization's name from its system prompt ("... assistant for Ridgeline Hotels."),
    or else from the folder name."""
    try:
        prompt = (org_dir / "system_prompt.txt").read_text(encoding="utf-8")
        m = re.search(r"\bfor ([A-Z][\w&'-]*(?: [A-Z][\w&'-]*)*)", prompt)
        if m:
            return m.group(1)
    except OSError:
        pass
    return org_dir.name.replace("-", " ").replace("_", " ").title()


class EmployeeFile:
    """Reads employees.csv and works out which columns hold the email, name and balances."""

    def __init__(self, path):
        self.path = path
        with path.open(newline="", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            self.headers = [h for h in (reader.fieldnames or []) if h is not None]
            rows = list(reader)
        if not self.headers:
            raise SystemExit(f"{path} has no header row.")

        def values(h):
            return [(r.get(h) or "").strip() for r in rows]

        # Email column: by header name, otherwise the column whose values look like addresses.
        by_name = [h for h in self.headers
                   if {"email", "mail", "emailaddress"} & set(words(h)) or "e mail" in " ".join(words(h))]
        by_values = [h for h in self.headers
                     if rows and sum("@" in v for v in values(h)) >= max(1, len(rows) // 2)]
        email_cols = by_name or by_values
        if not email_cols:
            raise SystemExit(f"Could not find an email column in {path.name} (headers: {', '.join(self.headers)}).")
        self.email_col = email_cols[0]

        # Name column: a header with "name" in it (not user name / manager / supervisor name).
        name_cols = [h for h in self.headers if "name" in words(h) and h != self.email_col
                     and not {"user", "manager", "supervisor", "file"} & set(words(h))]
        self.name_col = name_cols[0] if name_cols else None

        # Balance columns: numeric values and a header that talks about leave.
        self.balance_cols = []
        for h in self.headers:
            if h in (self.email_col, self.name_col):
                continue
            w = set(words(h))
            if not (w & set(BALANCE_WORDS)) or (w & set(NOT_BALANCE_WORDS)):
                continue
            vals = [v for v in values(h) if v]
            if vals and all(re.fullmatch(r"-?\d+(\.\d+)?", v) for v in vals):
                self.balance_cols.append(h)
        if not self.balance_cols:
            raise SystemExit(f"Could not find any leave balance columns in {path.name} "
                             f"(headers: {', '.join(self.headers)}).")

    def describe(self):
        return ", ".join(self.balance_cols)

    def lookup(self, email):
        address = normalize_email(email)
        if not address:
            raise not_found(f"'{email}' (not a valid email address)")
        with self.path.open(newline="", encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                if (row.get(self.email_col) or "").strip().lower() != address:
                    continue
                result = {"email": address}
                if self.name_col:
                    result["name"] = (row.get(self.name_col) or "").strip()
                try:
                    for h in self.balance_cols:
                        result[snake(h)] = to_number(row.get(h))
                except ValueError:
                    raise ToolError(
                        f"The leave record for {address} is incomplete or unreadable. Do not state "
                        "any balance; tell the sender a person from HR will follow up."
                    )
                result["source"] = self.path.name
                return result
        raise not_found(address)


def not_found(what):
    return ToolError(
        f"No employee record matches {what}. Do not state any leave balance, number of days, "
        "or estimate for this person. Tell the sender that HR could not find their leave record "
        "and that a person from HR will follow up."
    )


def build_server(org_dir, employees, as_employee=None):
    collection = hr_search.open_collection(org_dir)
    org_name = org_display_name(org_dir)
    balances = employees.describe()

    server = MCPServer(
        name=org_dir.name,
        instructions=f"{org_name} HR tools: search the HR policy documents and look up leave balances. "
                     "Read-only; uses only local files.",
        log_level="WARNING",
    )

    search_description = (
        f"Search {org_name}'s HR policy documents.\n\n"
        "Returns the 4 document sections closest to the query. Each result has its rank, a similarity score "
        "from 0 to 1 (higher is closer; scores below about 0.35 usually mean the policies don't cover the "
        "question), the source file, the document title and version, the section heading, and the full "
        "section text.\n\nUse only these results for policy facts, and cite the source file for each fact."
    )

    @server.tool(description=search_description, annotations=READ_ONLY)
    def search_policy(query: str) -> dict:
        if not query or not query.strip():
            raise ToolError("The search query is empty. Pass the policy question or topic to search for.")
        return {"query": query, "results": hr_search.search(collection, query, TOP_K)}

    if as_employee:
        address = normalize_email(as_employee)

        def get_leave_balance() -> dict:
            return employees.lookup(address or as_employee)

        server.add_tool(
            get_leave_balance,
            name="get_leave_balance",
            description=(
                f"Look up the leave balances ({balances}) of the employee this assistant is serving, "
                f"{address or as_employee}, from {employees.path.name}. Takes no inputs. This is the only "
                "balance available; balances of other employees cannot be looked up. If no record matches, "
                "the tool returns an error, and you must not state any balance."
            ),
            annotations=READ_ONLY,
        )
    else:
        def get_leave_balance(employee_email: str) -> dict:
            return employees.lookup(employee_email)

        server.add_tool(
            get_leave_balance,
            name="get_leave_balance",
            description=(
                f"Look up one employee's leave balances ({balances}) by their work email address, from "
                f"{employees.path.name}.\n\nPass the exact email address of the employee whose balance you need "
                "(for an email, the sender's address). One employee per call. If no record matches, the tool "
                "returns an error, and you must not state any balance for that person."
            ),
            annotations=READ_ONLY,
        )
    return server


def main():
    parser = argparse.ArgumentParser(description="HR MCP server (stdio) for one organization.")
    parser.add_argument("--org", metavar="FOLDER",
                        help="organization folder (a name inside Week-04, or a path); default: hartwell-hr")
    parser.add_argument("--as-employee", metavar="EMAIL",
                        help="serve one employee: get_leave_balance takes no inputs and returns only this "
                             "employee's balance")
    parser.add_argument("--rebuild", action="store_true",
                        help="rebuild the organization's HR document search database, then exit")
    args = parser.parse_args()

    org_dir = hr_search.resolve_org(args.org)
    if args.rebuild:
        hr_search.build_database(org_dir)
        return

    employees = EmployeeFile(org_dir / "employees.csv")
    hr_search.log(f"Organization: {org_dir.name}. {employees.path.name}: email column '{employees.email_col}', "
                  f"balance columns: {employees.describe()}.")
    if args.as_employee:
        try:
            employees.lookup(args.as_employee)
            hr_search.log(f"Employee mode: get_leave_balance is limited to {normalize_email(args.as_employee)}.")
        except ToolError:
            hr_search.log(f"Warning: no employee record matches --as-employee {args.as_employee!r}; "
                          "get_leave_balance will return an error.")

    build_server(org_dir, employees, args.as_employee).run("stdio")


if __name__ == "__main__":
    main()
