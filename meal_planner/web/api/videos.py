"""Recipe import from video links."""

from flask import Blueprint, current_app

from ...settings import LLMTask
from ...video_import import import_video
from ..helpers import body, llm, load
from ..serialize import dish_view

bp = Blueprint("videos", __name__)


@bp.post("/videos/import")
def import_from_video():
    """Extract a recipe from a Bilibili / YouTube link into pending review."""
    store, cat = load()
    source = current_app.config["VIDEO_SOURCE"]
    cat, result = import_video(store, cat, llm(LLMTask.VIDEO_EXTRACTION), source, str(body()["url"]))
    ingredients = {i.ingredient_id: i for i in cat.ingredients.ingredients}
    return {
        "dish": dish_view(result.dish, ingredients),
        "title": result.title,
        "text_source": result.text_source,
        "truncated": result.truncated,
    }, 201
