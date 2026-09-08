"""고급 점역 — **MinerU 가 기준**이고 LLM 은 글자만 고친다.

고급 점역의 몫은 MinerU 가 한자로 깨뜨리는 글자를 제대로 읽는 것이지 지면 구조를 다시
잡는 것이 아니다. 레이아웃·좌표·읽기순서·유형·캡션 연결은 MinerU 것을 그대로 쓴다 —
그래야 bbox 가 보통 경로와 똑같이 맞는다.

⚠ 종전에는 반대로 했다(LLM 목록 기준 + 좌표만 얹기). 그러면 LLM 이 쪼갠 단위와 MinerU
  레이아웃이 어긋나 FE 하이라이트가 글자와 안 맞았다.
"""
import pytest

from app.core.pipeline import _graft_text


def test_좌표와_유형은_MinerU_것이_남는다():
    # 실물 꼴 — MinerU 가 '또'를 한자 '且'로, '구'를 '求'로 깨뜨린다(p1#75 실측).
    mnr = [{"type": "text", "content": "且, E(X^2)=a+5에서 값을 求하면", "bbox": [10, 10, 200, 20],
            "id": "m1", "order": 0}]
    llm = [{"type": "title", "content": "또, E(X^2)=a+5에서 값을 구하면"}]
    assert _graft_text(mnr, llm) == 1
    assert mnr[0]["content"] == "또, E(X^2)=a+5에서 값을 구하면"   # 글자만 바뀐다
    assert mnr[0]["bbox"] == [10, 10, 200, 20]          # 좌표는 그대로
    assert mnr[0]["type"] == "text" and mnr[0]["id"] == "m1"


def test_그림_설명은_본문에_안_붙는다():
    """LLM 이 그림을 설명한 줄이 본문 요소를 덮으면 지면에 없던 말이 나간다(3쪽 실측)."""
    mnr = [{"type": "text", "content": "My Top Secret", "bbox": [0, 0, 9, 9]}]
    llm = [{"type": "image", "content": "그림: My Top Secret 코너의 인물 아이콘"}]
    assert _graft_text(mnr, llm) == 0
    assert mnr[0]["content"] == "My Top Secret"


def test_많이_깨진_요소도_길이가_같으면_붙는다():
    """내용 감소 관문은 **길이**로 잰다 — 닮은 정도로 재면 많이 깨진 요소가 걸린다."""
    mnr = [{"type": "text", "content": "가나다라마바사아자차카타파하", "bbox": [0, 0, 9, 9]}]
    llm = [{"type": "text", "content": "가나다라마바사아자차카타파하"}]
    assert _graft_text(mnr, llm) == 1


def test_짧은_짝으로_긴_본문을_덮지_않는다(monkeypatch):
    """개악의 첫째는 **본문 삭제**였다 — 열 줄짜리 단락이 첫 줄 하나로 줄었다.

    이제는 문턱과 무관하게 관문이 막는다. 갈아 끼운 글자가 원래 글자를 `_GRAFT_KEEP`
    만큼 덮지 못하면 손대지 않는다. 문턱을 0.45 로 내려도 마찬가지다.
    """
    def run():
        mnr = [{"type": "text", "content": "이 문단은 앞 문장이 있고 뒤에 긴 설명이 더 붙는다",
                "bbox": [0, 0, 9, 9]}]
        return _graft_text(mnr, [{"type": "text", "content": "이 문단은 앞 문장이 있고"}]), mnr

    hit, mnr = run()
    assert hit == 0 and mnr[0]["content"].endswith("더 붙는다"), mnr

    monkeypatch.setenv("GRAFT_SIM_MIN", "0.45")
    hit, mnr = run()
    assert hit == 0 and mnr[0]["content"].endswith("더 붙는다"), "문턱을 내려도 본문은 안 지운다"


def test_문턱_스위치는_살아_있다(monkeypatch):
    """되돌리는 길(`GRAFT_SIM_MIN`)이 실제로 먹는지 — 길이가 같고 덜 닮은 짝으로 본다."""
    def run():
        mnr = [{"type": "text", "content": "가나다라마바사아자차카타", "bbox": [0, 0, 9, 9]}]
        return _graft_text(mnr, [{"type": "text", "content": "가나다라마바사아영영영영"}]), mnr

    assert run()[0] == 0
    monkeypatch.setenv("GRAFT_SIM_MIN", "0.45")
    assert run()[0] == 1, "스위치를 내려도 안 붙으면 되돌리는 길이 없다"


def test_LaTeX_장황함이_짝을_가리지_않는다():
    """MinerU 는 같은 수식을 훨씬 장황한 LaTeX 로 뱉는다(5·6쪽이 이것 하나로 갈렸다)."""
    mnr = [{"type": "formula", "bbox": [0, 0, 9, 9],
            "content": r"\overline {{\mathrm{AH} _ {1}}} = \sqrt {1 7 - 1} = 4 \text {或}"}]
    llm = [{"type": "formula", "content": r"\overline{AH_1}=\sqrt{17-1}=4\text{야}"}]
    assert _graft_text(mnr, llm) == 1
    assert "或" not in mnr[0]["content"]


