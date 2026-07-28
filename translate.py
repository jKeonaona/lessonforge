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

BACK_SYSTEM = """You are given Spanish safety training text. Translate
it back into plain English as literally as possible.

Do not improve, smooth, or interpret. If the Spanish is awkward, the
English should be awkward. If the Spanish omits something, omit it.
Your output is used to detect translation errors, so fidelity to the
Spanish matters more than readability.

Return ONLY a JSON array, no markdown fences and no commentary:
  {"seq": <int>, "en": "<literal English of that block>"}
Return one element for every block you were given."""

COMPARE_SYSTEM = """You compare an original English safety instruction
against a back-translation of its Spanish version.

Report a problem ONLY if the meaning changed in a way that matters for
worker safety:
- A negation was added, dropped, or inverted.
- An instruction became a suggestion, or a prohibition became optional.
- A number, measurement, or citation changed.
- An agency, body part, equipment type, or hazard was swapped for a
  different one.
- Content was added that was not in the original.
- Content was dropped that changes what the worker should do.

Do NOT report:
- Wording, phrasing, or style differences.
- Synonyms that mean the same thing.
- Word order, article, or tense differences.
- Anything where a worker would still take the same action.

Return ONLY a JSON array, no markdown fences and no commentary:
  {"seq": <int>, "issue": "<one short sentence naming the problem>"}
Return an empty array [] if no block has a meaning-level problem."""


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


def verify_translations(doc_id, actor="system"):
    """Back-translate each block and compare to the original English.
    Blocks that pass are auto-approved. Blocks that fail are flagged
    for human review. Returns (approved, flagged)."""
    blocks = (Block.query.filter_by(source_doc_id=doc_id)
              .order_by(Block.seq).all())
    todo = [b for b in blocks
            if b.text_es and b.status_es == "proposed"]
    if not todo:
        return (0, 0)

    by_seq = {b.seq: b for b in todo}

    def chunk(seq, n):
        for i in range(0, len(seq), n):
            yield seq[i:i + n]

    def call(system, payload):
        resp = _client().messages.create(
            model=MODEL, max_tokens=8000, system=system,
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
            return json.loads(raw)
        except ValueError:
            return []

    flagged = {}
    for group in chunk(todo, 8):
        back = call(BACK_SYSTEM, "\n".join(
            "[%d] %s" % (b.seq, b.text_es) for b in group))
        back_by_seq = {i.get("seq"): (i.get("en") or "") for i in back}

        pairs = []
        for b in group:
            bt = back_by_seq.get(b.seq)
            if not bt:
                flagged[b.seq] = "Back-translation returned nothing."
                continue
            pairs.append(
                "[%d]\nORIGINAL: %s\nBACK: %s" % (b.seq, b.text_en, bt))

        if pairs:
            for item in call(COMPARE_SYSTEM, "\n\n".join(pairs)):
                seq = item.get("seq")
                if seq in by_seq:
                    flagged[seq] = item.get("issue") or "Meaning changed."

    approved = 0
    for b in todo:
        if b.seq in flagged:
            b.status_es = "flagged"
            db.session.add(ChangeLog(
                block_id=b.id, phase="translation_verify",
                before=b.text_en, after=b.text_es,
                status="flagged", actor=flagged[b.seq][:60],
            ))
        else:
            b.status_es = "approved"
            db.session.add(ChangeLog(
                block_id=b.id, phase="translation_verify",
                before=b.text_en, after=b.text_es,
                status="auto_approved", actor="claude",
            ))
            approved += 1

    db.session.commit()
    return (approved, len(flagged))
