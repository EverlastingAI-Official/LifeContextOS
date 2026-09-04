from lifecontext_api.tts_segmentation import pause_seconds_after, segment_for_speech


def test_strong_punctuation_defines_sentence_boundaries() -> None:
    assert segment_for_speech("你好。我是 Mindcopy！你想聊什么？") == [
        "你好。",
        "我是 Mindcopy！",
        "你想聊什么？",
    ]


def test_closing_quote_stays_with_the_sentence() -> None:
    assert segment_for_speech("他说：“继续走。”然后我们出发。") == [
        "他说：“继续走。”",
        "然后我们出发。",
    ]


def test_comma_only_splits_a_long_clause() -> None:
    assert segment_for_speech("很久以前，我还不知道人生上下文会变成一个真正的工程项目，后来它开始生长。", soft_min_chars=18) == [
        "很久以前，我还不知道人生上下文会变成一个真正的工程项目，",
        "后来它开始生长。",
    ]


def test_unpunctuated_text_has_a_safety_limit() -> None:
    parts = segment_for_speech("一二三四五六七八九十一二三四五六七八九十", hard_max_chars=10)
    assert parts == ["一二三四五六七八九十", "一二三四五六七八九十"]


def test_pause_tracks_punctuation_strength() -> None:
    assert pause_seconds_after("你好吗？") > pause_seconds_after("如果可以，")
