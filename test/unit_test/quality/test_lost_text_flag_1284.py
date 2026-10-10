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


def test_이웃_줄에_가린_손실은_한글_토막_거르기를_건너뛴다():
    """#1298 같은 틀 이웃 줄 글이 그 자리 요소에 있어 '한글 토막 절반' 거르기에 늘 걸린다. MinerU 가 본 줄(dropped)이어도 띄운다."""
    opt = "② 둘째 자료를 보니 자음으로 시작하는 조사 앞에서 바뀌었구나"
    host = _el("a", "① 첫째 자료를 보니 모음으로 시작하는 어미 앞에서 바뀌었구나\n③ 셋째 자료를 보니 모음으로 시작하는 조사 앞에서 바뀌었구나")
    sib = {**_loss(text=opt), "class": "dropped", "reason": "sibling"}
    assert lost_text_hosts([sib], [host], math_page=False) == {"a": [opt]}
    assert lost_text_hosts([{**sib, "reason": "not_carried"}], [host], math_page=False) == {}     # 그 밖 dropped 는 종전대로
    assert lost_text_hosts([{**sib, "class": "unseen", "reason": None}], [host], math_page=False) == {}   # 종전 거르기


# ── 걸친 요소가 없는 손실(#1300) ────────────────────────────────────────────────
_LINE = "진행자: 선수께서 지난 올림픽에서 접전 끝에 금메달을 따는 모습으로 큰 감동을 주셨는데"


def test_걸친_요소가_없으면_같은_단의_가장_가까운_요소에_위_아래를_적어_단다():
    """2027 언매 p0202 '진행자: …' 줄은 MinerU 가 자리조차 안 잡아 R1 을 달 곳이 없었다."""
    lost = _loss(text=_LINE, region=None, bbox=(100, 200, 600, 215))
    els = [_el("far", "다른 문항", (100, 500, 600, 520)), _el("next", "데 이렇게 뵙게 되어 반갑습니다.", (100, 220, 600, 240))]
    assert lost_text_hosts([lost], els, math_page=False) == {"next": [f"(이 요소 위) {_LINE}"]}
    els = [_el("prev", "사회자 소개 문단", (100, 150, 600, 195))]
    assert lost_text_hosts([lost], els, math_page=False) == {"prev": [f"(이 요소 아래) {_LINE}"]}


def test_간격이_같으면_경계_순서가_앞선_요소에_단다():
    lost = _loss(text=_LINE, region=None, bbox=(100, 200, 600, 215))
    below, above = _el("below", "아래 줄", (100, 220, 600, 240)), _el("above", "위 줄", (100, 175, 600, 195))
    assert set(lost_text_hosts([lost], [below, above], math_page=False)) == {"below"}
    assert set(lost_text_hosts([lost], [above, below], math_page=False)) == {"above"}


def test_다른_단이거나_멀면_달지_않는다():
    lost = _loss(text=_LINE, region=None, bbox=(100, 200, 450, 215))
    assert lost_text_hosts([lost], [_el("col2", "오른쪽 단", (520, 220, 900, 240))], math_page=False) == {}
    assert lost_text_hosts([lost], [_el("far", "먼 요소", (100, 300, 450, 320))], math_page=False) == {}   # 간격 85


def test_가까운_요소에_단_문구에_위_아래가_보인다():
    a = uuid4()
    msg = [f for f in _check({str(a): [f"(이 요소 위) {_LINE}"]}, [a]).review_flags if f.type == "R1"][0].message
    assert msg.startswith("원본에 있는 글이 추출에서 빠짐: (이 요소 위) 진행자:")


def test_가까운_요소에는_한글_토막_거르기를_걸지_않는다():
    """가까운 요소는 그 글의 자리가 아니다. 이웃 줄의 흔한 토막에 걸려 놓치던 꼴(2027 생명과학 p0103 '(나) …')."""
    line = "(나) (가)에 ⓑ를 첨가하고 슬라이드를 세척한다."
    lost = _loss(text=line, region=None, bbox=(100, 200, 600, 215))
    near = _el("next", "(다) 형광 현미경으로 슬라이드를 관찰한 결과, (가)에 ⓒ를 첨가한 A 가 빛났다.", (100, 216, 600, 240))
    assert lost_text_hosts([lost], [near], math_page=False) == {"next": [f"(이 요소 위) {line}"]}


# ── #1303 원본 글자층으로 되살린 손실: R1 을 지우지 않고 문구만 바꾼다 ─────────────────────

def _check_restored(lost, restored, ids):
    items = [BBoxItem(element_id=i, type="text", bbox=(0, 0, 10, 10), reading_order=k + 1) for k, i in enumerate(ids)]
    outs = [LLMOutput(element_id=i, corrected_text="①", render_mode="text_only", routing_tier="ZERO", processing_time_ms=0)
            for i in ids]
    return QualityChecker().check("p_001", layout_result=LayoutResult(page_id="p_001", elements=items),
                                  llm_outputs=outs, lost_text=lost, lost_restored=restored)


def test_되살린_손실은_R1_문구가_되살림이고_넣은_글을_보인다():
    a = uuid4()
    report = _check_restored({str(a): [_CHOICES]}, {_CHOICES: ("① 바다와 같이 넓고 깊은 ○○ 문화 예술의 보고", 0)}, [a])
    flags = [f for f in report.review_flags if f.type == "R1"]
    assert [f.message for f in flags] == ["추출에서 빠진 글을 원본 글자층으로 되살림: ① 바다와 같이 넓고 깊은 ○○ 문화 예술의 보고"]
    assert report.status == "NEEDS_REVIEW"


def test_못_읽은_글자가_남으면_그_수를_적는다():
    a = uuid4()
    flags = [f for f in _check_restored({str(a): [_CHOICES]}, {_CHOICES: ("① 바다", 2)}, [a]).review_flags if f.type == "R1"]
    assert flags[0].message == "추출에서 빠진 글을 원본 글자층으로 되살림, 못 읽은 글자 2자: ① 바다"


def test_한_요소에_못_넣은_손실이_있으면_종전_문구다():
    a = uuid4()
    other = "③ 다양한 영감을 느낄 수 있는 지역 문화 예술 여행"
    flags = [f for f in _check_restored({str(a): [_CHOICES, other]}, {_CHOICES: ("① 바다", 0)}, [a]).review_flags if f.type == "R1"]
    assert flags[0].message == "원본에 있는 글이 추출에서 빠짐: ③ 다양한 영감을 느낄 수 있는 지역 문화 예술 여행"
