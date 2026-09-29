"""MinerU 하위 블록 펼치기(#986) — 표·그림·그래프에 딸린 제목·각주와 code 블록 글이 사라지지 않는다.

MinerU 는 딸린 글을 부모 항목 안 필드(`table_footnote` 등)로 주고, 하위 블록 bbox 는 middle.json 에만 있다.
실물 모양(2027 생명과학1 정답 p030): 표 몸통 [68,240,459,428] 아래에 각주 둘이 따로 있다.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[3]))

from app.ai.parser import mineru_runner as M  # noqa: E402

W, H = 583, 737          # 2027 EBS 한 쪽 PDF 크기(pt)


def _pt(bb):             # 0~1000 → pt (middle.json 좌표)
    return [bb[0] * W / 1000, bb[1] * H / 1000, bb[2] * W / 1000, bb[3] * H / 1000]


def _raw(tmp_path, blocks):
    raw = tmp_path / "mineru_raw"
    raw.mkdir()
    (raw / "x_middle.json").write_text(json.dumps(
        {"pdf_info": [{"page_size": [W, H], "para_blocks": blocks}]}), encoding="utf-8")
    return raw


def _types(items):
    return [(it["type"], it.get("_nested"), (it.get("text") or it.get("table_body") or "")[:6]) for it in items]


def test_표_각주는_표_뒤에_제자리_bbox로_펼친다(tmp_path):
    body = [68, 240, 459, 428]
    raw = _raw(tmp_path, [{"type": "table", "blocks": [
        {"type": "table_body", "bbox": _pt(body)},
        {"type": "table_footnote", "bbox": _pt([67, 437, 238, 452])},
        {"type": "table_footnote", "bbox": _pt([67, 456, 214, 471])},
    ]}])
    cl = [{"type": "text", "text": "앞 문단"},
          {"type": "table", "bbox": body, "table_body": "<table></table>",
           "table_footnote": ["ㄱ. ⓐ+ⓑ=1+2=3이다.", "ㄴ. ㉠은 X 염색체이다."]},
          {"type": "text", "text": "ㄷ. 뒤 문단"}]
    out = M._unfold_nested(cl, raw)
    assert _types(out) == [("text", None, "앞 문단"), ("table", None, "<table"),
                           ("text", "table_footnote", "ㄱ. ⓐ+ⓑ"), ("text", "table_footnote", "ㄴ. ㉠은 "),
                           ("text", None, "ㄷ. 뒤 문")]
    assert out[2]["bbox"] == [67, 437, 238, 452] and out[2]["_nested_exact"]


def test_인쇄_순서를_따른다_아래_제목은_뒤에(tmp_path):
    body = [100, 100, 500, 300]
    raw = _raw(tmp_path, [{"type": "chart", "blocks": [
        {"type": "chart_body", "bbox": _pt(body)},
        {"type": "chart_caption", "bbox": _pt([100, 305, 500, 320])},
    ]}])
    out = M._unfold_nested([{"type": "chart", "bbox": body, "chart_caption": ["휴지 전위와 활동 전위"]}], raw)
    assert _types(out) == [("chart", None, ""), ("text", "chart_caption", "휴지 전위와")]


def test_위_제목은_앞에(tmp_path):
    body = [100, 120, 500, 300]
    raw = _raw(tmp_path, [{"type": "table", "blocks": [
        {"type": "table_caption", "bbox": _pt([100, 100, 500, 115])},
        {"type": "table_body", "bbox": _pt(body)},
    ]}])
    out = M._unfold_nested([{"type": "table", "bbox": body, "table_body": "<table/>",
                             "table_caption": ["[사례 2] 파스퇴르의 탄저병 백신 개발"]}], raw)
    assert [x.get("_nested") for x in out] == ["table_caption", None]


def test_middle_없으면_제목은_앞_각주는_뒤(tmp_path):
    raw = tmp_path / "mineru_raw"
    raw.mkdir()
    body = [100, 120, 500, 300]
    out = M._unfold_nested([{"type": "table", "bbox": body, "table_body": "<table/>",
                             "table_caption": ["표 제목입니다"], "table_footnote": ["각주 글입니다"]}], raw)
    assert [x.get("_nested") for x in out] == ["table_caption", None, "table_footnote"]
    # 제자리 bbox 를 모르므로 부모 bbox 를 빌리고, 그 자리 텍스트레이어로 덮지 않게 표시한다
    assert out[0]["bbox"] == body and out[0]["_nested_exact"] is False


def test_개수가_안_맞으면_인쇄_순서를_버린다(tmp_path):
    body = [100, 120, 500, 300]
    raw = _raw(tmp_path, [{"type": "image", "blocks": [
        {"type": "image_body", "bbox": _pt(body)},
        {"type": "image_footnote", "bbox": _pt([100, 305, 500, 320])},
    ]}])
    out = M._unfold_nested([{"type": "image", "bbox": body,
                             "image_footnote": ["출처: 가나다", "※ 둘째 각주"]}], raw)
    assert [x.get("_nested") for x in out] == [None, "image_footnote", "image_footnote"]
    assert all(x["_nested_exact"] is False for x in out[1:])


def test_이미_글_블록으로_있으면_넣지_않는다(tmp_path):
    raw = tmp_path / "mineru_raw"
    raw.mkdir()
    out = M._unfold_nested([
        {"type": "table", "bbox": [1, 1, 2, 2], "table_footnote": ["* 단위: 명, 2024년 기준"]},
        {"type": "text", "text": "* 단위: 명, 2024년 기준"},
    ], raw)
    assert [x.get("_nested") for x in out] == [None, None]


def test_짧은_글은_중복이어도_넣는다(tmp_path):
    """①·(가) 같은 조각은 다른 글에 흔히 들어 있다 — 그걸로 지우면 진짜 각주를 잃는다."""
    raw = tmp_path / "mineru_raw"
    raw.mkdir()
    out = M._unfold_nested([
        {"type": "chart", "bbox": [1, 1, 2, 2], "chart_caption": ["(가)"]},
        {"type": "text", "text": "(가)는 학생이 만든 자료이다."},
    ], raw)
    assert [x.get("_nested") for x in out] == ["chart_caption", None, None]   # middle 없음 → 제목은 앞


def test_code_블록은_제자리_글이_된다(tmp_path):
    """수학1 p019: 풀이 전체가 algorithm code 블록으로 와서 통째로 사라졌다(gold 821셀)."""
    raw = tmp_path / "mineru_raw"
    raw.mkdir()
    body = '<div class="mineru-algorithm" style="white-space: pre-wrap;">\n(i) $m=2$일 때, ㉠은\n</div>'
    out = M._unfold_nested([{"type": "text", "text": "앞"},
                            {"type": "code", "sub_type": "algorithm", "bbox": [233, 423, 866, 728],
                             "code_body": body, "code_caption": []},
                            {"type": "text", "text": "답③"}], raw)
    assert [(x["type"], x.get("_nested")) for x in out] == [("text", None), ("text", "code_body"), ("text", None)]
    assert out[1]["text"] == "(i) $m=2$일 때, ㉠은"
    assert out[1]["bbox"] == [233, 423, 866, 728]


def test_code_울타리를_벗긴다():
    assert M._code_text("```txt\n보기\n재다¹「동사」\n```") == "보기\n재다¹「동사」"


def test_image_caption_은_건드리지_않는다(tmp_path):
    """그림의 인쇄 캡션은 run() 의 forced_caption 규칙이 따로 맡는다(그림을 캡션 요소로 바꾼다)."""
    raw = tmp_path / "mineru_raw"
    raw.mkdir()
    it = {"type": "image", "bbox": [1, 1, 2, 2], "image_caption": ["▲ 참호전"]}
    assert M._unfold_nested([it], raw) == [it]


def test_새_플래그는_검토_플래그로_새지_않는다():
    """출처 표시일 뿐이다 — R 플래그로 승격되면 점역사 화면에 소음이 뜬다."""
    from app.ai.quality.quality_checker import _FLAG_TO_REVIEW, _GENERIC_R_FLAG
    for f in ("table_caption", "table_footnote", "image_footnote", "chart_caption",
              "chart_footnote", "code_caption", "code_body"):
        flag = f"MINERU_{f.upper()}"
        assert flag not in _FLAG_TO_REVIEW and not _GENERIC_R_FLAG.match(flag)
        assert not flag.endswith("_FALLBACK")
