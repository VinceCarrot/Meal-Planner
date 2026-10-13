import json

import pytest

from fakes import FakeLLM
from meal_planner.video_import import (
    VideoImportError,
    VideoText,
    import_video,
    match_ingredient,
    parse_video_url,
    pick_transcript,
    subtitle_to_text,
)

URL = "https://www.bilibili.com/video/BV1xx411c7mD"


@pytest.mark.parametrize(
    "url, platform, video_id",
    [
        ("https://www.youtube.com/watch?v=dQw4w9WgXcQ", "youtube", "dQw4w9WgXcQ"),
        ("https://www.youtube.com/watch?list=x&v=dQw4w9WgXcQ&t=10", "youtube", "dQw4w9WgXcQ"),
        ("https://youtu.be/dQw4w9WgXcQ", "youtube", "dQw4w9WgXcQ"),
        ("https://www.youtube.com/shorts/dQw4w9WgXcQ", "youtube", "dQw4w9WgXcQ"),
        ("  https://www.bilibili.com/video/BV1xx411c7mD?p=1 ", "bilibili", "BV1xx411c7mD"),
        ("https://m.bilibili.com/video/av170001", "bilibili", "av170001"),
        ("https://b23.tv/AbC123", "bilibili", "AbC123"),
    ],
)
def test_supported_urls(url, platform, video_id):
    ref = parse_video_url(url)
    assert (ref.platform, ref.video_id) == (platform, video_id)


@pytest.mark.parametrize("url", ["", "bilibili BV1xx411c7mD", "https://vimeo.com/123", "file:///etc/passwd",
                                 "https://www.youtube.com/watch?v=short", "https://evil.example/bilibili.com/video/BV1xx411c7mD"])
def test_unsupported_urls_fail_clearly(url):
    with pytest.raises(VideoImportError, match="只支持"):
        parse_video_url(url)


def test_vtt_to_text_drops_timing_and_duplicates():
    vtt = "WEBVTT\nKind: captions\n\n00:00:01.000 --> 00:00:02.000\n先把<c>鸡蛋</c>打散\n\n00:00:02.000 --> 00:00:03.000\n先把鸡蛋打散\n\n2\n00:00:03.000 --> 00:00:04.000\n加盐\n"
    assert subtitle_to_text(vtt, "vtt") == "先把鸡蛋打散\n加盐"


def test_json_subtitles():
    youtube = json.dumps({"events": [{"segs": [{"utf8": "番茄"}, {"utf8": "切块"}]}, {"tStartMs": 1}]})
    bilibili = json.dumps({"body": [{"content": "热锅"}, {"content": "下油"}]})
    assert subtitle_to_text(youtube, "json3") == "番茄切块"
    assert subtitle_to_text(bilibili, "json") == "热锅\n下油"


def test_uploaded_subtitles_are_preferred_and_danmaku_ignored():
    info = {
        "subtitles": {"danmaku": [{"ext": "xml", "url": "d"}], "en": [{"ext": "vtt", "url": "en"}]},
        "automatic_captions": {"zh-Hans": [{"ext": "vtt", "url": "auto"}]},
    }
    fetched = []
    text, kind, lang = pick_transcript(info, lambda u: fetched.append(u) or "00:00 --> 00:01\nhello")
    assert (text, kind, lang, fetched) == ("hello", "subtitles", "en", ["en"])


def test_automatic_captions_in_the_video_language():
    info = {"language": "zh-Hans", "automatic_captions": {"en": [{"ext": "vtt", "url": "en"}], "zh-Hans": [{"ext": "json3", "url": "zh"}]}}
    text, kind, lang = pick_transcript(info, lambda u: json.dumps({"events": [{"segs": [{"utf8": u}]}]}))
    assert (text, kind, lang) == ("zh", "auto_captions", "zh-Hans")
    assert pick_transcript({}, lambda u: "") == (None, None, None)


class FakeSource:
    def __init__(self, text: VideoText):
        self.text = text
        self.refs = []

    def fetch(self, ref):
        self.refs.append(ref)
        return self.text


SUBTITLED = VideoText("家常番茄炒蛋", "简单快手菜", "先把三个鸡蛋打散……", "auto_captions", "zh-Hans")


