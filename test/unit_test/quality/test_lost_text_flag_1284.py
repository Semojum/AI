"""#1284 MinerU 가 버린 본문 글을 그 자리 요소에 R1 로 알린다.

원본 글자층에는 있는데 묵자에 없는 글은 경계 `extraction_losses`(unseen)에 적히지만 채점기만 읽었다. 화면에는 번호(①)만
남아 점역사가 빠진 줄을 알 길이 없었다(2027 화작 p0165 선택지 ①~⑤). 손실 목록에는 대조 잡음이 많아(수식 쪽 등) 거른 것만 띄운다.
"""
from uuid import uuid4

from app.ai.quality.quality_checker import QualityChecker, lost_text_hosts
from app.schemas.content import LLMOutput
from app.schemas.layout import BBoxItem, LayoutResult

_CHOICES = "① 바다와 같이 넓고 깊은 문화 예술의 보고\n② 문화 예술의 고장에서 창의의 물결을 느껴 봐요!"
_LABELS = "남극 대륙 연구 기지\n북극 해빙 면적"      # 지도 이름표 꼴 — 한글 10자 이상이지만 줄이 다 짧다


def _loss(text=_CHOICES, region="text", bbox=(100, 200, 600, 260)):
    return {"class": "unseen", "source": "textlayer", "region": region, "text": text, "bbox": list(bbox)}


def _el(eid, content, bbox=(100, 200, 600, 225)):
    return {"id": eid, "type": "text", "bbox": list(bbox), "content": content}


def test_번호만_남은_요소에_빠진_글을_단다():
    els = [_el("a", "<!2칸>①"), _el("b", "<!2칸>②", (100, 230, 600, 255)), _el("c", "다른 문항", (100, 700, 600, 720))]
    got = lost_text_hosts([_loss()], els, math_page=False)
    assert set(got) == {"a", "b"} and got["a"] == [_CHOICES]


def test_대조_잡음은_거른다():
    els = [_el("a", "<!2칸>①")]
    assert lost_text_hosts([_loss()], els, math_page=True) == {}                       # 수식 쪽
    assert lost_text_hosts([_loss(text=_LABELS, region=None)], els, math_page=False) == {}   # 항목 없는 자리의 짧은 줄(그림 이름표 · 쪽 장식)
    assert lost_text_hosts([_loss(region="footer")], els, math_page=False) == {}        # 글 자리도 None 도 아닌 곳
    assert lost_text_hosts([_loss(text="① 하늘 ② 논밭")], els, math_page=False) == {}    # 한글 10자 미만
    assert lost_text_hosts([_loss(bbox=(700, 900, 800, 950))], els, math_page=False) == {}   # 걸친 요소 없음
    dropped = {**_loss(), "class": "dropped"}
    assert lost_text_hosts([dropped], els, math_page=False) == {}                       # MinerU 는 본 글(채점기 몫)


def test_자리_없는_손실도_긴_줄이면_단다():
    """#1294 MinerU 가 자리조차 안 잡은 줄(region None)도 빠진 본문이면 띄운다(2027 언매 p0036 '님금하 아쇼셔(임금이시여, 아소서.)')."""
    els = [_el("a", "(,)"), _el("b", "2) 의문문", (100, 230, 600, 255))]
    got = lost_text_hosts([_loss(region=None)], els, math_page=False)
    assert set(got) == {"a", "b"} and got["a"] == [_CHOICES]


def test_자리_없는_손실은_글_자리_손실_뒤에_붙는다():
    """R1 문구는 첫 손실 글이다. 그 요소 몫인 글 자리 손실이 문구로 남아야 한다(#1294)."""
    els = [_el("a", "<!상자>① 바다")]
    own = _loss(text="사료 상자에서 빠진 문장 하나가 여기 있다", region="text")
    got = lost_text_hosts([_loss(region=None), own], els, math_page=False)
    assert got["a"] == [own["text"], _CHOICES]


def test_띄어쓰기만_다른_자리는_빠진_것이_아니다():
    """한글 토막 절반 이상이 걸친 요소 글에 있으면 대조가 빗나간 것이다. 한 음절 낱말(갑 · 병)도 센다."""
    text = "① 갑, 병\n② 갑, 정\n③ 을, 정\n④ 갑, 을, 병\n⑤ 을, 병, 정"
    els = [_el("a", "① 갑, 병"), _el("b", "② 갑, 정", (100, 230, 600, 255))]
    assert lost_text_hosts([_loss(text=text)], els, math_page=False) == {}
    els = [_el("a", "①바다와같이넓고깊은문화예술의보고"), _el("b", "②문화예술의고장에서창의의물결을느껴봐요!", (100, 230, 600, 255))]
    assert lost_text_hosts([_loss()], els, math_page=False) == {}


def _check(lost, ids):
    items = [BBoxItem(element_id=i, type="text", bbox=(0, 0, 10, 10), reading_order=k + 1) for k, i in enumerate(ids)]
    outs = [LLMOutput(element_id=i, corrected_text="①", render_mode="text_only", routing_tier="ZERO", processing_time_ms=0)
            for i in ids]
    return QualityChecker().check("p_001", layout_result=LayoutResult(page_id="p_001", elements=items),
                                  llm_outputs=outs, lost_text=lost)


def test_요소에_R1_을_달고_쪽은_검토_필요다():
    a, b = uuid4(), uuid4()
    report = _check({str(a): [_CHOICES]}, [a, b])
    flags = [f for f in report.review_flags if f.type == "R1"]
    assert [f.element_id for f in flags] == [str(a)]
    assert flags[0].message == "원본에 있는 글이 추출에서 빠짐: ① 바다와 같이 넓고 깊은 문화 예술의 보고 ② 문화…"
    assert report.status == "NEEDS_REVIEW"
    assert _check({}, [a, b]).status == "COMPLETED"


def test_이_쪽에_없는_요소에는_달지_않는다():
    a = uuid4()
    report = _check({str(uuid4()): [_CHOICES]}, [a])
    assert not [f for f in report.review_flags if f.type == "R1"]
