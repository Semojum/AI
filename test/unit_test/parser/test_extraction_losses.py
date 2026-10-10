"""추출 손실 목록(T35) — 추출이 못 본 글(unseen)과 MinerU 는 봤는데 경계까지 못 온 글(dropped).

T33 에서 손으로 가른 층 대조(D 묵자에 있음·추출 못 봄 / C MinerU 봄·우리 변환에서 빠짐)를
파이프라인이 스스로 단다. 실물 꼴: 언매 p198 카드 뉴스(MinerU 가 그림 한 장으로 잡음 → figure_text),
수학1 p019 풀이(`code` 블록 → 옛 변환기가 버림 → not_carried), 〈보기〉 상자 밖 대화(영역 없음 → unseen).
"""
import json
import sys
from pathlib import Path

import fitz
import pytest

sys.path.insert(0, str(Path(__file__).parents[3]))

from app.ai.builder import result_builder as rb  # noqa: E402
from app.ai.parser import extraction_losses as L  # noqa: E402
from app.ai.preprocessor.line_join import join_wrapped_lines  # noqa: E402

KEPT = "학생들은 수업 시간에 자기 생각을 발표하였다."
DROP = "이 글은 MinerU 가 읽었지만 경계로 옮겨지지 않았다."
UNSEEN = "추출기가 아예 영역을 잡지 못한 줄이다."
CARD = "카드 뉴스 속 글자는 레이어에 멀쩡히 있다."


def _page():
    doc = fitz.open()
    pg = doc.new_page(width=500, height=1000)
    for y, t in ((100, KEPT), (200, DROP), (300, UNSEEN), (600, CARD)):
        pg.insert_text((50, y), t, fontname="korea", fontsize=9)
    return doc, pg


def _raw(tmp_path, items):
    raw = tmp_path / "mineru_raw"
    raw.mkdir()
    (raw / "p_content_list.json").write_text(json.dumps(items, ensure_ascii=False), encoding="utf-8")
    return raw


ITEMS = [
    {"type": "text", "text": KEPT, "bbox": [90, 85, 900, 105]},
    {"type": "text", "text": DROP, "bbox": [90, 185, 900, 205]},
    {"type": "image", "content": "", "bbox": [80, 560, 920, 640]},   # 카드 뉴스 면을 그림 한 장으로
]


def _by(losses):
    return {x["class"]: x for x in losses}


def test_세_갈래를_스스로_단다(tmp_path):
    doc, pg = _page()
    losses, checks = L.extraction_losses(
        [{"content": KEPT}, {"content": "이미지 캡셔닝 대기"}], pg, _raw(tmp_path, ITEMS))
    assert checks == ["mineru", "text_layer"]
    got = sorted((x["class"], x["source"], x.get("reason")) for x in losses)
    assert got == [("dropped", "mineru:image", "figure_text"),
                   ("dropped", "mineru:text", "not_carried"),
                   ("unseen", "textlayer", None)]
    fig = next(x for x in losses if x.get("reason") == "figure_text")
    assert "카드 뉴스" in fig["text"]            # 그림 안 글은 레이어에서 읽어 적는다
    un = _by(losses)["unseen"]
    assert "영역을 잡지 못한" in un["text"] and un["region"] is None
    assert 0 <= un["bbox"][1] < un["bbox"][3] <= 1000 and un["bbox"][1] < 300   # 0~1000 정규화


def test_경계에_있으면_손실이_아니다(tmp_path):
    doc, pg = _page()
    kept = [{"content": t} for t in (KEPT, DROP, UNSEEN, CARD)]
    assert L.extraction_losses(kept, pg, _raw(tmp_path, ITEMS))[0] == []


def test_태그가_끼어도_대조한다(tmp_path):
    """경계 요소에는 `<!상자>`·표 태그가 들어간다 — 태그 이름 글자가 대조를 흐리면 안 된다."""
    doc, pg = _page()
    kept = [{"content": f"<!상자><!/상자>{KEPT}<!상자끝><!/상자끝>"},
            {"content": f"<!표><!행><!칸>{DROP}<!/칸><!/행><!/표>"}]
    losses, _ = L.extraction_losses(kept, pg, _raw(tmp_path, ITEMS[:2]))
    assert [x["class"] for x in losses] == ["unseen", "unseen"]      # 레이어의 UNSEEN · CARD 줄만


def test_펼친_필드는_필드_이름으로_적는다(tmp_path):
    doc, pg = _page()
    items = [{"type": "table", "table_body": "<table><tr><td>구분</td></tr></table>",
              "table_footnote": ["* 표의 수치는 2025년 기준 통계청 자료이다."], "bbox": [90, 700, 900, 800]}]
    losses, _ = L.extraction_losses([{"content": "구분"}], pg, _raw(tmp_path, items))
    src = [x["source"] for x in losses if x["class"] == "dropped"]
    assert src == ["mineru:table_footnote"]


