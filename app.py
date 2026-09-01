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
                       verify_translations, translate_title)
from render import build_docx, docx_filename
from batch import ingest, run_pipeline
from worker import enqueue, start as start_worker, reset_orphans


def create_app():
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_object(Config)

    os.makedirs(app.instance_path, exist_ok=True)
    os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)

    db.init_app(app)

    with app.app_context():
        db.create_all()
        reset_orphans()

    start_worker(app)

    @app.route("/health")
    def health():
        return jsonify({"app": "lessonforge", "status": "ok"})

    @app.route("/")
    def index():
        docs = SourceDocument.query.order_by(
            SourceDocument.uploaded_at.desc()).all()
        pending = (db.session.query(ChangeLog)
                   .filter(ChangeLog.phase == "correction")
                   .filter(ChangeLog.status == "pending").count())
        busy = SourceDocument.query.filter(
            SourceDocument.queue_status.in_(
                ["queued", "processing"])).count()
        return render_template("index.html", docs=docs,
                               phase=doc_phase, label=PHASE_LABEL,
                               pending=pending, busy=busy)

    @app.route("/upload", methods=["POST"])
    def upload():
        files = request.files.getlist("pdf")
        files = [f for f in files
                 if f and f.filename.lower().endswith(".pdf")]
        if not files:
            flash("Select one or more PDF files.")
            return redirect(url_for("index"))

        auto = request.form.get("auto") == "on"
        made = []
        skipped = 0
        for f in files:
            doc, msg = ingest(f.read(), secure_filename(f.filename),
                              app.config["UPLOAD_FOLDER"])
            if doc is None:
                skipped += 1
            else:
                made.append(doc)
                if auto:
                    enqueue(doc.id)

        parts = ["%d uploaded" % len(made)]
        if skipped:
            parts.append("%d duplicates skipped" % skipped)
        if auto and made:
            parts.append("processing in the background")
        flash(", ".join(parts))

        if len(made) == 1 and not auto:
            return redirect(url_for("document", doc_id=made[0].id))
        return redirect(url_for("index"))

    @app.route("/document/<int:doc_id>/pipeline", methods=["POST"])
    def pipeline(doc_id):
        doc = SourceDocument.query.get_or_404(doc_id)
        enqueue(doc.id)
        flash("%s queued." % (doc.title or doc.filename))
        return redirect(url_for("index"))

    @app.route("/queue")
    def queue():
        rows = (db.session.query(ChangeLog, Block, SourceDocument)
                .join(Block, ChangeLog.block_id == Block.id)
                .join(SourceDocument,
                      Block.source_doc_id == SourceDocument.id)
                .filter(ChangeLog.phase == "correction")
                .filter(ChangeLog.status == "pending")
                .order_by(SourceDocument.id, Block.seq).all())
        items = [{"id": c.id, "doc_id": d.id, "seq": b.seq,
                  "before": c.before, "after": c.after}
                 for c, b, d in rows]
        seen = []
        docs = []
        for c, b, d in rows:
            if d.id not in seen:
                seen.append(d.id)
                docs.append(d)
        return render_template("queue.html", items=items, docs=docs)

    @app.route("/queue/<int:change_id>/<action>", methods=["POST"])
    def queue_decide(change_id, action):
        ch = ChangeLog.query.get_or_404(change_id)
        blk = Block.query.get(ch.block_id)
        doc_id = blk.source_doc_id if blk else None
        if action == "approve":
            apply_change(change_id)
        else:
            reject_change(change_id)
        if doc_id:
            remaining = (db.session.query(ChangeLog)
                         .join(Block, ChangeLog.block_id == Block.id)
                         .filter(Block.source_doc_id == doc_id)
                         .filter(ChangeLog.phase == "correction")
                         .filter(ChangeLog.status == "pending").count())
            if not remaining:
                enqueue(doc_id)
        return redirect(url_for("queue"))

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
        doc_id = blk.source_doc_id
        remaining = (db.session.query(ChangeLog)
                     .join(Block, ChangeLog.block_id == Block.id)
                     .filter(Block.source_doc_id == doc_id)
                     .filter(ChangeLog.phase == "correction")
                     .filter(ChangeLog.status == "pending").count())
        if not remaining:
            enqueue(doc_id)
        return redirect(url_for("review", doc_id=doc_id))

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
            if not doc.title_es:
                translate_title(doc.id)
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
    # Loopback only. nginx serves lessonforge.ccctrainingonline.com and proxies
    # to http://127.0.0.1:6100, so binding every interface never served a real
    # request -- it just left this app answering on its raw port over plain
    # http, outside the certificate. LessonForge has no login of any kind, and
    # an upload here spends the Anthropic API key, so the raw port was the
    # whole front door. Changed 2026-09-01.
    app.run(host="127.0.0.1", port=port)
