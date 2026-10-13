"""Recipe import from Bilibili / YouTube videos (Phase 8, ADR-020).

Pipeline: URL check -> metadata and subtitles via yt-dlp (no video or audio is
downloaded) -> recipe extraction by Claude from that text only -> deterministic
ingredient matching -> schema validation -> pending review.

Speech recognition is not available (no local models; the Claude CLI cannot take
audio). A video without subtitles is imported from its description only if the
description is long enough; otherwise the import fails clearly instead of
inventing a recipe. Ingredients that do not match the catalogue become
`unmatched_name` lines; the catalogue is never changed.
"""

import json
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, ValidationError

from .candidates import next_dish_number
from .catalogue import Catalogue
from .llm import LLMBackend
from .models import Dish, DishesFile, Ingredient
from .readonly import ReadOnlyCatalogue
from .store import DataStore
from .vocab import CookingMethod, DishType, Flavour

MAX_TEXT_CHARS = 20000  # longer transcripts are cut, and the cut is noted
MIN_DESCRIPTION_CHARS = 60  # a description shorter than this is not enough to extract a recipe from
PREFERRED_LANGUAGES = ["zh-Hans", "zh-CN", "zh", "ai-zh", "zh-Hant", "zh-TW", "en", "en-US", "en-GB"]
IGNORED_TRACKS = {"danmaku", "live_chat"}
FORMAT_ORDER = ["vtt", "srt", "json3", "json"]  # subtitle formats we can read, preferred first


class VideoImportError(Exception):
    pass


@dataclass(frozen=True)
class VideoRef:
    platform: Literal["youtube", "bilibili"]
    video_id: str
    url: str


_PATTERNS = [
    ("youtube", re.compile(r"^https?://(?:www\.|m\.)?youtube\.com/(?:watch\?(?:[^#]*&)?v=|shorts/|embed/)([A-Za-z0-9_-]{11})")),
    ("youtube", re.compile(r"^https?://youtu\.be/([A-Za-z0-9_-]{11})")),
    ("bilibili", re.compile(r"^https?://(?:www\.|m\.)?bilibili\.com/video/(BV[0-9A-Za-z]{10}|av\d+)")),
    ("bilibili", re.compile(r"^https?://b23\.tv/([0-9A-Za-z]+)")),
]


def parse_video_url(url: str) -> VideoRef:
    url = url.strip()
    for platform, pattern in _PATTERNS:
        match = pattern.match(url)
        if match:
            return VideoRef(platform, match.group(1), url)
    raise VideoImportError("只支持 YouTube（youtube.com/watch?v=…、youtu.be/…）和 Bilibili（bilibili.com/video/BV…、b23.tv/…）的视频链接")


@dataclass(frozen=True)
class VideoText:
    title: str
    description: str
    transcript: str | None
    transcript_kind: Literal["subtitles", "auto_captions"] | None
    language: str | None


class VideoSource(Protocol):
    def fetch(self, ref: VideoRef) -> VideoText: ...


class YtDlpSource:
    """Reads title, description and one subtitle track; never downloads the video."""

    def fetch(self, ref: VideoRef) -> VideoText:
        import yt_dlp

        options = {"quiet": True, "no_warnings": True, "skip_download": True, "noplaylist": True}
        try:
            with yt_dlp.YoutubeDL(options) as ydl:
                info = ydl.extract_info(ref.url, download=False)
                transcript, kind, language = pick_transcript(info, lambda u: ydl.urlopen(u).read().decode("utf-8", "replace"))
        except yt_dlp.utils.DownloadError as e:
            raise VideoImportError(f"无法读取该视频（可能不存在、需要登录或受地区限制）：{e}") from None
        return VideoText(info.get("title") or "", info.get("description") or "", transcript, kind, language)


