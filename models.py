from datetime import datetime
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()


class SourceDocument(db.Model):
    __tablename__ = "source_document"
    id = db.Column(db.Integer, primary_key=True)
    filename = db.Column(db.String(255), nullable=False)
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
