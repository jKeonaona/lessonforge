import threading
import time
from models import db, SourceDocument
from batch import run_pipeline

_lock = threading.Lock()
_running = False


def enqueue(doc_id):
    doc = SourceDocument.query.get(doc_id)
    if doc:
        doc.queue_status = "queued"
        db.session.commit()


def reset_orphans():
    """On startup, requeue anything left mid-flight by a restart."""
    stuck = SourceDocument.query.filter_by(
        queue_status="processing").all()
    for d in stuck:
        d.queue_status = "queued"
    if stuck:
        db.session.commit()
    return len(stuck)


def _loop(app):
    while True:
        try:
            with app.app_context():
                doc = (SourceDocument.query
                       .filter_by(queue_status="queued")
                       .order_by(SourceDocument.id).first())
                if doc is None:
                    time.sleep(5)
                    continue
                doc.queue_status = "processing"
                db.session.commit()
                doc_id = doc.id
                try:
                    result = run_pipeline(doc_id)
                except Exception as exc:
                    result = "failed: %s" % exc
                doc = SourceDocument.query.get(doc_id)
                if doc:
                    doc.queue_status = (
                        "done" if result == "complete" else result[:60])
                    db.session.commit()
        except Exception:
            time.sleep(10)


def start(app):
    global _running
    with _lock:
        if _running:
            return
        _running = True
    t = threading.Thread(target=_loop, args=(app,), daemon=True)
    t.start()
