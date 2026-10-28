# CLAUDE.md

Guidance for Claude Code when working in this repository.

## Course context

This is coursework for **GBUS 562: AI Language Models** at the University of Mary Washington. The work focuses on building software tools that use large language models (LLMs), mostly Claude via the Anthropic API.

## Repository layout

- The GitHub repo lives in the folder `UMW-GBUS-562` (this folder): `C:\Users\Dell\Desktop\GBUS-562-Course\UMW-GBUS-562`.
- Work is organized into weekly folders (`Week-01`, `Week-02`, …). Each week's work goes in its own folder.
- `Week-01/` holds last week's work: two single-page browser games (Connect Four and Ludo) built with HTML and JavaScript.
- When adding a new week's work, also update the **Weekly Work** section of `README.md`.

## Anthropic API key

- The Anthropic API key is stored **outside** the repo at:
  `C:\Users\Dell\Desktop\GBUS-562-Course\API-KEY.txt`
- Use this key whenever a project needs to connect to Claude.

### Keeping the key secure (mandatory)

- **NEVER commit, push or publish the API key to GitHub**, or anywhere else.
- Never copy the key into any file inside this repo, and never hardcode it in source code.
- Never print the key in terminal output, logs, commit messages, READMEs or chat responses.
- Programs should load the key at runtime, either by reading `../API-KEY.txt` (relative to the repo root) or from the `ANTHROPIC_API_KEY` environment variable.
- If a project needs a local secrets file (for example `.env`), make sure it is listed in `.gitignore` before creating it.
- Before every commit, check the staged changes (`git diff --cached`) to confirm no key or secrets file is included.
- Browser-only (HTML/JS) apps must not embed the key in client-side code, since anyone viewing the page could read it. Use a small local backend (for example Python) that holds the key instead.

## Building with Claude

- Default to the latest, most capable Claude models (currently the Claude 5 family, e.g. `claude-opus-5-5`).
- Prefer the official Anthropic SDK (`anthropic` for Python, `@anthropic-ai/sdk` for JavaScript).
