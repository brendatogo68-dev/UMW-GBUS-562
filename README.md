# UMW-GBUS-562
Repository for GBUS 562 (AI Language Models)

## About

This repository contains coursework, notes, and project materials developed for **GBUS 562: AI Language Models** at the University of Mary Washington (UMW). It documents hands-on work with large language models and their applications in business.

Materials are organized into weekly folders (for example, `Week-01`, `Week-02`, …), with each folder holding the content, exercises, and deliverables for that week of the course.

## Weekly Work

1. [Week-01](Week-01/): two single-page browser games built with HTML and JavaScript.
   - **Connect Four**: play against a computer opponent that uses a minimax search with alpha-beta pruning (Easy, Medium or Hard), or switch to 2 Players to take turns on the same device.
   - **Ludo**: a modern take on the classic board game for 2–4 players, human or computer. Computer opponents come in three difficulty levels (Easy, Medium or Hard) and play strategically around token captures. Includes animated dice rolls and moves, save and load, customizable player names and colors, and an optional 2 vs 2 team mode.
2. [Week-02](Week-02/): a Prompt Lab web app for testing prompts against Claude, built with Claude Code.
   - **Prompt Lab** (`prompt-lab.html`): a single-file browser app that sends prompts to Claude Sonnet 5 through the Anthropic API, keeps a labeled conversation log, and exports conversations as Markdown.
   - **Prompt runs** (`runs/task-1.md` – `runs/task-4.md`): exported conversations for four Wildframe Coffee Roasters tasks.
   - **Write-up** (`writeup.md`): explains the four prompting techniques used (zero-shot, one-shot, few-shot and chain-of-thought) and reflects on the results.
3. [Week-03](Week-03/): a RAG tool that answers questions from Copperline Manufacturing's finance documents, built with Claude Code.
   - **RAG tool** (`ask.py`): a Python command-line tool that splits documents (HTML, PDF, Markdown, text and Word) into one chunk per section, stores them in a local Chroma database, retrieves the 4 most relevant chunks for each question, and has Claude Sonnet 5 answer only from those sources with a citation for every fact. Options: `--docs` to choose a document folder (each gets its own database), `--save` to save a run to a text file, and `--rebuild` after adding or removing documents.
   - **Documents** (`copperline-docs/`, `larkfield-docs/`): finance policies for Copperline Manufacturing and member-service policies for Larkfield Credit Union. Outdated versions are kept in the matching `-archive` folders so they are not indexed.
   - **Runs** (`runs/q1-before.txt` – `runs/q6.txt`): nine saved runs against the Larkfield documents, including before/after comparisons for removing an outdated fee schedule and for tightening Claude's instructions.
   - **Write-up** (`writeup.md`): what was built, the structure-based chunking approach, an example run, and a reflection on the outdated-document problem and an out-of-scope question.
4. [Week-04](Week-04/): an AI agent that prepares replies to HR emails using tools from an MCP server, built with Claude Code.
   - **Write-up** (`writeup.md`): what was built and the changes for Ridgeline Hotels, the script/model-call/agent choices for Tasks A–C, an example run (Email 6) and a reflection on Emails 3, 6 and 7.
5. [Week 5](week-05/): a team of AI agents that prepares a bicycle maker's response to supplier emails, built with Claude Code.
   - **Specialists** (`specialists.py`): a supply analyst that uses data tools from an MCP server (`supply_mcp_server.py`), a writer for supplier replies, a writer for customer notices, and a reviewer that checks every draft (one revision allowed). Code checks the analyst's brief against the tool results and gives each writer only the facts it should see.
   - **Coordinators**: a fixed pipeline (`pipeline.py`) that always runs the same steps, and an orchestrator agent (`orchestrator.py`) that chooses which specialists each email needs. Both take `--email FILE`, plus `--save LOG.txt` to keep a copy of everything printed.
   - **MCP server** (`supply_mcp_server.py`): reads the CSV files in `brookfield-bikes/` (parts, inbound shipments, orders, bill of materials, suppliers) and offers `get_part`, `get_orders_for_part` and `check_coverage`. Coverage is plain Python: a new list of arrivals replaces the part's scheduled shipments, and orders are filled complete in ship-day order, so a short order holds up the ones after it.
   - **Outputs** (`drafts/`, `runs/`): the drafts, analyst briefs, summaries and run logs for the three supplier emails, from both coordinators. Nothing is sent.
