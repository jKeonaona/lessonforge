import os
from flask import Flask, jsonify
from config import Config
from models import db


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

    return app


app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 6100))
    app.run(host="0.0.0.0", port=port)