def test_뭉친_요소에_LLM_여럿을_이어_붙인다():
    """MinerU 가 지면 여러 줄을 한 요소로 뭉치면 LLM 요소 여럿이 그 하나에 걸린다.

    첫 줄만 갈아 끼우면 나머지가 사라진다 — 2쪽 (ii)·(iii) 단락이 그렇게 잘렸다.
    """
    mnr = [{"type": "text", "bbox": [0, 0, 9, 9],
            "content": "첫째 줄은 여기까지다 둘째 줄은 이렇게 이어진다 셋째 줄로 끝난다"}]
    llm = [{"type": "text", "content": "첫째 줄은 여기까지다"},
           {"type": "text", "content": "둘째 줄은 이렇게 이어진다"},
           {"type": "text", "content": "셋째 줄로 끝난다"}]
    assert _graft_text(mnr, llm) == 1
    for want in ("첫째 줄", "둘째 줄", "셋째 줄"):
        assert want in mnr[0]["content"], mnr[0]["content"]


def test_잘린_요소는_2패스에서_붙는다():
    """`실수 k의 최,` 처럼 뒤가 날아간 요소 — 앞머리가 같고 LLM 이 더 길면 받는다."""
    mnr = [{"type": "text", "content": "실수 k의 최, 이므로 그림과 같이", "bbox": [0, 0, 9, 9]}]
    llm = [{"type": "text", "content": "실수 k의 최댓값이 f'(√2)이므로 그림과 같이"}]
    assert _graft_text(mnr, llm) == 1
    assert "최댓값이" in mnr[0]["content"]


def test_이웃_글자를_머금으면_손대지_않는다():
    """제목 요소에 이웃의 `[정답률 88%]` 를 덧붙이면 같은 말이 두 번 나간다."""
    mnr = [{"type": "title", "content": "정답 ③ *이항정리-다항식", "bbox": [0, 0, 9, 9]},
           {"type": "text", "content": "[정답률 88%]", "bbox": [0, 20, 9, 29]}]
    llm = [{"type": "title", "content": "정답 ③ *이항정리-다항식 [정답률 88%]"}]
    assert _graft_text(mnr, llm) == 0
    assert mnr[0]["content"] == "정답 ③ *이항정리-다항식"


def test_MinerU_가_원래_두_벌_갖고_있으면_통과():
    """중복 관문은 **우리가 만든** 중복만 막는다 — 원래 있던 것까지 막으면 고칠 길이 없다."""
    mnr = [{"type": "text", "content": "같은 문장이 두 번 있다 같은 문장이 두 번 있다",
            "bbox": [0, 0, 9, 9]},
           {"type": "text", "content": "같은 문장이 두 번 있다", "bbox": [0, 20, 9, 29]}]
    llm = [{"type": "text", "content": "같은 문장이 두 번 있다 같은 문장이 두 번 있다"}]
    assert _graft_text(mnr, llm) == 1


def test_요소_개수는_MinerU_를_따른다():
    # LLM 이 둘로 쪼개도 MinerU 가 하나면 하나다 — 레이아웃이 흔들리면 안 된다.
    mnr = [{"type": "text", "content": "가나다라마바사", "bbox": [0, 0, 9, 9]}]
    llm = [{"type": "text", "content": "가나다라마바사"}, {"type": "text", "content": "딴 것"}]
    _graft_text(mnr, llm)
    assert len(mnr) == 1


def test_짝이_없으면_원래_글자를_지킨다():
    mnr = [{"type": "text", "content": "원래 글자다", "bbox": [0, 0, 9, 9]}]
    llm = [{"type": "text", "content": "전혀 다른 내용"}]
    assert _graft_text(mnr, llm) == 0
    assert mnr[0]["content"] == "원래 글자다"


def test_빈_LLM_글자로_덮지_않는다():
    mnr = [{"type": "text", "content": "지켜야 할 본문", "bbox": [0, 0, 9, 9]}]
    llm = [{"type": "text", "content": "   "}]
    _graft_text(mnr, llm)
    assert mnr[0]["content"] == "지켜야 할 본문"


def test_한_LLM_요소를_둘이_나눠_쓰지_않는다():
    mnr = [{"type": "text", "content": "같은 문장이다", "bbox": [0, 0, 9, 9]},
           {"type": "text", "content": "같은 문장이다", "bbox": [0, 20, 9, 29]}]
    llm = [{"type": "text", "content": "같은 문장이다"}]
    assert _graft_text(mnr, llm) == 1


