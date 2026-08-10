"""ZERO 티어 어절 경계 복원(_line_text_with_word_gaps) — 공백 글리프 없는 PDF 대응.

라인 dict는 PyMuPDF rawdict 형식을 그대로 본떠 수동 구성(순환검증 금지).
실측 근거: 교과서 PDF 글자 간격 이중분포 — 어절 경계 ≈ +2.06pt, 글자 내 ≈ -1.18pt
(폰트 9.4pt, 사회문화 p035).
"""
from app.ai.preprocessor.pdf_analyzer import _line_text_with_word_gaps


def _line(chars: list[tuple[str, float, float]], size: float = 9.4) -> dict:
    """(글자, x0, x1) 목록 → rawdict line dict."""
    return {
        "spans": [{
            "size": size,
            "chars": [{"c": c, "bbox": (x0, 0.0, x1, 10.0)} for c, x0, x1 in chars],
        }],
    }


def _glued(words: list[str], *, intra=-1.18, boundary=2.06, width=9.4, size=9.4) -> dict:
    """어절들을 공백 글리프 없이 물리 간격만으로 이어붙인 라인 생성."""
    chars = []
    x = 0.0
    for wi, word in enumerate(words):
        if wi > 0:
            x += boundary
        for ci, ch in enumerate(word):
            if ci > 0:
                x += intra
            chars.append((ch, x, x + width))
            x = x + width
    return _line(chars, size=size)


class TestWordGapRestore:
    def test_glued_korean_splits_at_boundary(self):
        line = _glued(["다음은", "가정", "환경을", "위해"])
        assert _line_text_with_word_gaps(line) == "다음은 가정 환경을 위해"

    def test_real_space_glyph_preserved_no_double(self):
        # 실제 공백 글리프가 있는 자리는 그대로 (이중 삽입 금지)
        chars = [("안", 0, 9), ("녕", 8, 17), (" ", 17, 21), ("하", 21, 30),
                 ("세", 29, 38), ("요", 37, 46)]
        assert _line_text_with_word_gaps(_line(chars)) == "안녕 하세요"

    def test_uniform_tracking_not_split(self):
        # 자간이 고르게 넓은 제목(트래킹) — 기준 간격 자체가 커서 분리 안 됨
        line = _glued(["사회문화탐구"], intra=3.0)
        assert _line_text_with_word_gaps(line) == "사회문화탐구"

    def test_latin_not_split(self):
        # 한글 없는 쌍은 간격이 벌어져도 미분리 (URL 보호)
        chars = []
        x = 0.0
        for i, ch in enumerate("www.ebsi"):
            if i == 3:
                x += 4.0    # 큰 커닝이 있어도
            chars.append((ch, x, x + 5.0))
            x += 5.0 + 0.5
        assert " " not in _line_text_with_word_gaps(_line(chars))

    def test_few_samples_kept_as_is(self):
        # 간격 표본 부족(짧은 줄) → 판단 보류
        line = _glued(["가나", "다"])
        assert _line_text_with_word_gaps(line) == "가나다"

    def test_number_after_hangul_splits(self):
        # 한글-숫자 경계도 어절 간격이면 분리 ("…방법" ↔ "35")
        line = _glued(["수집", "방법은", "35쪽"])
        assert _line_text_with_word_gaps(line) == "수집 방법은 35쪽"

    def test_empty_line(self):
        assert _line_text_with_word_gaps({"spans": []}) == ""


# ── 줄 단위 블록 → 문단 (QA S2·S5, 2026-08-07) ──────────────────────────────
from app.ai.preprocessor.pdf_analyzer import (          # noqa: E402
    _join_words, _merge_paragraph_blocks, _NO_SPACE_AFTER, _NO_SPACE_BEFORE,
)


def _blk(text, x0, y0, x1, y1):
    return {"content": text, "bbox": [float(x0), float(y0), float(x1), float(y1)]}


