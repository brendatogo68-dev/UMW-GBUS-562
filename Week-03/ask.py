"""Ask questions about Copperline Manufacturing's finance documents (RAG with Chroma + Claude).

Usage (from the top of the repository):
    .venv\\Scripts\\python.exe Week-03\\ask.py "What is the hotel limit in Boston?"
    .venv\\Scripts\\python.exe Week-03\\ask.py              # ask questions one after another
    .venv\\Scripts\\python.exe Week-03\\ask.py --rebuild    # re-read the documents after adding or removing files

The documents live in Week-03/copperline-docs. Supported file types: HTML, PDF, Markdown,
plain text and Word (.docx). Each document is split into one chunk per section heading,
and every chunk starts with its document title and section heading.
"""

import argparse
import hashlib
import os
import re
import sys
from collections import Counter
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
DOCS_DIR = SCRIPT_DIR / "copperline-docs"
DB_DIR = SCRIPT_DIR / "chroma-db"
# The key file sits in the folder that contains the repository, outside Git.
KEY_FILE = SCRIPT_DIR.parent.parent / "API-Key.txt"

COLLECTION = "copperline_docs"
MODEL = "claude-sonnet-5"
TOP_K = 4
PREVIEW_CHARS = 150
# Chroma's built-in embedding model (all-MiniLM-L6-v2) only reads about the first 256 tokens
# of a chunk, so longer sections are split into parts of at most this many words.
MAX_WORDS = 180

SUPPORTED = {".html", ".htm", ".pdf", ".md", ".markdown", ".txt", ".docx"}

# Some sections rely on a definition that appears in a different section of the same
# document. These notes are added to those chunks so they make sense on their own.
# Keys are file names, then section headings.
CONTEXT_NOTES = {
    "travel-expense-policy.html": {
        "Hotels": "Tier 1 cities are New York, San Francisco, Boston, Chicago, Washington DC, "
                  "Los Angeles, and Seattle. Tier 2 cities are every other city in the United States.",
    },
    "month-end-close-calendar.html": {
        heading: "Deadlines are counted in business days. Business day 1 is the first business day "
                 "of the new month. Business day minus 1 is the last business day of the month being closed."
        for heading in (
            "Deadlines for all employees before month end",
            "Accounts Payable cutoff",
            "Accruals for goods and services not yet invoiced",
            "Controller's Office close tasks",
        )
    },
}

SYSTEM_PROMPT = """You answer employees' questions about Copperline Manufacturing's finance documents.

Rules:
- Answer only from the sources in the user's message. Do not use outside knowledge or make assumptions beyond what the sources say.
- After every fact, cite the source file it came from in square brackets, for example [travel-expense-policy.html].
- If the sources do not contain the answer, say plainly that the documents provided do not cover it. If they answer only part of the question, answer that part and say which part is not covered.
- Keep the answer short and direct."""


# ---------------------------------------------------------------------------
# Reading documents into sections
# ---------------------------------------------------------------------------
# Every reader returns (title, doc_info, sections), where each section is a dict with
# "heading", "blocks" (a list of paragraph strings) and "pages" (PDF page numbers, or empty).

def clean(text):
    return re.sub(r"\s+", " ", text).strip()


def new_section(heading, pages=None):
    return {"heading": heading, "blocks": [], "pages": pages or []}


def read_html(path):
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(path.read_text(encoding="utf-8", errors="replace"), "html.parser")
    for tag in soup(["script", "style", "nav", "noscript"]):
        tag.decompose()

    footer = soup.find("footer")
    footer_text = clean(footer.get_text(" ")) if footer else ""
    if footer:
        footer.decompose()

    h1 = soup.find("h1")
    if h1:
        title = clean(h1.get_text(" "))
    elif soup.title:
        title = clean(soup.title.get_text(" "))
    else:
        title = path.stem
    meta = soup.find(class_="meta")
    doc_info = clean(meta.get_text(" ")) if meta else ""
    if meta:
        meta.decompose()

    root = soup.find("main") or soup.body or soup
    content_tags = ["h2", "h3", "h4", "p", "ul", "ol", "table", "pre", "blockquote"]
    sections = [new_section("Overview")]
    current_h2 = None
    for el in root.find_all(content_tags):
        # Skip elements nested inside another content element; the outer one includes them.
        if el.find_parent(["p", "ul", "ol", "table", "pre", "blockquote"]):
            continue
        if el.name == "h2":
            current_h2 = clean(el.get_text(" "))
            sections.append(new_section(current_h2))
        elif el.name in ("h3", "h4"):
            heading = clean(el.get_text(" "))
            sections.append(new_section(f"{current_h2} > {heading}" if current_h2 else heading))
        elif el.name in ("ul", "ol"):
            items = [clean(li.get_text(" ")) for li in el.find_all("li", recursive=False)]
            sections[-1]["blocks"].append("\n".join(f"- {item}" for item in items if item))
        elif el.name == "table":
            rows = []
            for tr in el.find_all("tr"):
                cells = [clean(c.get_text(" ")) for c in tr.find_all(["th", "td"])]
                rows.append(" | ".join(cells))
            sections[-1]["blocks"].append("\n".join(rows))
        else:
            text = clean(el.get_text(" "))
            if text:
                sections[-1]["blocks"].append(text)

    if footer_text:
        contact = new_section("Contact")
        contact["blocks"].append(footer_text)
        sections.append(contact)
    return title, doc_info, sections


