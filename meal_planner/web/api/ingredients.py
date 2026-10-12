"""Ingredient master data: user edits only. AI workflows never reach these endpoints."""

from flask import Blueprint

from ...models import Ingredient, IngredientsFile
from ..helpers import NotFound, body, dump, load

bp = Blueprint("ingredients", __name__)


@bp.get("/ingredients")
def list_ingredients():
    _, cat = load()
    return [dump(i) for i in cat.ingredients.ingredients]


@bp.post("/ingredients")
def add_ingredient():
    store, cat = load()
    new = Ingredient.model_validate(body())
    store.save_ingredients(cat, IngredientsFile(ingredients=cat.ingredients.ingredients + (new,)))
    return dump(new), 201


@bp.put("/ingredients/<ingredient_id>")
def edit_ingredient(ingredient_id):
    store, cat = load()
    _require(cat, ingredient_id)
    edited = Ingredient.model_validate(body() | {"ingredient_id": ingredient_id})
    items = tuple(edited if i.ingredient_id == ingredient_id else i for i in cat.ingredients.ingredients)
    store.save_ingredients(cat, IngredientsFile(ingredients=items))
    return dump(edited)


@bp.delete("/ingredients/<ingredient_id>")
def delete_ingredient(ingredient_id):
    store, cat = load()
    _require(cat, ingredient_id)
    items = tuple(i for i in cat.ingredients.ingredients if i.ingredient_id != ingredient_id)
    store.save_ingredients(cat, IngredientsFile(ingredients=items))  # refused while dishes still use it
    return {"deleted": ingredient_id}


def _require(cat, ingredient_id):
    if ingredient_id not in cat.ingredient_ids:
        raise NotFound(f"食材 {ingredient_id} 不存在")