def pick_transcript(info: dict, download) -> tuple[str | None, str | None, str | None]:
    """Choose one subtitle track: uploaded subtitles first, then automatic captions in the video's language."""
    for kind, tracks in (("subtitles", info.get("subtitles") or {}), ("auto_captions", info.get("automatic_captions") or {})):
        order = ([info["language"]] if kind == "auto_captions" and info.get("language") else []) + PREFERRED_LANGUAGES
        if kind == "subtitles":
            order += sorted(tracks)
        for language in order:
            formats = [f for f in tracks.get(language) or [] if f.get("ext") in FORMAT_ORDER]
            if not formats or language in IGNORED_TRACKS:
                continue
            fmt = min(formats, key=lambda f: FORMAT_ORDER.index(f["ext"]))
            text = subtitle_to_text(download(fmt["url"]), fmt["ext"])
            if text:
                return text, kind, language
    return None, None, None


def subtitle_to_text(raw: str, ext: str) -> str:
    """Plain text from VTT/SRT/JSON subtitles, with consecutive duplicate lines removed."""
    if ext in ("json3", "json"):
        data = json.loads(raw)
        if "events" in data:  # YouTube json3
            lines = ["".join(s.get("utf8", "") for s in e.get("segs") or []) for e in data["events"]]
        else:  # Bilibili
            lines = [item.get("content", "") for item in data.get("body", [])]
    else:
        lines = [
            re.sub(r"<[^>]+>", "", line)
            for line in raw.splitlines()
            if line.strip() and "-->" not in line and not line.strip().isdigit()
            and not line.startswith(("WEBVTT", "Kind:", "Language:", "NOTE"))
        ]
    result = []
    for line in (l.strip() for l in lines):
        if line and (not result or result[-1] != line):
            result.append(line)
    return "\n".join(result)


# --- Extraction ----------------------------------------------------------------------


