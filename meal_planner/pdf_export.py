"""Printable English recipe book for one menu version (Phase 9, ADR-021).

Layout (A4): a cover page with the four-week dinner table, then one section per
dish in order of first appearance: ingredients with quantities, numbered steps,
and notes. Quantities come from the recipe data; all wording comes from the
checked translations. Shopping lists are not included.
"""

from collections.abc import Sequence
from io import BytesIO
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import KeepTogether, ListFlowable, ListItem, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from .models import Dish, MenuVersion
from .translation import DishTranslation

DISH_TYPE_EN = {"vegetarian": "Vegetable dish", "mixed": "Meat and vegetable dish", "meat": "Main meat dish", "soup": "Soup"}


class ExportError(Exception):
    pass


def dishes_in_order(menu: MenuVersion) -> list[str]:
    return list(dict.fromkeys(k for d in menu.dinners for k in d.dish_ids))


def build_menu_pdf(
    menu: MenuVersion, dishes: dict[str, Dish], translations: dict[str, DishTranslation], compress: bool = True
) -> bytes:
    order = dishes_in_order(menu)
    missing = [k for k in order if k not in translations]
    if missing:
        raise ExportError(f"missing translations: {', '.join(missing)}")

    styles = getSampleStyleSheet()
    small = ParagraphStyle("small", parent=styles["BodyText"], fontSize=8.5, leading=10.5)
    note = ParagraphStyle("note", parent=styles["BodyText"], textColor=colors.HexColor("#555555"), fontName="Helvetica-Oblique")
    text = lambda s, style=styles["BodyText"]: Paragraph(escape(s), style)  # noqa: E731

    story = [
        text("Family Dinner Menu", styles["Title"]),
        text(f"Four weeks from {menu.start_date:%A %d %B %Y} - menu {menu.menu_id}, version {menu.version}", styles["Heading4"]),
        Spacer(1, 4 * mm),
        _menu_table(menu, translations, text, small),
        PageBreak(),
        text("Recipes", styles["Heading1"]),
    ]
    served_on = {k: [d.date for d in menu.dinners if k in d.dish_ids] for k in order}
    for dish_id in order:
        story += _recipe(dishes[dish_id], translations[dish_id], served_on[dish_id], text, styles, note)

    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4, leftMargin=16 * mm, rightMargin=16 * mm, topMargin=16 * mm, bottomMargin=16 * mm,
        title=f"Dinner menu {menu.menu_id} v{menu.version}", pageCompression=1 if compress else 0,
    )
    doc.build(story, onFirstPage=_page_number, onLaterPages=_page_number)
    return buffer.getvalue()


def _menu_table(menu: MenuVersion, translations, text, small) -> Table:
    rows = [[text("", small)] + [text(day, small) for day in ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday")]]
    for week in range(4):
        cells = [text(f"Week {week + 1}", small)]
        for dinner in menu.dinners[week * 5:week * 5 + 5]:
            lines = [f"{dinner.date:%d %b}"] + [translations[k].name_en for k in dinner.dish_ids]
            cells.append([text(lines[0], small)] + [text(f"- {name}", small) for name in lines[1:]])
        rows.append(cells)
    table = Table(rows, colWidths=[16 * mm] + [34 * mm] * 5, repeatRows=1)
    table.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#bbbbbb")),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e8f2ed")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))
    return table


def _quantity(value: float) -> str:
    return str(int(value)) if value == int(value) else f"{value:g}"


def _recipe(dish: Dish, t: DishTranslation, dates: Sequence, text, styles, note) -> list:
    meta = [DISH_TYPE_EN[dish.dish_type]] + ([f"serves {dish.servings}"] if dish.servings else [])
    meta.append("served on " + ", ".join(f"{d:%a %d %b}" for d in dates))
    ingredients = []
    for line, name, unit, line_note in zip(dish.ingredients, t.ingredient_names, t.units, t.notes):
        amount = " ".join(p for p in (_quantity(line.quantity) if line.quantity else "", unit or "") if p)
        ingredients.append(f"{amount} {name}".strip() + (f" ({line_note})" if line_note else ""))
    header = [
        text(t.name_en, styles["Heading2"]),
        text(" | ".join(meta), note),
        text("Ingredients", styles["Heading4"]),
        ListFlowable([ListItem(text(i), leftIndent=10) for i in ingredients], bulletType="bullet", start="-"),
    ]
    body = [
        text("Method", styles["Heading4"]),
        ListFlowable([ListItem(text(s)) for s in t.steps], bulletType="1") if t.steps else text("(no steps recorded)", note),
    ]
    if t.uncertainty_notes:
        body.append(text(f"Notes: {t.uncertainty_notes}", note))
    return [KeepTogether(header), *body, Spacer(1, 6 * mm)]


def _page_number(canvas, doc):
    canvas.saveState()
    canvas.setFont("Helvetica", 8)
    canvas.drawRightString(A4[0] - 16 * mm, 10 * mm, f"Page {doc.page}")
    canvas.restoreState()