def test_MinerU_가_없으면_레이어만_대조한다(tmp_path):
    """ZERO 티어(TEXT_NATIVE)는 MinerU 를 안 돈다 — 'mineru' 가 checks 에서 빠진다."""
    doc, pg = _page()
    losses, checks = L.extraction_losses([{"content": KEPT}, {"content": DROP}], pg, None)
    assert checks == ["text_layer"]
    assert [x["class"] for x in losses] == ["unseen", "unseen"]      # 레이어 블록마다 한 건
    assert "영역을" in losses[0]["text"] and "카드" in losses[1]["text"]


def test_스캔본이면_unseen_을_안_잰다(tmp_path, monkeypatch):
    """스캔본 위의 글은 남의 OCR — 목록이 비었다고 손실이 없는 게 아니다. checks 로 알린다."""
    monkeypatch.setattr(L, "_is_scanned_page", lambda page: True)
    doc, pg = _page()
    losses, checks = L.extraction_losses([{"content": KEPT}], pg, _raw(tmp_path, ITEMS))
    assert checks == ["mineru"]
    assert {x["class"] for x in losses} == {"dropped"}


def test_깨진_글자만_빼고_줄은_남긴다():
    """언매 실물 — ◇ 가 PUA, 글머리 구분이 제어 문자로 나온다. 줄째 버리면 멀쩡한 한글이 대조에서 빠진다."""
    assert L._BAD_CHAR_RE.sub("", "이번 주부터 우리 \ue280\u2009\ue280\u2009시 주요 뉴스") == \
        "이번 주부터 우리 \u2009\u2009시 주요 뉴스"
    assert L._BAD_CHAR_RE.sub("", "•\x07Ⅰ~Ⅲ의 전체 개체 수는") == "•Ⅰ~Ⅲ의 전체 개체 수는"
    assert L._BAD_CHAR_RE.sub("", "‘\uf537녀긔’") == "‘녀긔’"


def test_짧은_줄이_이어진_칸은_덩이로_잰다():
    """생명과학 p10 정답 칸 — 줄 하나씩 재면 `정답` 이 머리말 `정답과 해설` 에 걸려 칸이 끊겼다."""
    doc = fitz.open()
    pg = doc.new_page(width=500, height=1000)
    pg.insert_text((50, 100), "정답\n1. 가설\n2. 대조\n3. 인산", fontname="korea", fontsize=9)
    kept = [{"content": "정답과 해설 5쪽"}, {"content": "가설을 세우고 대조 실험을 한다."}]
    losses, _ = L.extraction_losses(kept, pg, None)
    assert [L._plain(x["text"]) for x in losses] == ["정답1가설2대조3인산"]


def test_항목_안에서_빠진_줄만_적는다(tmp_path):
    """그림 제목은 경계에 들어갔고 그림 안 글만 빠졌다 — 들어간 줄까지 손실로 적으면 채점기가 오인한다."""
    doc, pg = _page()
    title = "그림 1 우리 동네 소식 카드 뉴스"
    pg.insert_text((50, 580), title, fontname="korea", fontsize=9)
    losses, _ = L.extraction_losses([{"content": KEPT}, {"content": title}], pg, _raw(tmp_path, ITEMS))
    fig = [x for x in losses if x.get("reason") == "figure_text"]
    assert len(fig) == 1 and "카드 뉴스 속" in fig[0]["text"] and "우리 동네" not in fig[0]["text"]


def test_짧은_조각은_적지_않는다(tmp_path):
    doc, pg = _page()
    items = [{"type": "text", "text": "①", "bbox": [1, 1, 2, 2]}]
    losses, _ = L.extraction_losses([{"content": t} for t in (KEPT, DROP, UNSEEN, CARD)],
                                    pg, _raw(tmp_path, items))
    assert losses == []


def test_채점기는_locate_로_갈래를_읽는다(tmp_path):
    doc, pg = _page()
    els = [{"content": KEPT}, {"content": "이미지 캡셔닝 대기"}]
    losses, checks = L.extraction_losses(els, pg, _raw(tmp_path, ITEMS))
    bnd = {"meta": {"loss_checks": checks}, "elements": els, "extraction_losses": losses}
    assert L.locate(bnd, KEPT) == "kept"
    assert L.locate(bnd, UNSEEN) == "unseen"
    assert L.locate(bnd, DROP) == "dropped" and L.locate(bnd, CARD) == "dropped"
    assert L.locate(bnd, "【점역자주】그림: 지도에 표시된 두 지역의 위치") is None   # gold 만의 것
    assert L.locate({"elements": els}, UNSEEN) is None                              # 옛 경계 파일


def test_builder_가_추출_표지를_경계로_싣는다(tmp_path, monkeypatch):
    """종전에는 builder 가 flags 를 새로 만들어 추출기 표지(MINERU_*·TEXTLAYER_*)가 버려졌다."""
    monkeypatch.chdir(tmp_path)
    el = {"element_id": "e1", "type": "text", "bbox": [1, 1, 500, 50], "bbox_px": [1, 1, 2, 2],
          "content": "* 표의 수치는 추정치이다.", "flags": ["MINERU_TABLE_FOOTNOTE"]}
    res = rb.build([el], "job-flags", 1, "OCR")
    assert res["elements"][0]["flags"] == ["MINERU_TABLE_FOOTNOTE"]