class TestParagraphMerge:
    """PyMuPDF가 한 줄을 한 블록으로 내놓는 PDF에서 문단을 되살린다.

    실측 job_260807103532: 한 쪽 43~46요소가 전부 한 줄이었다.
    """

    def test_단_끝까지_찬_줄은_이어진다(self):
        bs = [_blk("이날이야말로 동소문 안에서", 113, 345, 1105, 364),
              _blk("인력거꾼 노릇을 하는", 113, 375, 1105, 394)]
        out = _merge_paragraph_blocks(bs)
        assert len(out) == 1
        assert out[0]["bbox"] == [113.0, 345.0, 1105.0, 394.0]

    def test_짧게_끝난_줄에서_문단이_끊긴다(self):
        # 앞 줄이 단 오른쪽까지 안 가면 문단 끝이다.
        bs = [_blk("태워다 주기로 되었다.", 113, 435, 642, 454),
              _blk("첫 번에 삼십 전, 둘째", 113, 465, 1105, 484)]
        assert len(_merge_paragraph_blocks(bs)) == 2

    def test_들여쓰기로_시작하면_새_문단(self):
        bs = [_blk("앞 문단의 마지막 줄이다", 113, 345, 1105, 364),
              _blk("새 문단 첫 줄", 133, 375, 1105, 394)]
        assert len(_merge_paragraph_blocks(bs)) == 2

    def test_멀리_떨어진_줄은_안_이어진다(self):
        bs = [_blk("윗단 마지막", 113, 100, 1105, 119),
              _blk("한참 아래", 113, 900, 1105, 919)]
        assert len(_merge_paragraph_blocks(bs)) == 2


class TestJoinWords:
    """줄 끝 어절 + 줄 첫 어절을 붙일지 띄울지 — 형태소 분석으로 가른다.

    상위 모델이 문맥으로 매긴 18쌍에서 부호 규칙은 9/18, 형태소는 18/18이었다.
    """

    def test_어절_가운데가_잘리면_붙인다(self):
        assert _join_words("찰깍하고 손바닥에 떨어질 제 거의 눈", "물을 흘릴 만큼") == ""

    def test_어절_경계면_띄운다(self):
        assert _join_words("행여나 손님이 있을까", "하고 정류장에서") == " "

    def test_여는_괄호_앞은_띄운다(self):
        assert _join_words("좋은 날이었다. 문 안에", "(거기도 문밖은") == " "

    def test_숫자_뒤는_띄운다(self):
        assert _join_words("본문 13", "쪽 참고") == " "


class TestQuoteSpacing:
    """여는 따옴표 뒤·닫는 따옴표 앞에 공백을 넣지 않는다 (QA S5).

    실측: QA 11곳 중 5곳이 `‘ 이 민족 ’`처럼 안쪽에 공백이 끼어 나왔다.
    따옴표 글리프는 글자 폭보다 자리가 넓어 간격 임계를 늘 넘는다.
    """

    def test_여는_부호_목록(self):
        for ch in "‘“([{〈《「『【":
            assert ch in _NO_SPACE_AFTER

    def test_닫는_부호_목록(self):
        for ch in "’”)]}〉》」』】":
            assert ch in _NO_SPACE_BEFORE


class TestClosingMarkJoin:
    """닫는 부호로 끝난 줄 뒤의 조사는 붙여 잇는다 (2026-08-08).

    종전에는 `_join_sep`가 닫는 부호 뒤에 무조건 공백을 넣어
    `「곤여만국전도」 를`·`예(禮) 를`가 나갔다(val-2027 200쪽 19건 실측).
    이 자리도 한글끼리와 똑같이 형태소로 가른다 — 실측 10/10.
    """

    def test_조사는_붙인다(self):
        for a, b in (("「곤여만국전도」", "를"), ("예(禮)", "를"),
                     ("조약(1860)", "이"), ("한커우(우한)", "에서"),
                     ("화이부동(和而不同)", "의"), ("길’", "을")):
            assert _join_words(a, b) == "", f"{a}+{b}"

    def test_새_어절은_띄운다(self):
        for a, b in (("(가)", "국가가"), ("(대)", "동맹을")):
            assert _join_words(a, b) == " ", f"{a}+{b}"

    def test_태그로_끝난_줄은_손대지_않는다(self):
        # `모든<!/드러냄>` + `<!드러냄>사람이` — 뒤가 한글이 아니라 종전대로 공백
        assert _join_words("모든<!/드러냄>", "<!드러냄>사람이") == " "
