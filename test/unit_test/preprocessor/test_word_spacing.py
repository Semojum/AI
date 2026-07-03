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