def test_줄을_이어도_출처_표지가_남는다():
    class _Page:
        rect = fitz.Rect(0, 0, 1000, 1000)

        def get_textbox(self, rect):   # noqa: ARG002 - 레이어 없음
            return ""

    a = {"id": "a", "order": 1, "type": "text", "heading_level": 0, "flags": ["MINERU_FOOTER"],
         "content": "첫째, 후각은 대뇌의 감각 피질과 직접 연결되어 있습니", "bbox": [196, 100, 832, 111]}
    b = {"id": "b", "order": 2, "type": "text", "heading_level": 0, "flags": ["MINERU_TABLE_FOOTNOTE"],
         "content": "다. 시각, 청각 등의 다른 감각의 경우 정보가 들어오면", "bbox": [196, 115, 832, 126]}
    out = join_wrapped_lines([a, b], _Page(), bbox_space="norm1000", image_width=0, image_height=0)
    assert len(out) == 1 and out[0]["flags"] == ["MINERU_FOOTER", "MINERU_TABLE_FOOTNOTE"]


def test_추출_표지는_검토_플래그로_새지_않는다():
    """경계로 나가면 quality_checker 가 flags 를 읽는다 — 출처 표지가 R 플래그가 되면 소음이다."""
    from app.ai.quality.quality_checker import _FLAG_TO_REVIEW, _GENERIC_R_FLAG
    for flag in ("MINERU_FOOTER", "TEXTLAYER_TABLE_OUTSIDE", "MINERU_CODE_BODY", "MINERU_TABLE_FOOTNOTE"):
        assert flag not in _FLAG_TO_REVIEW and not _GENERIC_R_FLAG.match(flag)
        assert not flag.endswith("_FALLBACK")


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))


# ── 같은 틀 이웃 줄에 가린 손실(#1298) ──────────────────────────────────────────
OPT = ("가. 첫째 자료를 보니 모음으로 시작하는 어미 앞에서 바뀌었구나",
       "나. 둘째 자료를 보니 자음으로 시작하는 조사 앞에서 바뀌었구나",
       "다. 셋째 자료를 보니 모음으로 시작하는 조사 앞에서 바뀌었구나")


def _opt_page():
    doc = fitz.open()
    pg = doc.new_page(width=500, height=1000)
    for y, t in zip((100, 130, 160), OPT):
        pg.insert_text((20, y), t, fontname="korea", fontsize=9)
    return doc, pg


def test_같은_틀_이웃_줄에_가린_줄을_적는다(tmp_path):
    """선택지 '나'만 빠졌다. 쪽 전체 6-gram 대조로는 '가' · '다'에 덮여 '있음'이었다(2027 언매 p0096 선택지 ②)."""
    doc, pg = _opt_page()
    items = [{"type": "text", "text": t, "bbox": [30, y, 970, y + 20]} for y, t in ((85, OPT[0]), (145, OPT[2]))]
    losses, _ = L.extraction_losses([{"content": OPT[0]}, {"content": OPT[2]}], pg, _raw(tmp_path, items))
    sib = [x for x in losses if x.get("reason") == "sibling"]
    assert [(x["class"], " ".join(x["text"].split())) for x in sib] == [("unseen", OPT[1])]
    assert not [x for x in losses if x.get("reason") != "sibling"]          # 종전 대조로는 손실 없음


def test_MinerU_가_본_이웃_줄_손실은_dropped(tmp_path):
    doc, pg = _opt_page()
    items = [{"type": "text", "text": t, "bbox": [30, 85 + 30 * k, 970, 105 + 30 * k]} for k, t in enumerate(OPT)]
    losses, _ = L.extraction_losses([{"content": OPT[0]}, {"content": OPT[2]}], pg, _raw(tmp_path, items))
    assert [(x["class"], " ".join(x["text"].split())) for x in losses if x.get("reason") == "sibling"] == [("dropped", OPT[1])]


def test_다_있으면_이웃_줄_손실이_없다(tmp_path):
    doc, pg = _opt_page()
    losses, _ = L.extraction_losses([{"content": t} for t in OPT], pg, None)
    assert losses == []


def test_짧은_이름표_줄이_긴_문장_자리를_빼앗지_않는다():
    """짧은 줄('세포 하나의 유전 물질 양')이 긴 문장 속 같은 문구 자리를 먼저 차지해 그 문장(한 음절 오독이 있어 닮음 1 아래)을
    밀어내면 안 된다. 길이가 비슷한 줄끼리만 자리를 다툰다."""
    lines = [(None, "세포 하나의 유전 물질 양은"), (None, "감수 분열에서 세포 하나의 유전 물질 양은 절반이 되고 염색체 수도 같이 준다")]
    have, lost = L._sibling_match(lines, ["감수 분열에서 세포 하나의 유전 물질 양은 절반이 되고 염색채 수도 같이 준다"])
    assert lost == set() and have == {0, 1}