def read_pdf(path):
    """Find headings by font: body text is the most common font size, and section headings
    are bold lines in the smallest size above it. Smaller text (page footers) is dropped."""
    import pymupdf

    doc = pymupdf.open(path)
    lines = []  # (page, size, bold, text, starts_new_block)
    for page_no, page in enumerate(doc, start=1):
        for block in page.get_text("dict")["blocks"]:
            first = True
            for line in block.get("lines", []):
                spans = [s for s in line["spans"] if s["text"].strip()]
                if not spans:
                    continue
                text = "".join(s["text"] for s in spans).strip()
                size = round(max(s["size"] for s in spans), 1)
                bold = all(s["flags"] & 16 for s in spans)
                lines.append((page_no, size, bold, text, first))
                first = False

    if not lines:
        return path.stem, "", []

    sizes = Counter()
    for _, size, _, text, _ in lines:
        sizes[size] += len(text)
    body = sizes.most_common(1)[0][0]
    heading_sizes = sorted({size for _, size, bold, _, _ in lines if size > body and bold})
    section_size = heading_sizes[0] if heading_sizes else None

    title = (doc.metadata or {}).get("title") or path.stem
    doc_info_parts = []
    sections = []
    for page_no, size, bold, text, starts_block in lines:
        if size < body:
            continue  # page headers/footers and fine print
        if section_size and bold and size > section_size:
            if not sections:
                title = text  # the last large heading before the first section is the title
                doc_info_parts = []
            continue
        if section_size and bold and size == section_size:
            sections.append(new_section(text, [page_no]))
            continue
        if not sections:
            doc_info_parts.append(text)
            continue
        section = sections[-1]
        if page_no not in section["pages"]:
            section["pages"].append(page_no)
        if starts_block or not section["blocks"]:
            section["blocks"].append(text)
        elif section["blocks"][-1].endswith("-"):
            section["blocks"][-1] += text
        else:
            section["blocks"][-1] += " " + text

    if not sections:  # no headings found: treat the whole document as one section
        whole = new_section(title, sorted({p for p, *_ in lines}))
        whole["blocks"] = doc_info_parts
        return title, "", [whole]
    return title, clean(" ".join(doc_info_parts)), sections


def read_markdown(path):
    title = path.stem
    sections = [new_section("Overview")]
    current_h2 = None
    paragraph = []

    def flush():
        if paragraph:
            sections[-1]["blocks"].append("\n".join(paragraph))
            paragraph.clear()

    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.rstrip()
        match = re.match(r"^(#{1,6})\s+(.*)", line)
        if match:
            flush()
            level, heading = len(match.group(1)), match.group(2).strip()
            if level == 1 and title == path.stem:
                title = heading
            elif level == 2 or (level >= 2 and current_h2 is None):
                current_h2 = heading
                sections.append(new_section(heading))
            elif level > 2:
                sections.append(new_section(f"{current_h2} > {heading}"))
        elif not line.strip():
            flush()
        else:
            paragraph.append(line.strip())
    flush()
    return title, "", sections


def read_text(path):
    text = path.read_text(encoding="utf-8", errors="replace")
    section = new_section(path.stem.replace("-", " ").replace("_", " ").title())
    section["blocks"] = [clean(p) for p in re.split(r"\n\s*\n", text) if p.strip()]
    return section["heading"], "", [section]


