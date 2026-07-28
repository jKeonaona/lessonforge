import re
from collections import Counter
import pdfplumber

BULLET = re.compile(r"^\s*[\u2022\u25cf\u25aa\uf0b7o\-\*]\s+")
BANNERISH = re.compile(r"(https?://|www\.|\d{3}[-.\s]?\d{3}[-.\s]?\d{4})",
                       re.I)
CONTINUES = re.compile(r"[a-z,;:]$")


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


def _pick_title(drop):
    """Choose a lesson title from repeating page furniture.
    Prefers ALL-CAPS lines that are not phone numbers or URLs."""
    best = None
    for line in drop:
        s = line.strip(" .")
        if len(s) < 6 or len(s) > 70:
            continue
        if BANNERISH.search(s):
            continue
        letters = [c for c in s if c.isalpha()]
        if not letters:
            continue
        if sum(1 for c in letters if c.isupper()) / len(letters) < 0.85:
            continue
        if best is None or len(s) > len(best):
            best = s
    return best.title() if best else None


def extract_blocks(path):
    """Return (blocks, title). Blocks are dicts with seq, block_type,
    text_en. Wrapped continuation lines are joined into their parent."""
    pages = []
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ""
            pages.append(text.split("\n"))

    drop = _furniture(pages)
    title = _pick_title(drop)
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
            elif (blocks and not buffer
                  and blocks[-1]["block_type"] == "list_item"
                  and CONTINUES.search(blocks[-1]["text_en"])):
                blocks[-1]["text_en"] += " " + line
            else:
                buffer.append(line)
        flush()
    flush()

    for i, b in enumerate(blocks, start=1):
        b["seq"] = i
    return blocks, title
