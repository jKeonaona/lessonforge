import json
import os
from anthropic import Anthropic
from models import db, Block, ChangeLog

MODEL = "claude-sonnet-4-5-20250929"

SYSTEM = """You are proofreading extracted safety training text before it
is translated into Spanish. Uncorrected errors become dangerous
instructions in the translated document.

Report ONLY these categories of error:
1. Misspellings and wrong words (e.g. "board head" should be "broad head",
   "couch down" should be "crouch down").
2. Missing words that invert or destroy the meaning of a sentence,
   especially a missing "not".
3. Internal inconsistencies where the same thing is named two different
   ways in the document (e.g. "wildlife office" in one place and
   "wildfire office" in another).
4. Duplicated or garbled words from PDF extraction (e.g. "two 2 lobes").
5. Plainly wrong facts that contradict the rest of the document.

Do NOT report:
- Style, tone, wording, or readability preferences.
- Formatting, capitalization, or punctuation preferences.
- Anything you would change only to make the text "better".
- American vs British spelling.

Rewrite as little as possible. Change only the erroneous words. Preserve
the original sentence structure exactly.

Return ONLY a JSON array, no markdown fences and no commentary. Each
element must be:
  {"seq": <int>, "corrected": "<full corrected block text>",
   "reason": "<short reason>"}

Return an empty array [] if nothing meets the criteria above."""


def _client():
    return Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])


def run_correction_pass(doc_id, actor="system"):
    """Send all blocks for review. Write proposals to change_log as
    pending. Never modifies block text."""
    blocks = (Block.query.filter_by(source_doc_id=doc_id)
              .order_by(Block.seq).all())
    if not blocks:
        return 0

    by_seq = {b.seq: b for b in blocks}
    seen = {
        c.block_id for c in ChangeLog.query.filter_by(phase="correction")
        .filter(ChangeLog.block_id.in_([b.id for b in blocks])).all()
    }

    def chunk(seq, n):
        for i in range(0, len(seq), n):
            yield seq[i:i + n]

    items = []
    for group in chunk(blocks, 10):
        payload = "\n".join(
            "[%d] %s" % (b.seq, b.text_en or "") for b in group
        )
        resp = _client().messages.create(
            model=MODEL,
            max_tokens=4000,
            system=SYSTEM,
            messages=[{"role": "user", "content": payload}],
        )
        raw = "".join(
            p.text for p in resp.content
            if getattr(p, "type", "") == "text"
        ).strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
            raw = raw.strip()
        items.extend(json.loads(raw))

    created = 0
    for item in items:
        blk = by_seq.get(item.get("seq"))
        if not blk:
            continue
        if blk.id in seen:
            continue
        after = (item.get("corrected") or "").strip()
        if not after or after == (blk.text_en or "").strip():
            continue
        db.session.add(ChangeLog(
            block_id=blk.id,
            phase="correction",
            before=blk.text_en,
            after=after,
            status="pending",
            actor=actor,
        ))
        created += 1

    db.session.commit()
    return created


def apply_change(change_id, actor="john"):
    ch = ChangeLog.query.get(change_id)
    if not ch or ch.status != "pending":
        return False
    blk = Block.query.get(ch.block_id)
    if blk:
        blk.text_en = ch.after
        blk.status_en = "corrected"
    ch.status = "approved"
    ch.actor = actor
    db.session.commit()
    return True


def reject_change(change_id, actor="john"):
    ch = ChangeLog.query.get(change_id)
    if not ch or ch.status != "pending":
        return False
    ch.status = "rejected"
    ch.actor = actor
    db.session.commit()
    return True
