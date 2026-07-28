import re
from collections import Counter
import pdfplumber

BULLET = re.compile(r"^\s*[\u2022\u25cf\u25aa\uf0b7o\-\*]\s+")


def _is_heading(line):
    s = line.strip()
    if len(s) < 3 or len(s) > 80:
        return False
    letters = [c for c in s if c.isalpha()]
    if not letters:
        return False
    upper = sum(1 for c in letters if c.isupper())
    return upper / len(letters) > 0.85


def _furniture(pages):
    """Lines repeating on most pages are headers/footers/branding."""
    if len(pages) < 2:
        return set()
    counts = Counter()
    for lines in pages:
        for line in set(l.strip() for l in lines if l.strip()):
            counts[line] += 1
    threshold = max(2, int(len(pages) * 0.5))
    return {line for line, n in counts.items() if n >= threshold}


def extract_blocks(path):
    """Return list of dicts: {seq, block_type, text_en}."""
    pages = []
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ""
            pages.append(text.split("\n"))

    drop = _furniture(pages)
    blocks = []
    buffer = []

    def flush():
        if buffer:
            blocks.append({
                "block_type": "paragraph",
                "text_en": " ".join(buffer).strip(),
            })
            buffer.clear()

    for lines in pages:
        for raw in lines:
            line = raw.strip()
            if not line or line in drop:
                continue
            if _is_heading(line):
                flush()
                blocks.append({"block_type": "heading", "text_en": line})
            elif BULLET.match(line):
                flush()
                blocks.append({
                    "block_type": "list_item",
                    "text_en": BULLET.sub("", line).strip(),
                })
            else:
                buffer.append(line)
        flush()
    flush()

    for i, b in enumerate(blocks, start=1):
        b["seq"] = i
    return blocks