def read_docx(path):
    import docx

    document = docx.Document(path)
    title = document.core_properties.title or path.stem
    sections = [new_section("Overview")]
    current_h1 = None
    for para in document.paragraphs:
        text = clean(para.text)
        if not text:
            continue
        style = para.style.name if para.style is not None else ""
        if style == "Title":
            title = text
        elif style == "Heading 1":
            current_h1 = text
            sections.append(new_section(text))
        elif style.startswith("Heading"):
            sections.append(new_section(f"{current_h1} > {text}" if current_h1 else text))
        elif style.startswith("List"):
            sections[-1]["blocks"].append(f"- {text}")
        else:
            sections[-1]["blocks"].append(text)
    for table in document.tables:
        rows = [" | ".join(clean(cell.text) for cell in row.cells) for row in table.rows]
        tables = new_section("Table")
        tables["blocks"].append("\n".join(rows))
        sections.append(tables)
    return title, "", sections


READERS = {
    ".html": read_html, ".htm": read_html, ".pdf": read_pdf,
    ".md": read_markdown, ".markdown": read_markdown, ".txt": read_text, ".docx": read_docx,
}


# ---------------------------------------------------------------------------
# Turning sections into chunks
# ---------------------------------------------------------------------------

def split_blocks(blocks):
    """Group paragraphs into parts of at most MAX_WORDS words, splitting long paragraphs by sentence."""
    pieces = []
    for block in blocks:
        if len(block.split()) <= MAX_WORDS:
            pieces.append(block)
        else:
            pieces.extend(s for s in re.split(r"(?<=[.!?])\s+", block) if s)

    parts, current, words = [], [], 0
    for piece in pieces:
        n = len(piece.split())
        if current and words + n > MAX_WORDS:
            parts.append(current)
            current, words = [], 0
        current.append(piece)
        words += n
    if current:
        parts.append(current)
    return parts


def chunk_document(path):
    title, doc_info, sections = READERS[path.suffix.lower()](path)
    rel = path.relative_to(DOCS_DIR).as_posix()
    notes = CONTEXT_NOTES.get(path.name, {})
    chunks = []
    for section in sections:
        blocks = [b for b in section["blocks"] if b.strip()]
        if not blocks:
            continue
        parts = split_blocks(blocks)
        for part_no, part in enumerate(parts, start=1):
            heading = section["heading"]
            if len(parts) > 1:
                heading += f" (part {part_no} of {len(parts)})"
            header = [f"Document: {title}", f"Section: {heading}"]
            note = notes.get(section["heading"])
            if note:
                header.append(f"Context: {note}")
            text = "\n".join(header) + "\n\n" + "\n\n".join(part)
            chunks.append({
                "id": f"{rel}::{len(chunks)}",
                "text": text,
                "metadata": {
                    "source": rel,
                    "title": title,
                    "section": heading,
                    "doc_info": doc_info,
                    "pages": ", ".join(str(p) for p in section["pages"]),
                },
            })
    return chunks


def document_files():
    files, skipped = [], []
    for path in sorted(DOCS_DIR.rglob("*")):
        if not path.is_file() or path.name.startswith((".", "~$")):
            continue
        (files if path.suffix.lower() in SUPPORTED else skipped).append(path)
    return files, skipped


def fingerprint(files):
    """A hash of the document names, sizes and modification times, used to spot changes."""
    h = hashlib.sha256()
    for path in files:
        stat = path.stat()
        h.update(f"{path.relative_to(DOCS_DIR).as_posix()}|{stat.st_size}|{stat.st_mtime_ns}\n".encode())
    return h.hexdigest()


# ---------------------------------------------------------------------------
# Chroma database
# ---------------------------------------------------------------------------

def open_client():
    import chromadb
    from chromadb.config import Settings

    return chromadb.PersistentClient(path=str(DB_DIR), settings=Settings(anonymized_telemetry=False))


def embedding_function():
    from chromadb.utils import embedding_functions

    return embedding_functions.DefaultEmbeddingFunction()


