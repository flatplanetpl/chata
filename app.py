"""HTTP API and static assets backed exclusively by SQLite."""

import os
import sqlite3
from pathlib import Path

from flask import Flask, jsonify, request, send_file, send_from_directory

import storage


ROOT = Path(__file__).resolve().parent


def create_app(database=None, data_dir=None):
    if database is None:
        database = Path(os.environ["CHATA_DATABASE"])
    if data_dir is None:
        data_dir = Path(database).parent
    storage.read(database)  # Refuse startup on a missing or incompatible database.
    app = Flask(__name__, static_folder=None)
    app.config["MAX_CONTENT_LENGTH"] = 65536

    @app.get("/")
    def index():
        return send_file(ROOT / "index.html")

    @app.get("/runtime/images/<path:filename>")
    def image(filename):
        return send_from_directory(Path(data_dir) / "images", filename)

    @app.get("/api/listings")
    def listings():
        return jsonify(storage.read(database))

    @app.patch("/api/listings")
    def edit_listing():
        payload = request.get_json()
        if not isinstance(payload, dict) or "url" not in payload or not isinstance(payload["url"], str):
            return jsonify(error="Listing URL is required"), 400
        url = payload.pop("url")
        try:
            storage.update_listing(database, url, payload)
        except ValueError as error:
            return jsonify(error=str(error)), 400
        except KeyError:
            return jsonify(error="Listing not found"), 404
        return jsonify(saved=True)

    @app.errorhandler(sqlite3.Error)
    def database_error(error):
        app.logger.exception("SQLite operation failed")
        return jsonify(error="Database operation failed; changes were not saved"), 503

    @app.after_request
    def headers(response):
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    return app