class ExtractedLine(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str  # the ingredient as mentioned in the video
    ingredient_id: str | None = None  # only from the provided list
    quantity: float | None = None
    unit: str | None = None
    note: str | None = None
    main: bool = False


class ExtractedRecipe(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name_zh: str
    name_en: str | None = None
    dish_type: DishType
    servings: int | None = None
    ingredients: list[ExtractedLine]
    steps: list[str]
    cooking_method: CookingMethod | None = None
    flavours: list[Flavour] = []
    cuisine: str | None = None
    uncertainty_notes: str


class ExtractionOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    found_recipe: bool
    reason: str
    recipe: ExtractedRecipe | None = None


SYSTEM_PROMPT = """\
You extract one home-cooking recipe from the text of a cooking video (title, description, subtitles), usually Chinese.

Rules:
- Use only what the text states or clearly implies. Never add ingredients, amounts or steps that are not there.
- If an amount is not stated, leave quantity and unit null (use note for words like "适量").
- Subtitles may contain recognition errors; correct obvious ones and mention them in uncertainty_notes.
- Write name_zh, steps and notes in Chinese. Mark the 1-2 defining ingredients with main=true.
- For each ingredient give the name as mentioned, and ingredient_id only if it clearly matches an entry of the \
ingredient list below; otherwise ingredient_id null.
- uncertainty_notes must say what is unclear or missing (amounts, timing, steps not shown in text).
- If the text does not contain a recipe, set found_recipe false, recipe null, and explain in reason.

Dish types: vegetarian (素菜), mixed (荤素搭配), meat (大荤), soup (汤).

Ingredient list (id, name, aliases):
{ingredients}
"""


@dataclass(frozen=True)
class ImportResult:
    dish: Dish
    text_source: str  # subtitles | auto_captions | description
    title: str
    truncated: bool


def import_video(
    store: DataStore, cat: Catalogue, llm: LLMBackend, source: VideoSource, url: str
) -> tuple[Catalogue, ImportResult]:
    ref = parse_video_url(url)
    video = source.fetch(ref)

    if video.transcript:
        text_source, body = video.transcript_kind, video.transcript
    elif len(video.description.strip()) >= MIN_DESCRIPTION_CHARS:
        text_source, body = "description", ""
    else:
        raise VideoImportError("该视频没有可读取的字幕，简介文字也太少，无法提取菜谱（目前不支持语音识别）")

    text = f"Title: {video.title}\n\nDescription:\n{video.description}\n\nSubtitles:\n{body or '(none)'}"
    truncated = len(text) > MAX_TEXT_CHARS
    view = ReadOnlyCatalogue(cat)
    raw = llm.structured(_system_prompt(view), text[:MAX_TEXT_CHARS], ExtractionOutput.model_json_schema())

    try:
        output = ExtractionOutput.model_validate(raw)
    except ValidationError as e:
        err = e.errors()[0]
        raise VideoImportError(f"提取结果格式无效：{'.'.join(str(p) for p in err['loc'])}: {err['msg']}") from None
    if not output.found_recipe or output.recipe is None:
        raise VideoImportError(f"没有从视频文字中找到菜谱：{output.reason}")

    dish = _to_dish(output.recipe, {i.ingredient_id: i for i in view.ingredients()}, cat, ref, text_source, truncated)
    cat = store.save_pending_dishes(cat, DishesFile(dishes=cat.pending_dishes.dishes + (dish,)))
    return cat, ImportResult(dish, text_source, video.title, truncated)


SOURCE_NOTES = {"subtitles": "根据上传者提供的字幕提取", "auto_captions": "根据平台自动生成的字幕提取，可能有识别错误",
                "description": "视频没有字幕，仅根据简介提取，可能不完整"}


def _to_dish(recipe: ExtractedRecipe, ingredients: dict[str, Ingredient], cat, ref, text_source, truncated) -> Dish:
    lines, mains = [], []
    for line in recipe.ingredients:
        ingredient_id = line.ingredient_id if line.ingredient_id in ingredients else match_ingredient(line.name, ingredients)
        lines.append({
            "ingredient_id": ingredient_id,
            "unmatched_name": None if ingredient_id else line.name.strip(),
            "quantity": line.quantity if line.quantity and line.quantity > 0 else None,
            "unit": line.unit if line.quantity and line.quantity > 0 else None,
            "note": line.note,
        })
        if line.main and ingredient_id:
            mains.append(ingredient_id)
    notes = [recipe.uncertainty_notes.strip(), SOURCE_NOTES[text_source]] + (["视频文字过长，只使用了前一部分"] if truncated else [])
    try:
        return Dish.model_validate({
            "dish_id": f"dish_{next_dish_number(cat):04d}",
            "name_zh": recipe.name_zh,
            "name_en": recipe.name_en,
            "dish_type": recipe.dish_type,
            "servings": recipe.servings if recipe.servings and recipe.servings > 0 else None,
            "ingredients": lines,
            "steps": [s for s in recipe.steps if s.strip()],
            "style": {"main_ingredients": list(dict.fromkeys(mains)), "cooking_method": recipe.cooking_method,
                      "flavours": recipe.flavours, "cuisine": recipe.cuisine},
            "source": "video_imported",
            "source_url": ref.url,
            "review_status": "pending",
            "uncertainty_notes": "；".join(n for n in notes if n),
            "created_at": datetime.now().replace(microsecond=0),
        })
    except ValidationError as e:
        err = e.errors()[0]
        raise VideoImportError(f"提取的菜谱不完整：{'.'.join(str(p) for p in err['loc'])}: {err['msg']}") from None


def match_ingredient(name: str, ingredients: dict[str, Ingredient]) -> str | None:
    """Exact match on Chinese name, alias or English name (case-insensitive); no fuzzy guessing."""
    key = name.strip().lower()
    for i in ingredients.values():
        if key in {i.name_zh.lower(), *(a.lower() for a in i.aliases), (i.name_en or "").lower()} - {""}:
            return i.ingredient_id
    return None


def _system_prompt(view: ReadOnlyCatalogue) -> str:
    listing = "\n".join(
        f"{i.ingredient_id} {i.name_zh}" + (f" ({', '.join(i.aliases)})" if i.aliases else "") for i in view.ingredients()
    )
    return SYSTEM_PROMPT.format(ingredients=listing or "(empty)")
