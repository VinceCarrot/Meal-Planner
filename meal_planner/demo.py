"""Deterministic synthetic catalogues for tests, benchmarks and the demo mode of the Web UI.

The data is invented. It is never written to the real data directory.
"""

import dataclasses
import random
from pathlib import Path

from .catalogue import Catalogue, check_catalogue
from .models import (
    Constraint,
    ConstraintsFile,
    Dish,
    DishesFile,
    Ingredient,
    IngredientsFile,
    PreferencesFile,
)
from .yaml_io import write_yaml_atomic

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
CUISINES = ["家常", "川菜", "粤菜", "江浙菜", "湘菜"]
NAMES_ZH = {
    "tomato": "番茄", "bok_choy": "青菜", "potato": "土豆", "eggplant": "茄子", "green_pepper": "青椒",
    "cabbage": "包菜", "spinach": "菠菜", "carrot": "胡萝卜", "cucumber": "黄瓜", "broccoli": "西兰花",
    "celery": "芹菜", "lotus_root": "莲藕", "pumpkin": "南瓜", "radish": "萝卜", "bean_sprout": "豆芽",
    "pork_belly": "五花肉", "pork_loin": "里脊", "minced_pork": "肉末", "beef": "牛肉", "lamb": "羊肉",
    "chicken_thigh": "鸡腿", "chicken_breast": "鸡胸", "chicken_wing": "鸡翅", "duck": "鸭肉",
    "shrimp": "虾仁", "fish_fillet": "鱼片", "squid": "鱿鱼", "clam": "花蛤", "crab": "螃蟹",
    "egg": "鸡蛋", "tofu": "豆腐", "dried_tofu": "豆干", "tofu_skin": "腐竹",
    "shiitake": "香菇", "enoki": "金针菇", "wood_ear": "木耳", "oyster_mushroom": "平菇",
    "soy_sauce": "生抽", "vinegar": "醋", "chili": "辣椒",
}
METHOD_ZH = {"stir_fry": "炒", "steam": "蒸", "braise": "烧", "stew": "炖", "boil": "煮", "deep_fry": "炸",
             "pan_fry": "煎", "roast": "烤", "cold_mix": "拌"}
# Share of each dish type in the catalogue.
TYPE_MIX = [("vegetarian", 0.35), ("mixed", 0.30), ("meat", 0.20), ("soup", 0.15)]


def synthetic_catalogue(num_dishes: int, seed: int = 0) -> Catalogue:
    rng = random.Random(seed)
    ingredients = [
        Ingredient(ingredient_id=f"ing_{name}", name_zh=NAMES_ZH[name], name_en=name.replace("_", " "),
                   category=category, kcal_per_100g=rng.randint(15, 400))
        for category, names in INGREDIENTS.items()
        for name in names
    ]
    by_category = {c: [f"ing_{n}" for n in names] for c, names in INGREDIENTS.items()}
    plant = by_category["vegetable"] + by_category["soy"] + by_category["mushroom"] + by_category["egg"]

    types = []
    for dish_type, share in TYPE_MIX:
        types += [dish_type] * round(num_dishes * share)
    types = (types + ["vegetarian"] * num_dishes)[:num_dishes]

    dishes, names = [], set()
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
        name = "".join(NAMES_ZH[i[4:]] for i in main) + ("汤" if dish_type == "soup" else METHOD_ZH[method])
        name = name if name not in names else f"{name}（{n}）"
        names.add(name)
        dishes.append(Dish(
            dish_id=f"dish_{n:04d}",
            name_zh=name,
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


def write_catalogue(catalogue: Catalogue, data_dir: Path) -> None:
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


DEMO_RULES = [
    ("每顿饭4个菜（含汤）", "hard", {"type": "dish_count", "min": 4, "max": 4}),
    ("每顿恰好一个汤", "hard", {"type": "dish_type_count", "dish_type": "soup", "min": 1, "max": 1}),
    ("每顿至少一个大荤", "hard", {"type": "dish_type_count", "dish_type": "meat", "min": 1}),
    ("两周内同一道菜不重复", "hard", {"type": "exact_repeat_window", "weeks": 2}),
    ("同一周的菜别太像", "soft", {"type": "dish_similarity", "window_weeks": 1}),
    ("同一周的整餐别太像", "soft", {"type": "meal_similarity", "window_weeks": 1}),
]


def create_demo_data(data_dir: Path) -> None:
    """Write a demo data set (100 invented dishes and typical rules) unless it already exists."""
    if (data_dir / "dishes.yaml").exists():
        return
    catalogue = synthetic_catalogue(100)
    constraints = [
        Constraint(constraint_id=f"C{n:03d}", description=text, scope=["menu_generation", "menu_adjustment"],
                   strictness=strictness, source="persistent", execution=execution, parse_status="executable")
        for n, (text, strictness, execution) in enumerate(DEMO_RULES, start=1)
    ]
    write_catalogue(dataclasses.replace(catalogue, constraints=ConstraintsFile(constraints=constraints)), data_dir)
