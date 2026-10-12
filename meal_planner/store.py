"""Reading and writing the data directory.

`DataStore` has full write access and is used only by application services that
act on explicit user requests. AI workflows never receive a `DataStore`; they get
a `ReadOnlyCatalogue` (see `readonly.py`), which has no path to any file.

Every save validates the complete resulting data set before touching the disk.
"""

import dataclasses
import re
from pathlib import Path

from .catalogue import (
    CONSTRAINTS_FILE,
    DISHES_FILE,
    INGREDIENTS_FILE,
    PENDING_DISHES_FILE,
    PREFERENCES_FILE,
    Catalogue,
    DataError,
    DataIssue,
    check_catalogue,
    check_menu,
    parse_model,
)
from .models import ConstraintsFile, DishesFile, IngredientsFile, MenuVersion, PreferencesFile
from .yaml_io import YamlReadError, create_yaml, read_yaml, write_yaml_atomic

_FILES = {
    "ingredients": (INGREDIENTS_FILE, IngredientsFile),
    "dishes": (DISHES_FILE, DishesFile),
    "pending_dishes": (PENDING_DISHES_FILE, DishesFile),
    "constraints": (CONSTRAINTS_FILE, ConstraintsFile),
    "preferences": (PREFERENCES_FILE, PreferencesFile),
}
_MENU_VERSION_FILE = re.compile(r"^v(\d{3,})\.yaml$")


class DataStore:
    def __init__(self, data_dir: Path):
        self.data_dir = Path(data_dir)
        self.menus_dir = self.data_dir / "menus"

    # --- Catalogue ---------------------------------------------------------

    def load(self) -> Catalogue:
        parts, issues = {}, []
        for field, (file, model) in _FILES.items():
            try:
                parts[field] = parse_model(model, read_yaml(self.data_dir / file), file)
            except YamlReadError as e:
                issues.append(DataIssue(file, "", str(e)))
            except DataError as e:
                issues += e.issues
        if issues:
            raise DataError(issues)
        catalogue = Catalogue(**parts)
        _raise_if(check_catalogue(catalogue, set(self.menu_ids())))
        return catalogue

    def save_dishes(self, catalogue: Catalogue, dishes: DishesFile) -> Catalogue:
        return self._save(catalogue, "dishes", dishes)

    def save_pending_dishes(self, catalogue: Catalogue, pending: DishesFile) -> Catalogue:
        return self._save(catalogue, "pending_dishes", pending)

    def save_constraints(self, catalogue: Catalogue, constraints: ConstraintsFile) -> Catalogue:
        return self._save(catalogue, "constraints", constraints)

    def save_preferences(self, catalogue: Catalogue, preferences: PreferencesFile) -> Catalogue:
        return self._save(catalogue, "preferences", preferences)

    def save_ingredients(self, catalogue: Catalogue, ingredients: IngredientsFile) -> Catalogue:
        """User-owned master data. Call only for an explicit user edit; never expose to AI."""
        return self._save(catalogue, "ingredients", ingredients)

    def _save(self, catalogue: Catalogue, field: str, value) -> Catalogue:
        updated = dataclasses.replace(catalogue, **{field: value})
        _raise_if(check_catalogue(updated, set(self.menu_ids())))
        write_yaml_atomic(self.data_dir / _FILES[field][0], value.model_dump(mode="json"))
        return updated

    # --- Menus ---------------------------------------------------------------

    def menu_ids(self) -> list[str]:
        if not self.menus_dir.is_dir():
            return []
        return sorted(p.name for p in self.menus_dir.iterdir() if p.is_dir())

    def menu_versions(self, menu_id: str) -> list[int]:
        menu_dir = self.menus_dir / menu_id
        if not menu_dir.is_dir():
            return []
        versions = (_MENU_VERSION_FILE.match(p.name) for p in menu_dir.iterdir())
        return sorted(int(m.group(1)) for m in versions if m)

    def load_menu(self, catalogue: Catalogue, menu_id: str, version: int | None = None) -> MenuVersion:
        versions = self.menu_versions(menu_id)
        if not versions:
            raise DataError([DataIssue(f"menus/{menu_id}", "", "menu not found")])
        version = versions[-1] if version is None else version
        file = _menu_file(menu_id, version)
        try:
            raw = read_yaml(self.data_dir / file)
        except YamlReadError as e:
            raise DataError([DataIssue(file, "", str(e))]) from None
        menu = parse_model(MenuVersion, raw, file)
        issues = check_menu(menu, catalogue, file)
        if (menu.menu_id, menu.version) != (menu_id, version):
            issues.append(DataIssue(file, "", f"content says {menu.menu_id} v{menu.version}, file location says {menu_id} v{version}"))
        _raise_if(issues)
        return menu

    def save_menu_version(self, catalogue: Catalogue, menu: MenuVersion) -> Path:
        """Store a new menu version. Existing versions are never overwritten."""
        file = _menu_file(menu.menu_id, menu.version)
        issues = check_menu(menu, catalogue, file)
        expected = (self.menu_versions(menu.menu_id) or [0])[-1] + 1
        if menu.version != expected:
            issues.append(DataIssue(file, "", f"next version of {menu.menu_id} must be {expected}, got {menu.version}"))
        _raise_if(issues)
        path = self.data_dir / file
        create_yaml(path, menu.model_dump(mode="json"))
        return path


def _menu_file(menu_id: str, version: int) -> str:
    return f"menus/{menu_id}/v{version:03d}.yaml"


def _raise_if(issues: list[DataIssue]) -> None:
    if issues:
        raise DataError(issues)
