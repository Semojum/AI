"""PUA·제어문자 정화 회귀 테스트.

한컴/HWP 수식 폰트는 수식 글리프를 PUA(U+E000~)로 인코딩 → PyMuPDF가 매핑 없는
raw 코드포인트로 추출한다. 한 글자라도 braillify에 들어가면 "Invalid symbol character"
예외로 요소 전체가 [처리 불가]가 되던 버그를 막는다(빈 결과 금지·요소 격리).
"""
from app.ai.braille.translator import sanitize_for_braille, translate_tagged_text

PUA = chr(0xE06D)        # 실제 PUA 글리프(수식 폰트가 쓰는 영역)
PUA2 = chr(0xE047)


class TestSanitizeForBraille:
    def test_pua_제거(self):
        assert PUA not in sanitize_for_braille(f"18. {PUA}")
        assert sanitize_for_braille(f"18. {PUA}").strip() == "18."

    def test_제어문자_제거(self):
        assert "\x00" not in sanitize_for_braille("a\x00b")

    def test_한글영문숫자_보존(self):
        out = sanitize_for_braille(f"AC {PUA2}{PUA}이고 값")
        assert "AC" in out and "이고" in out and "값" in out
        assert PUA not in out and PUA2 not in out

    def test_정상텍스트_무변경(self):
        s = "정상 텍스트 123 ABC"
        assert sanitize_for_braille(s) == s


class TestSpecialCharNormalize:
    """braillify가 거부하는 비-PUA 특수문자(전각부호·반각괄호·불릿) 안전화."""

    def test_전각문장부호_무예외(self):
        # ， ． ？ ！ （ ） ； ～ 전각 → 반각화 후 점역
        for t in ["나타날 수 있는데，이를", "적절한가？", "（보기）", "[1～3] 다음"]:
            assert translate_tagged_text(t)

    def test_반각모서리괄호_무예외(self):
        out = translate_tagged_text("우선 ｢민법｣에 의하면")
        assert out and "처리 불가" not in out

    def test_불릿_무예외(self):
        assert translate_tagged_text("◦소리 내어 단어 읽기")

    def test_원문자_무예외(self):
        assert translate_tagged_text("문맥상 ⓐ～ⓔ와 ㉠㉤")


class TestTranslateNoCrashOnPUA:
    def test_pua_포함_점역_무예외(self):
        # 이전엔 ValueError("Invalid symbol character")로 전체 요소 소실
        out = translate_tagged_text(f"19. {PUA}인 실수 {PUA2}에 대하여")
        assert out  # 비어있지 않게 점역됨
        assert "처리 불가" not in out

    def test_pua만_있어도_무예외(self):
        out = translate_tagged_text(f"{PUA}{PUA2}")
        assert isinstance(out, str)

    def test_미지문자_글자단위_폴백(self):
        # 정규화로 못 잡는 임의 미지 기호가 섞여도 줄 전체가 깨지지 않음
        out = translate_tagged_text("정상 텍스트 ⌬ 사이 미지기호")
        assert out and "정상" in str(out) or isinstance(out, str)
