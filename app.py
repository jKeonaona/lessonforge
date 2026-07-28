import hashlib
import os
from flask import (Flask, jsonify, render_template, request,
                   redirect, url_for, flash)
from werkzeug.utils import secure_filename
from config import Config
from models import db, SourceDocument, Block
from extract import extract_blocks


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
        return render_template("index.html", docs=docs)

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
            for b in extract_blocks(path):
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
        return render_template("document.html", doc=doc, blocks=blocks)

    return app


app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 6100))
    app.run(host="0.0.0.0", port=port)
