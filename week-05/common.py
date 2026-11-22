"""Shared helpers for the Brookfield agent team (adapted from Week-04/agent.py).

- load_api_key(): ANTHROPIC_API_KEY, else ../API-KEY.txt outside the repo (never printed or saved).
- parse_email(): one .eml file into sender, subject and body.
- call_claude(): one Messages API request with the team's model settings, counting tokens.
- run_tool_loop(): the Week 4 tool-use loop, made general: any tools, any handler, a tool-call limit.
- Tee: copy everything printed to a run log file.
"""

import json
import os
import re
import sys
from email import policy
from email.parser import BytesParser
from email.utils import parseaddr
from pathlib import Path

import anthropic

MODEL = "claude-opus-5-5"
# Server-side refusal fallback (beta): if the model declines, the API re-runs the request on a
# fallback model in the same call. "default" lets the API pick the fallback by refusal category.
FALLBACK_BETA = "server-side-fallback-2026-07-01"

WEEK_DIR = Path(__file__).resolve().parent
REPO_ROOT = WEEK_DIR.parent
DATA_DIR = WEEK_DIR / "brookfield-bikes"
PROMPTS_DIR = DATA_DIR / "prompts"
EMAILS_DIR = DATA_DIR / "supplier-emails"
DRAFTS_DIR = WEEK_DIR / "drafts"
RUNS_DIR = WEEK_DIR / "runs"
API_KEY_FILE = REPO_ROOT.parent / "API-KEY.txt"
PREVIEW_CHARS = 300


class Tee:
    """Write everything printed to the console and to a UTF-8 file."""

    def __init__(self, console, file):
        self.console, self.file = console, file

    def write(self, text):
        self.console.write(text)
        self.file.write(text)
        return len(text)

    def flush(self):
        self.console.flush()
        self.file.flush()

    def __getattr__(self, name):
        return getattr(self.console, name)


def utf8_console():
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except AttributeError:
            pass


def load_api_key():
    key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not key and API_KEY_FILE.exists():
        key = API_KEY_FILE.read_text(encoding="utf-8").strip()
    if not key:
        sys.exit(f"No API key found. Put it in {API_KEY_FILE} or set ANTHROPIC_API_KEY.")
    return key


def make_client():
    return anthropic.AsyncAnthropic(api_key=load_api_key())


def load_prompt(name):
    # Re-read on every run so edits to a prompt take effect immediately.
    return (PROMPTS_DIR / f"{name}.txt").read_text(encoding="utf-8").strip()


def parse_email(path):
    msg = BytesParser(policy=policy.default).parsebytes(Path(path).read_bytes())
    body_part = msg.get_body(preferencelist=("plain", "html"))
    body = body_part.get_content() if body_part else ""
    if body_part is not None and body_part.get_content_type() == "text/html":
        body = re.sub(r"<[^>]+>", " ", body)
    return {
        "file": Path(path).name,
        "stem": Path(path).stem,
        "sender": parseaddr(str(msg.get("From", "")))[1].strip().lower(),
        "from_header": str(msg.get("From", "")),
        "subject": str(msg.get("Subject", "")),
        "body": body.strip(),
    }


def email_block(email):
    return (f"<supplier_email>\nFrom: {email['from_header']}\nSubject: {email['subject']}\n\n"
            f"{email['body']}\n</supplier_email>")


def preview(text, limit=PREVIEW_CHARS):
    text = " ".join(str(text).split())
    return text if len(text) <= limit else text[:limit] + "..."


def response_text(response):
    return "\n".join(b.text for b in response.content if b.type == "text").strip()


class Usage:
    """Token totals for one run, per role."""

    def __init__(self):
        self.by_role = {}

    def add(self, role, usage):
        i = (usage.input_tokens or 0) + (usage.cache_creation_input_tokens or 0) + (usage.cache_read_input_tokens or 0)
        o = usage.output_tokens or 0
        a, b = self.by_role.get(role, (0, 0))
        self.by_role[role] = (a + i, b + o)

    def report(self):
        lines = [f"  {role:<16} {i:>7} input, {o:>6} output" for role, (i, o) in self.by_role.items()]
        ti = sum(i for i, _ in self.by_role.values())
        to = sum(o for _, o in self.by_role.values())
        return "\n".join(lines + [f"  {'total':<16} {ti:>7} input, {to:>6} output"])


