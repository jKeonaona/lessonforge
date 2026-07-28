import hashlib
import os
from models import db, SourceDocument, Block
from extract import extract_blocks
from corrections import run_correction_pass
from translate import (run_translation_pass, verify_translations,
                       translate_title)


def ingest(data, filename, upload_folder):
    """Store one PDF and extract its blocks. Returns
    (SourceDocument or None, message)."""
    digest = hashlib.sha256(data).hexdigest()
    existing = SourceDocument.query.filter_by(sha256=digest).first()
    if existing:
        return (None, "duplicate")

    path = os.path.join(upload_folder, digest + ".pdf")
    with open(path, "wb") as out:
        out.write(data)

    doc = SourceDocument(filename=filename, sha256=digest,
                         status="extracting")
    db.session.add(doc)
    db.session.commit()

    try:
        parsed, title = extract_blocks(path)
        doc.title = title
        for b in parsed:
            db.session.add(Block(
                source_doc_id=doc.id, seq=b["seq"],
                block_type=b["block_type"], text_en=b["text_en"],
            ))
        doc.status = "extracted"
        db.session.commit()
        return (doc, "extracted %d blocks" % len(parsed))
    except Exception as exc:
        doc.status = "extract_failed"
        db.session.commit()
        return (doc, "extract failed: %s" % exc)


def run_pipeline(doc_id):
    """Correct, lock, translate, and verify one document end to end.
    Stops before locking if corrections need human review.
    Returns a short status string."""
    doc = SourceDocument.query.get(doc_id)
    if not doc:
        return "not found"

    try:
        run_correction_pass(doc.id)
        doc.status = "pass_run"
        db.session.commit()
    except Exception as exc:
        return "correction failed: %s" % exc

    ids = [b.id for b in Block.query.filter_by(
        source_doc_id=doc.id).all()]
    from models import ChangeLog
    pending = (ChangeLog.query
               .filter(ChangeLog.block_id.in_(ids))
               .filter(ChangeLog.phase == "correction")
               .filter(ChangeLog.status == "pending").count())
    if pending:
        return "%d corrections need review" % pending

    doc.english_locked = True
    db.session.commit()

    try:
        run_translation_pass(doc.id)
        if not doc.title_es:
            translate_title(doc.id)
        ok, bad = verify_translations(doc.id)
    except Exception as exc:
        return "translation failed: %s" % exc

    if bad:
        return "%d translations need review" % bad
    return "complete"