def build_database(client):
    files, skipped = document_files()
    for path in skipped:
        print(f"  Skipping {path.relative_to(DOCS_DIR).as_posix()} (unsupported file type)")
    if not files:
        sys.exit(f"No supported documents found in {DOCS_DIR}")

    chunks = []
    for path in files:
        doc_chunks = chunk_document(path)
        print(f"  {path.relative_to(DOCS_DIR).as_posix()}: {len(doc_chunks)} chunks")
        chunks.extend(doc_chunks)

    try:
        client.delete_collection(COLLECTION)
    except Exception:
        pass  # nothing to delete on the first build
    collection = client.create_collection(
        COLLECTION,
        embedding_function=embedding_function(),
        metadata={"hnsw:space": "cosine", "fingerprint": fingerprint(files)},
    )
    collection.add(
        ids=[c["id"] for c in chunks],
        documents=[c["text"] for c in chunks],
        metadatas=[c["metadata"] for c in chunks],
    )
    print(f"Database built: {len(chunks)} chunks from {len(files)} documents in {DB_DIR.name}/\n")
    return collection


def get_collection(client, rebuild):
    if rebuild:
        print(f"Rebuilding the database from {DOCS_DIR.name}/ ...")
        return build_database(client)
    try:
        collection = client.get_collection(COLLECTION, embedding_function=embedding_function())
    except Exception:
        print(f"No database yet. Building it from {DOCS_DIR.name}/ ...")
        return build_database(client)
    files, _ = document_files()
    if (collection.metadata or {}).get("fingerprint") != fingerprint(files):
        print("Note: documents were added, removed or changed since the database was built.")
        print("      Run with --rebuild to include the changes.\n")
    return collection


def retrieve(collection, question):
    result = collection.query(query_texts=[question], n_results=TOP_K)
    hits = []
    for text, meta, distance in zip(result["documents"][0], result["metadatas"][0], result["distances"][0]):
        hits.append({"text": text, "meta": meta, "similarity": 1 - distance})
    return hits


# ---------------------------------------------------------------------------
# Claude
# ---------------------------------------------------------------------------

def load_api_key():
    try:
        key = KEY_FILE.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not key:
        sys.exit(f"No API key found. Put it in {KEY_FILE} or set ANTHROPIC_API_KEY.")
    return key


def ask_claude(client, question, hits):
    sources = []
    for rank, hit in enumerate(hits, start=1):
        meta = hit["meta"]
        sources.append(
            f'<source rank="{rank}" file="{meta["source"]}" document_info="{meta["doc_info"]}">\n'
            f'{hit["text"]}\n</source>'
        )
    user_message = "<sources>\n" + "\n".join(sources) + "\n</sources>\n\nQuestion: " + question

    response = client.messages.create(
        model=MODEL,
        max_tokens=16000,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_message}],
    )
    if response.stop_reason == "refusal":
        return "Claude declined to answer this question."
    answer = "".join(block.text for block in response.content if block.type == "text").strip()
    if response.stop_reason == "max_tokens":
        answer += "\n\n(The answer was cut off because it reached the length limit.)"
    return answer or "(Claude returned no text.)"


def answer_question(collection, claude, question):
    import anthropic

    hits = retrieve(collection, question)
    print(f"\nTop {len(hits)} chunks:")
    for rank, hit in enumerate(hits, start=1):
        preview = clean(hit["text"])[:PREVIEW_CHARS]
        print(f"  {rank}. similarity {hit['similarity']:.3f} | {hit['meta']['source']}")
        print(f"     {preview}...")

    print("\nAnswer:")
    try:
        print(ask_claude(claude, question, hits))
    except anthropic.AuthenticationError:
        print(f"Error: the API key was rejected. Check the key in {KEY_FILE}.")
    except anthropic.RateLimitError:
        print("Error: rate limit reached. Wait a minute and try again.")
    except anthropic.APIConnectionError:
        print("Error: could not reach the Anthropic API. Check your internet connection.")
    except anthropic.APIStatusError as err:
        print(f"Error from the Anthropic API (HTTP {err.status_code}): {err.message}")
    print()


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(description="Answer questions from Copperline's finance documents.")
    parser.add_argument("question", nargs="*", help="the question to ask (leave out to ask several in a row)")
    parser.add_argument("--rebuild", action="store_true",
                        help="rebuild the database after adding or removing documents")
    args = parser.parse_args()

    collection = get_collection(open_client(), args.rebuild)
    question = " ".join(args.question).strip()
    if args.rebuild and not question:
        return

    import anthropic
    claude = anthropic.Anthropic(api_key=load_api_key())

    if question:
        answer_question(collection, claude, question)
        return
    print("Ask a question about the Copperline finance documents (press Enter on an empty line to quit).")
    while True:
        try:
            question = input("\nQuestion: ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not question:
            break
        answer_question(collection, claude, question)


if __name__ == "__main__":
    main()
