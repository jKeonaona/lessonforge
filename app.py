import hashlib
import os
from flask import (Flask, jsonify, render_template, request,
                   redirect, url_for, flash, send_file)
from werkzeug.utils import secure_filename
from config import Config
from models import (db, SourceDocument, Block, ChangeLog,
                    doc_phase, PHASE_LABEL)
from extract import extract_blocks
from corrections import run_correction_pass, apply_change, reject_change
from translate import (run_translation_pass, edit_translation,
                       verify_translations)
from render import build_docx, docx_filename


def create_app():
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_object(Config)

    os.makedirs(app.instance_path, exist_ok=True)
    os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)

    db.init_app(app)

    with app.app_context():
        db.create_all()

    @app.route("/health")
    def health():
        return jsonify({"app": "lessonforge", "status": "ok"})

    @app.route("/")
    def index():
        docs = SourceDocument.query.order_by(
            SourceDocument.uploaded_at.desc()).all()
        return render_template("index.html", docs=docs,
                               phase=doc_phase, label=PHASE_LABEL)

    @app.route("/upload", methods=["POST"])
    def upload():
        f = request.files.get("pdf")
        if not f or not f.filename.lower().endswith(".pdf"):
            flash("Select a PDF file.")
            return redirect(url_for("index"))

        data = f.read()
        digest = hashlib.sha256(data).hexdigest()

        existing = SourceDocument.query.filter_by(sha256=digest).first()
        if existing:
            flash("That file was already uploaded.")
            return redirect(url_for("document", doc_id=existing.id))

        name = secure_filename(f.filename)
        path = os.path.join(app.config["UPLOAD_FOLDER"], digest + ".pdf")
        with open(path, "wb") as out:
            out.write(data)

        doc = SourceDocument(filename=name, sha256=digest,
                             status="extracting")
        db.session.add(doc)
        db.session.commit()

        try:
            parsed, title = extract_blocks(path)
            doc.title = title
            for b in parsed:
                db.session.add(Block(
                    source_doc_id=doc.id,
                    seq=b["seq"],
                    block_type=b["block_type"],
                    text_en=b["text_en"],
                ))
            doc.status = "extracted"
            db.session.commit()
        except Exception as exc:
            doc.status = "extract_failed"
            db.session.commit()
            flash("Extraction failed: %s" % exc)

        return redirect(url_for("document", doc_id=doc.id))

    @app.route("/document/<int:doc_id>")
    def document(doc_id):
        doc = SourceDocument.query.get_or_404(doc_id)
        blocks = Block.query.filter_by(
            source_doc_id=doc.id).order_by(Block.seq).all()
        ph = doc_phase(doc)
        return render_template("document.html", doc=doc, blocks=blocks,
                               phase=ph, label=PHASE_LABEL)

    @app.route("/document/<int:doc_id>/correct", methods=["POST"])
    def correct(doc_id):
        doc = SourceDocument.query.get_or_404(doc_id)
        try:
            n = run_correction_pass(doc.id)
            doc.status = "pass_run"
            db.session.commit()
            flash("%d corrections proposed." % n)
        except Exception as exc:
            flash("Correction pass failed: %s" % exc)
        return redirect(url_for("review", doc_id=doc.id))

    @app.route("/document/<int:doc_id>/review")
    def review(doc_id):
        doc = SourceDocument.query.get_or_404(doc_id)
        rows = (db.session.query(ChangeLog, Block)
                .join(Block, ChangeLog.block_id == Block.id)
                .filter(Block.source_doc_id == doc.id,
                        ChangeLog.phase == "correction")
                .order_by(Block.seq).all())

        def pack(ch, blk):
            return {"id": ch.id, "seq": blk.seq, "before": ch.before,
                    "after": ch.after, "status": ch.status, "ts": ch.ts,
                    "reason_hint": ch.phase}

        pending = [pack(c, b) for c, b in rows if c.status == "pending"]
        decided = [pack(c, b) for c, b in rows if c.status != "pending"]
        return render_template("review.html", doc=doc,
                               pending=pending, decided=decided,
                               phase=doc_phase(doc), label=PHASE_LABEL)

    @app.route("/change/<int:change_id>/<action>", methods=["POST"])
    def decide(change_id, action):
        ch = ChangeLog.query.get_or_404(change_id)
        blk = Block.query.get(ch.block_id)
        if action == "approve":
            apply_change(change_id)
        else:
            reject_change(change_id)
        return redirect(url_for("review", doc_id=blk.source_doc_id))

    @app.route("/document/<int:doc_id>/lock", methods=["POST"])
    def lock_english(doc_id):
        doc = SourceDocument.query.get_or_404(doc_id)
        if doc_phase(doc) != "english_ready":
            flash("Resolve all pending corrections first.")
            return redirect(url_for("review", doc_id=doc.id))
        doc.english_locked = True
        db.session.commit()
        flash("English locked. Ready for translation.")
        return redirect(url_for("document", doc_id=doc.id))

    @app.route("/document/<int:doc_id>/unlock", methods=["POST"])
    def unlock_english(doc_id):
        doc = SourceDocument.query.get_or_404(doc_id)
        doc.english_locked = False
        db.session.commit()
        flash("English unlocked.")
        return redirect(url_for("document", doc_id=doc.id))

    @app.route("/document/<int:doc_id>/title", methods=["POST"])
    def set_title(doc_id):
        doc = SourceDocument.query.get_or_404(doc_id)
        new = (request.form.get("title") or "").strip()
        doc.title = new or None
        db.session.commit()
        return redirect(url_for("document", doc_id=doc.id))

    @app.route("/document/<int:doc_id>/lesson")
    def lesson(doc_id):
        doc = SourceDocument.query.get_or_404(doc_id)
        lang = request.args.get("lang", "en")
        blocks = (Block.query.filter_by(source_doc_id=doc.id)
                  .order_by(Block.seq).all())
        rendered = []
        for b in blocks:
            if lang == "es":
                text = (b.text_es or "").strip()
            else:
                text = (b.text_en or "").strip()
            if not text:
                continue
            if b.block_type == "list_item":
                if rendered and rendered[-1]["kind"] == "list":
                    rendered[-1]["entries"].append(text)
                else:
                    rendered.append({"kind": "list", "entries": [text]})
            elif b.block_type == "heading":
                rendered.append({"kind": "heading", "text": text})
            else:
                rendered.append({"kind": "paragraph", "text": text})
        return render_template("lesson.html", doc=doc, rendered=rendered,
                               phase=doc_phase(doc), label=PHASE_LABEL,
                               lang=lang)

    @app.route("/document/<int:doc_id>/spanish")
    def spanish(doc_id):
        doc = SourceDocument.query.get_or_404(doc_id)
        blocks = (Block.query.filter_by(source_doc_id=doc.id)
                  .order_by(Block.seq).all())
        approved = sum(1 for b in blocks if b.status_es == "approved")
        flags = {}
        ids = [b.id for b in blocks]
        for c in (ChangeLog.query
                  .filter(ChangeLog.block_id.in_(ids))
                  .filter(ChangeLog.phase == "translation_verify")
                  .filter(ChangeLog.status == "flagged").all()):
            flags[c.block_id] = c.actor
        flagged = [b for b in blocks if b.status_es == "flagged"]
        return render_template("translate.html", doc=doc, blocks=blocks,
                               approved=approved, total=len(blocks),
                               flagged=flagged, flags=flags)

    @app.route("/document/<int:doc_id>/translate", methods=["POST"])
    def translate_doc(doc_id):
        doc = SourceDocument.query.get_or_404(doc_id)
        if not doc.english_locked:
            flash("Finalize English before translating.")
            return redirect(url_for("document", doc_id=doc.id))
        try:
            n = run_translation_pass(doc.id)
            flash("%d blocks translated." % n)
        except Exception as exc:
            flash("Translation failed: %s" % exc)
        return redirect(url_for("spanish", doc_id=doc.id))

    @app.route("/block/<int:block_id>/translation", methods=["POST"])
    def save_translation(block_id):
        blk = Block.query.get_or_404(block_id)
        edit_translation(block_id, (request.form.get("es") or "").strip())
        return redirect(url_for("spanish", doc_id=blk.source_doc_id))

    @app.route("/document/<int:doc_id>/verify", methods=["POST"])
    def verify_doc(doc_id):
        doc = SourceDocument.query.get_or_404(doc_id)
        try:
            ok, bad = verify_translations(doc.id)
            flash("%d auto-approved, %d flagged for review." % (ok, bad))
        except Exception as exc:
            flash("Verification failed: %s" % exc)
        return redirect(url_for("spanish", doc_id=doc.id))

    @app.route("/document/<int:doc_id>/docx")
    def download_docx(doc_id):
        doc = SourceDocument.query.get_or_404(doc_id)
        lang = request.args.get("lang", "en")
        buf = build_docx(doc, lang)
        return send_file(
            buf,
            as_attachment=True,
            download_name=docx_filename(doc, lang),
            mimetype="application/vnd.openxmlformats-officedocument"
                     ".wordprocessingml.document",
        )

    return app


app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 6100))
    app.run(host="0.0.0.0", port=port)
