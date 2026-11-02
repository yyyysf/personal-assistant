"""小红书 JSON 解析单元测试。"""

import json

import pytest

from src.core.xhs import XhsParseError, parse_export


def test_parse_list_export():
    notes = parse_export(
        json.dumps(
            [
                {
                    "title": "收藏一",
                    "desc": "推荐《思考，快与慢》",
                    "author": {"nickname": "博主A"},
                },
                {"desc": "没有标题的笔记内容", "url": "https://example.com/note/2"},
            ],
            ensure_ascii=False,
        )
    )
    assert len(notes) == 2
    assert notes[0]["title"] == "收藏一"
    assert notes[0]["author"] == "博主A"
    assert notes[1]["title"] == "没有标题的笔记内容"


def test_parse_dict_wrapper_and_text_fallback():
    wrapped = {"data": {"notes": [{"title": "嵌套笔记", "desc": "内容"}]}}
    notes = parse_export(json.dumps(wrapped, ensure_ascii=False))
    assert notes[0]["title"] == "嵌套笔记"

    notes = parse_export("这是一段普通文本，提到《人类简史》。")
    assert notes[0]["desc"].startswith("这是一段普通文本")


def test_parse_invalid_payload():
    with pytest.raises(XhsParseError):
        parse_export("")
    with pytest.raises(XhsParseError):
        parse_export(42)  # type: ignore[arg-type]
