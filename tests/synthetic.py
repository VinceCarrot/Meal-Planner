"""Deterministic synthetic catalogues for planner tests and benchmarks."""

import random

from meal_planner.catalogue import Catalogue, check_catalogue
from meal_planner.models import (
    ConstraintsFile,
    Dish,
    DishesFile,
    Ingredient,
    IngredientsFile,
    PreferencesFile,
)
from meal_planner.yaml_io import write_yaml_atomic

INGREDIENTS = {
    "vegetable": ["tomato", "bok_choy", "potato", "eggplant", "green_pepper", "cabbage", "spinach", "carrot",
                  "cucumber", "broccoli", "celery", "lotus_root", "pumpkin", "radish", "bean_sprout"],
    "meat": ["pork_belly", "pork_loin", "minced_pork", "beef", "lamb"],
    "poultry": ["chicken_thigh", "chicken_breast", "chicken_wing", "duck"],
    "seafood": ["shrimp", "fish_fillet", "squid", "clam", "crab"],
    "egg": ["egg"],
    "soy": ["tofu", "dried_tofu", "tofu_skin"],
    "mushroom": ["shiitake", "enoki", "wood_ear", "oyster_mushroom"],
    "seasoning": ["soy_sauce", "vinegar", "chili"],
}
PROTEIN = ["meat", "poultry", "seafood"]
METHODS = ["stir_fry", "steam", "braise", "stew", "boil", "deep_fry", "pan_fry", "roast", "cold_mix"]
FLAVOURS = ["light", "salty_savory", "soy_sauce", "sweet_sour", "sour", "sweet", "spicy", "numbing_spicy", "garlicky", "fish_fragrant"]
CUISINES = ["home_style", "sichuan", "cantonese", "jiangzhe", "hunan"]
# Share of each dish type in the catalogue.
TYPE_MIX = [("vegetarian", 0.35), ("mixed", 0.30), ("meat", 0.20), ("soup", 0.15)]


def synthetic_catalogue(num_dishes: int, seed: int = 0) -> Catalogue:
    rng = random.Random(seed)
    ingredients = [
        Ingredient(ingredient_id=f"ing_{name}", name_zh=name, category=category, kcal_per_100g=rng.randint(15, 400))
        for category, names in INGREDIENTS.items()
        for name in names
    ]
    by_category = {c: [f"ing_{n}" for n in names] for c, names in INGREDIENTS.items()}
    plant = by_category["vegetable"] + by_category["soy"] + by_category["mushroom"] + by_category["egg"]

    types = []
    for dish_type, share in TYPE_MIX:
        types += [dish_type] * round(num_dishes * share)
    types = (types + ["vegetarian"] * num_dishes)[:num_dishes]

    dishes = []
    for n, dish_type in enumerate(types, start=1):
        protein = by_category[rng.choice(PROTEIN)]
        if dish_type == "vegetarian":
            main = rng.sample(plant, rng.randint(1, 2))
        elif dish_type == "meat":
            main = [rng.choice(protein)]
        elif dish_type == "mixed":
            main = [rng.choice(protein), rng.choice(plant)]
        else:  # soup
            main = rng.sample(plant + protein, 2)
        extra = rng.sample([i for i in plant if i not in main], rng.randint(0, 2))
        lines = [{"ingredient_id": i, "quantity": rng.randint(50, 400), "unit": "g"} for i in main + extra]
        lines.append({"ingredient_id": rng.choice(by_category["seasoning"]), "note": "适量"})
        method = rng.choice(["boil", "stew"]) if dish_type == "soup" else rng.choice(METHODS)
        dishes.append(Dish(
            dish_id=f"dish_{n:04d}",
            name_zh=f"菜{n}",
            dish_type=dish_type,
            ingredients=lines,
            servings=4,
            style={
                "main_ingredients": main,
                "cooking_method": method,
                "flavours": rng.sample(FLAVOURS, rng.randint(1, 2)),
                "cuisine": rng.choice(CUISINES),
            },
            source="manual",
            review_status="approved",
        ))

    catalogue = Catalogue(
        ingredients=IngredientsFile(ingredients=ingredients),
        dishes=DishesFile(dishes=dishes),
        pending_dishes=DishesFile(),
        constraints=ConstraintsFile(),
        preferences=PreferencesFile(),
    )
    assert check_catalogue(catalogue) == []
    return catalogue


def write_catalogue(catalogue: Catalogue, data_dir) -> None:
    """Write a catalogue as the five YAML data files (for tests that need a DataStore)."""
    data_dir.mkdir(parents=True, exist_ok=True)
    for name, part in [
        ("ingredients.yaml", catalogue.ingredients),
        ("dishes.yaml", catalogue.dishes),
        ("pending_dishes.yaml", catalogue.pending_dishes),
        ("constraints.yaml", catalogue.constraints),
        ("preferences.yaml", catalogue.preferences),
    ]:
        write_yaml_atomic(data_dir / name, part.model_dump(mode="json"))
