"""Flask application: one shell page plus a JSON API (ADR-006).

Every write goes through the validated application services; there is no
generic "write this file" endpoint. Write requests must be JSON, which browsers
cannot send cross-site without a CORS preflight (CORS is not enabled), so other
web pages cannot trigger writes on this local server.
"""

import logging
import mimetypes
from pathlib import Path

from flask import Flask, jsonify, render_template
from pydantic import ValidationError
from werkzeug.exceptions import HTTPException

from ..catalogue import DataError
from ..llm import LLMError
from .api import constraints, dishes, ingredients, menus, settings
from .helpers import NotFound

log = logging.getLogger(__name__)


def create_app(data_dir: Path, llm_factory=None) -> Flask:
    """`llm_factory(settings, task)` returns the LLM backend for a task (tests pass a fake)."""
    # ES modules need a JavaScript MIME type; the Windows registry sometimes maps .js to text/plain.
    mimetypes.add_type("text/javascript", ".js")
    app = Flask(__name__)
    app.config["DATA_DIR"] = Path(data_dir)
    app.config["LLM_FACTORY"] = llm_factory or (lambda s, task: s.backend_for(task))
    app.json.ensure_ascii = False
    app.json.sort_keys = False

    for module in (constraints, dishes, ingredients, menus, settings):
        app.register_blueprint(module.bp, url_prefix="/api")

    @app.get("/")
    def index():
        return render_template("index.html")

    @app.errorhandler(DataError)
    def data_error(e: DataError):
        return jsonify(error="数据校验未通过", issues=[str(i) for i in e.issues]), 400

    @app.errorhandler(ValidationError)
    def validation_error(e: ValidationError):
        issues = [f"{'.'.join(str(p) for p in err['loc'])}: {err['msg']}" for err in e.errors()]
        return jsonify(error="请求内容不合法", issues=issues), 400

    @app.errorhandler(NotFound)
    def not_found(e: NotFound):
        return jsonify(error=str(e), issues=[]), 404

    @app.errorhandler(LLMError)
    def llm_error(e: LLMError):
        log.warning("LLM call failed: %s", e)
        return jsonify(error="调用 Claude 失败", issues=[str(e)]), 502

    @app.errorhandler(KeyError)
    @app.errorhandler(ValueError)
    @app.errorhandler(TypeError)
    def bad_request(e: Exception):
        log.exception("bad request")
        return jsonify(error="请求缺少字段或包含无效的值", issues=[f"{type(e).__name__}: {e}"]), 400

    @app.errorhandler(HTTPException)
    def http_error(e: HTTPException):
        return jsonify(error=e.name, issues=[e.description or ""]), e.code

    return app
