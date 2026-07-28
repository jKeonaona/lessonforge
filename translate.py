import json
import os
from anthropic import Anthropic
from models import db, Block, ChangeLog, GlossaryTerm

MODEL = "claude-sonnet-4-5-20250929"

BASE_SYSTEM = """You translate workplace safety training text from
English into Mexican Spanish (es-MX) for construction and industrial
field crews.

Requirements:
- Use Mexican Spanish as spoken by working crews, not European Spanish
  and not academic register. Plain, direct, unambiguous.
- Use usted, not tú.
- Preserve imperative force. "Do NOT run" must stay an unambiguous
  prohibition, not a suggestion.
- Preserve emphasis. If the English capitalizes NOT or uses bold-like
  emphasis, carry that emphasis into the Spanish.
- Never translate, renumber, or localize regulatory citations, standard
  numbers, part numbers, or measurements. Leave 29 CFR 1926.62,
  8 CCR 3395, ANSI Z87.1, 42 inches, 25 mph, 61-220 pounds exactly
  as written in the source.
- Do not add, remove, soften, or explain content. Translate what is
  there.
- Do not translate proper nouns or agency names.

TERMINOLOGY. The following translations are locked. Use them exactly.
Do not substitute synonyms:
%s

Return ONLY a JSON array, no markdown fences and no commentary.
Each element must be:
  {"seq": <int>, "es": "<the Spanish translation of that block>"}
Return one element for every block you were given."""


def _client():
    return Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])


def _system():
    terms = GlossaryTerm.query.filter_by(is_locked=True).all()
    lines = []
    for t in terms:
        line = "  %s = %s" % (t.term_en, t.term_es)
        if t.notes:
            line += "   (%s)" % t.notes
        lines.append(line)
    return BASE_SYSTEM % "\n".join(lines)


def run_translation_pass(doc_id, actor="system"):
    """Translate all blocks to es-MX. Writes text_es and sets
    status_es to 'proposed'. Does not overwrite approved rows."""
    blocks = (Block.query.filter_by(source_doc_id=doc_id)
              .order_by(Block.seq).all())
    todo = [b for b in blocks if b.status_es != "approved"]
    if not todo:
        return 0

    by_seq = {b.seq: b for b in todo}
    system = _system()

    def chunk(seq, n):
        for i in range(0, len(seq), n):
            yield seq[i:i + n]

    count = 0
    for group in chunk(todo, 8):
        payload = "\n".join(
            "[%d] %s" % (b.seq, b.text_en or "") for b in group
        )
        resp = _client().messages.create(
            model=MODEL,
            max_tokens=8000,
            system=system,
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
        try:
            items = json.loads(raw)
        except ValueError:
            continue

        for item in items:
            blk = by_seq.get(item.get("seq"))
            if not blk:
                continue
            es = (item.get("es") or "").strip()
            if not es:
                continue
            db.session.add(ChangeLog(
                block_id=blk.id,
                phase="translation",
                before=blk.text_en,
                after=es,
                status="proposed",
                actor="claude",
            ))
            blk.text_es = es
            blk.status_es = "proposed"
            count += 1

    db.session.commit()
    return count


def approve_translation(block_id, actor="john"):
    blk = Block.query.get(block_id)
    if not blk:
        return False
    blk.status_es = "approved"
    db.session.add(ChangeLog(
        block_id=blk.id, phase="translation_review",
        before=blk.text_en, after=blk.text_es,
        status="approved", actor=actor,
    ))
    db.session.commit()
    return True


def edit_translation(block_id, new_es, actor="john"):
    blk = Block.query.get(block_id)
    if not blk:
        return False
    db.session.add(ChangeLog(
        block_id=blk.id, phase="translation_review",
        before=blk.text_es, after=new_es,
        status="edited", actor=actor,
    ))
    blk.text_es = new_es
    blk.status_es = "approved"
    db.session.commit()
    return True
