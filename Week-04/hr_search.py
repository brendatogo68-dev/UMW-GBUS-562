"""Search an organization's HR documents with a local Chroma database.

Adapted from Week-03/ask.py: the same file readers and section-based chunking (one chunk per
section heading, each starting with its document title and section heading), and the same
Chroma setup (built-in embedding model, cosine similarity). Differences for use inside an
MCP server:
- Nothing is printed to stdout, because stdout carries the MCP protocol. Progress goes to stderr.
- Page footers are dropped instead of becoming "Contact" chunks.
- The database rebuilds itself when the documents change.
- Works for any organization folder (hr-docs/, employees.csv, sample-emails/, system_prompt.txt);
  each organization gets its own database in chroma-db/<folder name>/.
"""

import hashlib
import re
import sys
from collections import Counter
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_ORG_DIR = SCRIPT_DIR / "hartwell-hr"
ORG_ITEMS = ("hr-docs", "employees.csv", "sample-emails", "system_prompt.txt")
# One database per organization, in chroma-db/<organization folder name>/.
# The whole chroma-db folder is kept out of Git by .gitignore; delete a subfolder to rebuild it.
DB_ROOT = SCRIPT_DIR / "chroma-db"


def resolve_org(org=None):
    """Return the organization folder: a path, or a folder name inside Week-04. Default: hartwell-hr."""
    if not org:
        org_dir = DEFAULT_ORG_DIR
    else:
        candidate = Path(org)
        org_dir = candidate if candidate.is_dir() else SCRIPT_DIR / org
    org_dir = org_dir.resolve()
    missing = [item for item in ORG_ITEMS if item != "sample-emails" and not (org_dir / item).exists()]
    if not org_dir.is_dir() or missing:
        raise SystemExit(f"Organization folder {org_dir} is missing: {', '.join(missing) or 'the folder itself'}. "
                         f"It needs {', '.join(ORG_ITEMS)}.")
    return org_dir


def db_dir_for(org_dir):
    return DB_ROOT / Path(org_dir).name

COLLECTION = "hr_docs"
# Chroma's built-in embedding model (all-MiniLM-L6-v2) only reads about the first 256 tokens
# of a chunk, so longer sections are split into parts of at most this many words.
MAX_WORDS = 180

SUPPORTED = {".html", ".htm", ".pdf", ".md", ".markdown", ".txt", ".docx"}


def log(message):
    print(message, file=sys.stderr, flush=True)


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
    for tag in soup(["script", "style", "nav", "noscript", "footer"]):
        tag.decompose()

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


def chunk_document(path, docs_dir):
    title, doc_info, sections = READERS[path.suffix.lower()](path)
    rel = path.relative_to(docs_dir).as_posix()
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
            text = f"Document: {title}\nSection: {heading}\n\n" + "\n\n".join(part)
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


def document_files(docs_dir):
    files, skipped = [], []
    for path in sorted(docs_dir.rglob("*")):
        if not path.is_file() or path.name.startswith((".", "~$")):
            continue
        (files if path.suffix.lower() in SUPPORTED else skipped).append(path)
    return files, skipped


def fingerprint(files, docs_dir):
    """A hash of the document names, sizes and modification times, used to spot changes."""
    h = hashlib.sha256()
    for path in files:
        stat = path.stat()
        h.update(f"{path.relative_to(docs_dir).as_posix()}|{stat.st_size}|{stat.st_mtime_ns}\n".encode())
    return h.hexdigest()


# ---------------------------------------------------------------------------
# Chroma database
# ---------------------------------------------------------------------------

def open_client(db_dir):
    import chromadb
    from chromadb.config import Settings

    Path(db_dir).mkdir(parents=True, exist_ok=True)
    return chromadb.PersistentClient(path=str(db_dir), settings=Settings(anonymized_telemetry=False))


def embedding_function():
    from chromadb.utils import embedding_functions

    return embedding_functions.DefaultEmbeddingFunction()


def build_database(org_dir=DEFAULT_ORG_DIR, client=None):
    docs_dir = Path(org_dir) / "hr-docs"
    db_dir = db_dir_for(org_dir)
    client = client or open_client(db_dir)
    files, skipped = document_files(docs_dir)
    for path in skipped:
        log(f"  Skipping {path.relative_to(docs_dir).as_posix()} (unsupported file type)")
    if not files:
        raise RuntimeError(f"No supported documents found in {docs_dir}")

    chunks = []
    for path in files:
        doc_chunks = chunk_document(path, docs_dir)
        log(f"  {path.relative_to(docs_dir).as_posix()}: {len(doc_chunks)} chunks")
        chunks.extend(doc_chunks)

    try:
        client.delete_collection(COLLECTION)
    except Exception:
        pass  # nothing to delete on the first build
    collection = client.create_collection(
        COLLECTION,
        embedding_function=embedding_function(),
        metadata={"hnsw:space": "cosine", "fingerprint": fingerprint(files, docs_dir)},
    )
    collection.add(
        ids=[c["id"] for c in chunks],
        documents=[c["text"] for c in chunks],
        metadatas=[c["metadata"] for c in chunks],
    )
    log(f"Database built: {len(chunks)} chunks from {len(files)} documents in {db_dir}")
    return collection


def open_collection(org_dir=DEFAULT_ORG_DIR):
    """Open the organization's database, building it first if it is missing or the documents changed."""
    docs_dir = Path(org_dir) / "hr-docs"
    client = open_client(db_dir_for(org_dir))
    try:
        collection = client.get_collection(COLLECTION, embedding_function=embedding_function())
    except Exception:
        log(f"No search database for {Path(org_dir).name} yet; building it.")
        return build_database(org_dir, client)
    files, _ = document_files(docs_dir)
    if (collection.metadata or {}).get("fingerprint") != fingerprint(files, docs_dir):
        log("HR documents changed since the last build; rebuilding the search database.")
        return build_database(org_dir, client)
    return collection


def search(collection, query, top_k=4):
    result = collection.query(query_texts=[query], n_results=top_k)
    hits = []
    for rank, (text, meta, distance) in enumerate(
            zip(result["documents"][0], result["metadatas"][0], result["distances"][0]), start=1):
        hits.append({
            "rank": rank,
            "similarity": round(1 - distance, 3),
            "source": meta["source"],
            "document": meta["title"],
            "document_info": meta["doc_info"],
            "section": meta["section"],
            "text": text,
        })
    return hits
