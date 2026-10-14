"""목록표 빈칸 이름은 gRPC 응답 경계에서 한 방향으로 바뀐다(#1382).

`test/unit_test/braille/test_text_style_tags_1382.py` 에서 옮겼다. CI test-fast 는 proto 를 빌드하지 않고
`test/unit_test/braille/` 만 돌아 `grpc_server` 를 부르는 시험은 여기 둔다.
"""
from app.ai.braille.translator import translate_tagged_text


def test_별칭은_한_방향이다_나가는_묵자는_목록표_이름이다():
    """목록표 이름이 정본이다(#1382). 서버 안 엔진 이름(교열이 낸 `<!밑줄>` · `<!네모>`)은 gRPC 응답에서 목록표 이름으로
    바뀌어 나가고, 옛 이름은 안 나간다. `<!네모글>`(네모 문자)은 다른 태그라 그대로다."""
    from app.core.grpc_server import _dict_to_text_element
    old = "다음 <!밑줄>에 <!네모> 와 <!네모글>가<!/네모글>"
    e = _dict_to_text_element({"contents": [old], "tn_text": old, "table_source": old,
                               "drafts": [{"text": old, "tn_text": old, "label": "안"}]})
    for got in (e.contents[0], e.tn_text, e.table_source, e.drafts[0].text, e.drafts[0].tn_text):
        assert got == "다음 <!밑줄빈칸>에 <!네모빈칸> 와 <!네모글>가<!/네모글>"
    # 그 글을 다시 점역하면 엔진 이름으로 읽혀 같은 점자다(들어오는 쪽).
    assert translate_tagged_text(e.contents[0]) == translate_tagged_text(old)
