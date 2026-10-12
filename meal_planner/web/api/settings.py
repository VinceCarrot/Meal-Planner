"""Settings (model per LLM task, similarity weights, planner parameters) and vocabularies."""

from flask import Blueprint, current_app

from ...settings import Settings, save_settings
from ...vocab import CookingMethod, DishType, Flavour, IngredientCategory
from ..helpers import body, dump, settings

bp = Blueprint("settings", __name__)


@bp.get("/settings")
def get_settings():
    return dump(settings())


@bp.put("/settings")
def put_settings():
    new = Settings.model_validate(body())
    save_settings(current_app.config["DATA_DIR"], new)
    return dump(new)


@bp.get("/vocab")
def vocab():
    return {
        "dish_types": [v.value for v in DishType],
        "categories": [v.value for v in IngredientCategory],
        "cooking_methods": [v.value for v in CookingMethod],
        "flavours": [v.value for v in Flavour],
    }
