"""#1431 단을 넘는 문단의 뒷부분이 두 번 나가던 문제.

MinerU 는 단을 넘는 문단을 앞 블록에 합치고 뒤 블록을 middle.json 에 `lines_deleted` 로 비우는데, content_list 에는
그 뒤 블록이 빈 글 · 원래 bbox 로 남는다. 층 덮기가 그 빈 글을 다시 채우므로, 채운 글이 앞 글 요소에 이미 통째로 있을
때만 버린다(앞 블록이 층으로 앞부분만 남았으면 뒤 조각이 유일한 사본이다).
"""
import json

from app.ai.parser.mineru_runner import _merged_away, _merged_dup

HEAD = "⑤ #1에서 학생은 저녁 식사 후 쉴 겸 짧게 영상을 보려고 했으나 "
TAIL = "#2의 줌 아웃을 통해 늦은 밤까지 스마트폰을 들고 홀로 영상에 집중하고 있음을 확인할 수 있다."
GONE = [514, 84, 910, 208]                    # 오른쪽 단 맨 위(0~1000)


def test_비운_블록_bbox_를_0_1000_으로_읽는다(tmp_path):
    (tmp_path / "x_middle.json").write_text(json.dumps({"pdf_info": [{"page_size": [584, 737], "para_blocks": [
        {"bbox": [48, 667, 278, 680], "lines": [{}]},
        {"bbox": [300, 62, 531, 154], "lines": [], "lines_deleted": True}]}]}), encoding="utf-8")
    (got,) = _merged_away(tmp_path)
    assert [round(v) for v in got] == [514, 84, 909, 209]
    assert _merged_away(tmp_path / "없음") == []


def test_앞_요소에_이미_든_뒷조각만_버린다():
    item = {"type": "text", "text": "", "bbox": GONE}
    host_merged = [{"type": "text", "content": HEAD + TAIL}]        # MinerU 가 합친 글을 그대로 둔 앞 요소
    host_cut = [{"type": "text", "content": HEAD}]                  # 층으로 갈아 끼워 앞부분만 남은 앞 요소
    assert _merged_dup(item, TAIL, [GONE], host_merged)
    assert not _merged_dup(item, TAIL, [GONE], host_cut)


def test_글이_있던_블록_딴_자리_짧은_글은_안_버린다():
    host = [{"type": "text", "content": HEAD + TAIL}]
    assert not _merged_dup({"type": "text", "text": TAIL, "bbox": GONE}, TAIL, [GONE], host)
    assert not _merged_dup({"type": "text", "text": "", "bbox": [100, 84, 400, 208]}, TAIL, [GONE], host)
    assert not _merged_dup({"type": "text", "text": "", "bbox": GONE}, "있다.", [GONE], host)
