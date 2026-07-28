from datetime import datetime
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()


class SourceDocument(db.Model):
    __tablename__ = "source_document"
    id = db.Column(db.Integer, primary_key=True)
    filename = db.Column(db.String(255), nullable=False)
    title = db.Column(db.String(255))
    title_es = db.Column(db.String(255))
    english_locked = db.Column(db.Boolean, default=False)
    queue_status = db.Column(db.String(32))
    revision = db.Column(db.String(32), default="1.0")
    sha256 = db.Column(db.String(64), unique=True, nullable=False)
    uploaded_at = db.Column(db.DateTime, default=datetime.utcnow)
    status = db.Column(db.String(32), default="uploaded")
    blocks = db.relationship("Block", backref="source_document",
                            lazy=True, cascade="all, delete-orphan")


class Block(db.Model):
    __tablename__ = "block"
    id = db.Column(db.Integer, primary_key=True)
    source_doc_id = db.Column(db.Integer,
                              db.ForeignKey("source_document.id"),
                              nullable=False)
    seq = db.Column(db.Integer, nullable=False)
    block_type = db.Column(db.String(32), nullable=False)
    text_en = db.Column(db.Text)
    text_es = db.Column(db.Text)
    status_en = db.Column(db.String(32), default="raw")
    status_es = db.Column(db.String(32), default="none")
    is_jurisdictional = db.Column(db.Boolean, default=False)


class Lesson(db.Model):
    __tablename__ = "lesson"
    id = db.Column(db.Integer, primary_key=True)
    source_doc_id = db.Column(db.Integer,
                              db.ForeignKey("source_document.id"))
    title = db.Column(db.String(255), nullable=False)
    revision = db.Column(db.String(32), default="1.0")
    revision_date = db.Column(db.Date)
    status = db.Column(db.String(32), default="draft")


class GlossaryTerm(db.Model):
    __tablename__ = "glossary_term"
    id = db.Column(db.Integer, primary_key=True)
    term_en = db.Column(db.String(255), nullable=False)
    term_es = db.Column(db.String(255), nullable=False)
    is_locked = db.Column(db.Boolean, default=True)
    domain = db.Column(db.String(64))
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class ChangeLog(db.Model):
    __tablename__ = "change_log"
    id = db.Column(db.Integer, primary_key=True)
    block_id = db.Column(db.Integer, db.ForeignKey("block.id"))
    phase = db.Column(db.String(32), nullable=False)
    before = db.Column(db.Text)
    after = db.Column(db.Text)
    status = db.Column(db.String(32), default="pending")
    actor = db.Column(db.String(64))
    ts = db.Column(db.DateTime, default=datetime.utcnow)


def doc_phase(doc):
    """Derive the document phase from actual data, not stored status."""
    blocks = Block.query.filter_by(source_doc_id=doc.id).all()
    if not blocks:
        return "uploaded"
    ids = [b.id for b in blocks]
    rows = (ChangeLog.query
            .filter(ChangeLog.block_id.in_(ids))
            .filter(ChangeLog.phase == "correction").all())
    pending = [r for r in rows if r.status == "pending"]
    if pending:
        return "corrections_pending"
    if doc.english_locked:
        return "english_locked"
    if rows or doc.status == "pass_run":
        return "english_ready"
    return "extracted"


PHASE_LABEL = {
    "uploaded": "Uploaded",
    "extracted": "Extracted",
    "corrections_pending": "Corrections awaiting review",
    "english_ready": "English reviewed",
    "english_locked": "English locked",
}