async def call_claude(client, usage, role, system, messages, effort="medium", tools=None, max_tokens=16000):
    """One Messages API request. Thinking is adaptive (always on for Opus 5.5); effort sets its depth."""
    kwargs = {}
    if tools:
        kwargs["tools"] = tools
    response = await client.beta.messages.create(
        model=MODEL,
        max_tokens=max_tokens,
        system=system,
        messages=messages,
        thinking={"type": "adaptive"},
        output_config={"effort": effort},
        betas=[FALLBACK_BETA],
        fallbacks="default",
        **kwargs,
    )
    usage.add(role, response.usage)
    if response.stop_reason == "refusal":
        raise RuntimeError(f"{role}: Claude declined the request (stop_reason: refusal).")
    if response.stop_reason == "max_tokens":
        raise RuntimeError(f"{role}: the reply hit the max_tokens limit.")
    return response


async def run_tool_loop(client, usage, role, system, first_message, tools, handle_tool,
                        max_tool_calls=10, effort="medium", stop_after=None):
    """The Week 4 loop: ask Claude, run each tool it requests, send results back, repeat.

    handle_tool(name, input) -> (text, is_error); it may be async.
    stop_after: a tool name that ends the loop once it succeeds (e.g. the orchestrator's finish).
    Returns (final_text, tool_calls, stop_why, messages).
    """
    messages = [{"role": "user", "content": first_message}]
    calls, stop_why, final_text = 0, None, ""
    while stop_why is None:
        response = await call_claude(client, usage, role, system, messages, effort=effort, tools=tools)
        text = response_text(response)
        if text:
            print(f"  [{role}] {preview(text)}")
        # Keep the full content (including thinking blocks) in the history, unchanged.
        messages.append({"role": "assistant", "content": response.content})
        if response.stop_reason != "tool_use":
            final_text = text
            stop_why = f"{role} finished (stop_reason: {response.stop_reason})."
            break

        results = []
        for block in response.content:
            if block.type != "tool_use":
                continue
            if calls >= max_tool_calls:
                results.append({"type": "tool_result", "tool_use_id": block.id, "is_error": True,
                                "content": f"Tool-call limit of {max_tool_calls} reached; not run."})
                stop_why = f"{role} reached the limit of {max_tool_calls} tool calls."
                continue
            calls += 1
            print(f"  {role} step {calls}: {block.name} {json.dumps(block.input, ensure_ascii=False)}")
            try:
                out = handle_tool(block.name, block.input or {})
                if hasattr(out, "__await__"):
                    out = await out
                text, is_error = out
            except Exception as e:  # report tool failures back to Claude instead of crashing
                text, is_error = f"Tool failed: {e}", True
            print(f"    -> {'(error) ' if is_error else ''}{preview(text)}")
            results.append({"type": "tool_result", "tool_use_id": block.id, "content": text, "is_error": is_error})
            if stop_after and block.name == stop_after and not is_error:
                stop_why = f"{role} called {stop_after}."
        messages.append({"role": "user", "content": results})
    return final_text, calls, stop_why, messages


def parse_json_block(text):
    """The last JSON object in a reply (with or without ```json fences)."""
    candidates = re.findall(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if not candidates and "{" in text:
        candidates = [text[text.find("{"): text.rfind("}") + 1]]
    for c in reversed(candidates):
        try:
            return json.loads(c)
        except json.JSONDecodeError:
            continue
    raise ValueError("No valid JSON object found in the reply.")


def run_cli(description, coordinator, run_one):
    """Command line shared by pipeline.py and orchestrator.py.

    --email FILE handles one supplier email; --all handles every .eml in brookfield-bikes/supplier-emails/.
    Each email's console output is also saved to week-05/runs/<email>-<coordinator>.txt.
    run_one(client, email_path) is the coordinator's async function for one email.
    """
    import argparse
    import asyncio

    utf8_console()
    parser = argparse.ArgumentParser(description=description)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--email", help="path of one supplier email (.eml)")
    source.add_argument("--all", action="store_true", help="handle every email in brookfield-bikes/supplier-emails/")
    args = parser.parse_args()

    paths = sorted(EMAILS_DIR.glob("*.eml")) if args.all else [Path(args.email)]
    for p in paths:
        if not p.is_file():
            sys.exit(f"Email file not found: {p}")

    async def main():
        client = make_client()
        for p in paths:
            RUNS_DIR.mkdir(exist_ok=True)
            log_path = RUNS_DIR / f"{p.stem}-{coordinator}.txt"
            console = sys.stdout
            with open(log_path, "w", encoding="utf-8") as log:
                sys.stdout = Tee(console, log)
                try:
                    await run_one(client, p)
                finally:
                    sys.stdout.flush()
                    sys.stdout = console
            print(f"Run log saved to {log_path.relative_to(REPO_ROOT)}\n")

    asyncio.run(main())