def recipe(**changes):
    base = {
        "name_zh": "番茄炒鸡蛋", "dish_type": "vegetarian", "servings": 3,
        "ingredients": [
            {"name": "西红柿", "quantity": 2, "unit": "个", "main": True},
            {"name": "鸡蛋", "ingredient_id": "ing_egg", "quantity": 3, "unit": "个", "main": True},
            {"name": "葱花", "note": "少许"},
            {"name": "盐", "ingredient_id": "ing_salt_made_up"},
        ],
        "steps": ["鸡蛋打散炒熟", "番茄炒软后混合"],
        "cooking_method": "stir_fry", "flavours": ["sweet_sour"],
        "uncertainty_notes": "视频没有说明盐的用量",
    }
    return {"found_recipe": True, "reason": "", "recipe": base | changes}


def test_import_creates_a_pending_candidate_with_matched_and_flagged_ingredients(store, data_dir):
    ingredients_before = (data_dir / "ingredients.yaml").read_bytes()
    dishes_before = (data_dir / "dishes.yaml").read_bytes()
    llm = FakeLLM(recipe())

    cat, result = import_video(store, store.load(), llm, FakeSource(SUBTITLED), URL)

    dish = result.dish
    assert (dish.source, dish.review_status, dish.source_url) == ("video_imported", "pending", URL)
    lines = [(l.ingredient_id, l.unmatched_name) for l in dish.ingredients]
    assert lines == [("ing_tomato", None), ("ing_egg", None), (None, "葱花"), (None, "盐")]  # alias match; unknown id not trusted
    assert dish.style.main_ingredients == ("ing_tomato", "ing_egg")
    assert "盐的用量" in dish.uncertainty_notes and "自动生成的字幕" in dish.uncertainty_notes
    assert dish.dish_id in {d.dish_id for d in store.load().pending_dishes.dishes}
    assert (data_dir / "ingredients.yaml").read_bytes() == ingredients_before
    assert (data_dir / "dishes.yaml").read_bytes() == dishes_before
    assert "Subtitles:\n先把三个鸡蛋打散" in llm.calls[0]["prompt"]
    assert "ing_tomato 番茄 (西红柿)" in llm.calls[0]["system"]


def test_video_without_subtitles_or_description_fails_without_calling_claude(store):
    llm = FakeLLM(recipe())
    source = FakeSource(VideoText("番茄炒蛋", "好吃", None, None, None))
    with pytest.raises(VideoImportError, match="不支持语音识别"):
        import_video(store, store.load(), llm, source, URL)
    assert llm.calls == []


def test_description_only_import_is_marked(store):
    description = "用料：番茄两个、鸡蛋三个、葱花少许、盐适量。做法：鸡蛋打散后下锅炒熟盛出；番茄切块，下锅炒出汁；倒入炒好的鸡蛋一起翻炒，加盐调味，撒葱花即可出锅。"
    _, result = import_video(store, store.load(), FakeLLM(recipe()), FakeSource(VideoText("番茄炒蛋", description, None, None, None)), URL)
    assert result.text_source == "description" and "仅根据简介" in result.dish.uncertainty_notes


def test_text_without_a_recipe_is_not_imported(store, data_dir):
    before = (data_dir / "pending_dishes.yaml").read_bytes()
    llm = FakeLLM({"found_recipe": False, "reason": "这是一个探店视频", "recipe": None})
    with pytest.raises(VideoImportError, match="探店"):
        import_video(store, store.load(), llm, FakeSource(SUBTITLED), URL)
    assert (data_dir / "pending_dishes.yaml").read_bytes() == before


@pytest.mark.parametrize("output", [None, {"found_recipe": True}, recipe(dish_type="dessert"), recipe(ingredients=[]),
                                    recipe(ingredients=[{"name": "鸡蛋", "quantity": 2}]) | {"extra": 1}])
def test_invalid_extraction_is_rejected(store, data_dir, output):
    before = (data_dir / "pending_dishes.yaml").read_bytes()
    with pytest.raises(VideoImportError):
        import_video(store, store.load(), FakeLLM(output), FakeSource(SUBTITLED), URL)
    assert (data_dir / "pending_dishes.yaml").read_bytes() == before


def test_long_transcripts_are_cut_and_noted(store):
    long = VideoText("长视频", "", "很长的字幕。" * 5000, "subtitles", "zh")
    llm = FakeLLM(recipe())
    _, result = import_video(store, store.load(), llm, FakeSource(long), URL)
    assert result.truncated and len(llm.calls[0]["prompt"]) == 20000
    assert "只使用了前一部分" in result.dish.uncertainty_notes


def test_exact_matching_only(store):
    ingredients = {i.ingredient_id: i for i in store.load().ingredients.ingredients}
    assert match_ingredient(" 西红柿 ", ingredients) == "ing_tomato"
    assert match_ingredient("TOFU", ingredients) == "ing_tofu"
    assert match_ingredient("番茄酱", ingredients) is None
    assert match_ingredient("", ingredients) is None