# ── MinerU 가 통째로 빠뜨린 줄 회수(`_recover_missing`) ─────────────────────────
# 실측 근거: `temp/graft/누락회수_0909.md`. 요소가 아예 없으면 갈아 끼울 자리가 없어
# 짝짓기로는 못 고친다(눈으로 센 30건). 짝 못 찾은 LLM 줄만 보면 6쪽에 153건이 걸려
# 다섯 배가 헛것이라, **지면에서 요소가 안 덮은 잉크**를 같이 봐야 판정이 선다.

def _page(tmp_path, lines, cover):
    """줄 세 개짜리 가짜 지면. `cover` 에 든 줄만 MinerU bbox 가 덮는다."""
    cv2 = pytest.importorskip("cv2")
    np = pytest.importorskip("numpy")
    h, w = 1200, 900                      # 실제 쪽 렌더 크기 — 문턱이 지면 높이 비율이라 필요하다
    img = np.full((h, w, 3), 255, np.uint8)
    boxes = []
    for k in range(lines):
        y = 100 + k * 200
        cv2.putText(img, "ABCDEFGHIJKLMNO", (80, y + 40),
                    cv2.FONT_HERSHEY_SIMPLEX, 1.5, (0, 0, 0), 3)
        if k in cover:
            boxes.append([80, round(y / h * 1000), 800, round((y + 55) / h * 1000)])
    p = tmp_path / "page.png"
    cv2.imwrite(str(p), img)
    return str(p), boxes


def test_빈_구역에_짝_못_찾은_줄을_세운다(tmp_path):
    img, boxes = _page(tmp_path, 3, cover=[0, 2])       # 가운데 줄이 요소로 안 잡혔다
    mnr = [{"type": "text", "content": "첫째 줄입니다 여기는", "bbox": boxes[0]},
           {"type": "text", "content": "셋째 줄입니다 여기는", "bbox": boxes[1]}]
    llm = [{"type": "text", "content": "첫째 줄입니다 여기는"},
           {"type": "text", "content": "빠진 가운데 줄입니다"},
           {"type": "text", "content": "셋째 줄입니다 여기는"}]
    _graft_text(mnr, llm, img)
    assert [e["content"] for e in mnr] == [
        "첫째 줄입니다 여기는", "빠진 가운데 줄입니다", "셋째 줄입니다 여기는"]
    assert mnr[1]["flags"] == ["ADVANCED_RECOVERED"]
    assert mnr[1]["bbox"][1] > mnr[0]["bbox"][1]        # 실제 그 줄 자리를 잡았다
    assert [e["reading_order"] for e in mnr] == [0, 1, 2]


def test_지면에_잉크가_없으면_안_세운다(tmp_path):
    """짝만 못 찾았을 뿐 MinerU 가 다른 꼴로 갖고 있는 것 — 세우면 같은 말이 두 번 나간다."""
    img, boxes = _page(tmp_path, 2, cover=[0, 1])       # 지면이 요소로 다 덮였다
    mnr = [{"type": "text", "content": "첫째 줄입니다 여기는", "bbox": boxes[0]},
           {"type": "text", "content": "둘째 줄입니다 여기는", "bbox": boxes[1]}]
    llm = [{"type": "text", "content": "첫째 줄입니다 여기는"},
           {"type": "text", "content": "\\overline{AB} 같은 다른 꼴"},
           {"type": "text", "content": "둘째 줄입니다 여기는"}]
    _graft_text(mnr, llm, img)
    assert len(mnr) == 2


def test_지면_이미지가_없으면_회수를_안_한다(tmp_path):
    """평상 경로(`img_path=None`)는 종전 그대로 — 요소 수가 안 는다."""
    img, boxes = _page(tmp_path, 3, cover=[0, 2])
    mnr = [{"type": "text", "content": "첫째 줄입니다 여기는", "bbox": boxes[0]},
           {"type": "text", "content": "셋째 줄입니다 여기는", "bbox": boxes[1]}]
    llm = [{"type": "text", "content": "첫째 줄입니다 여기는"},
           {"type": "text", "content": "빠진 가운데 줄입니다"},
           {"type": "text", "content": "셋째 줄입니다 여기는"}]
    _graft_text(mnr, llm)
    assert len(mnr) == 2


def test_단을_넘은_자리에는_안_세운다(tmp_path):
    """앞뒤 요소가 단을 넘으면 둘을 감싼 사각이 지면 절반이라 **남의 구멍**이 걸린다.

    실측(p4)에서 꼬리말과 코너 제목이 왼쪽 단 본문 구멍으로 들어갔다. 구역은 앞뒤 요소
    **사이에 끼어** 있고 같은 단이어야 한다.
    """
    from app.core.pipeline import _gap_fits
    left_gap = [90, 500, 350, 512]
    assert _gap_fits(left_gap, [90, 480, 350, 495], [90, 520, 350, 535])   # 같은 단, 사이에 낌
    assert not _gap_fits(left_gap, [520, 20, 560, 40], [520, 50, 900, 70])  # 오른쪽 단
    assert not _gap_fits(left_gap, [90, 600, 350, 615], [90, 700, 350, 715])  # 앞 요소가 아래
