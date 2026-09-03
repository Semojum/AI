"""소괄호 줄 넘김 역맵 회귀 가드 (2026-09-04, PR ④).

★ 파일 이름을 `test_lone_punct_and_log.py` 와 나눠 둔다 — 그 이름은 PR #472 가 쓰고 있어
  같은 이름이면 머지 충돌이 난다.
"""
# ── 소괄호 줄 넘김 (2026-09-04) ──────────────────────────────────────────────
# 여는 ⠦⠄ 의 첫 셀 ⠦ 는 **받침 ㅌ**(제3항)과 겹친다. 줄 단위로만 짝을 찾으면
# 닫는 ⠠⠴ 가 다음 줄일 때 괄호를 못 만들고 받침으로 붙는다 — `개최(1919. 1.)` → `개쵵'…`.
# gold 18,892쪽 실측: 여는 쪽이 남는 줄 13,459 · 닫는 표까지 **1줄 뒤 80.2% · 2줄 뒤 12.5%**.
class TestParenLineWrap:
    def test_줄을_넘는_괄호가_괄호로_읽힌다(self):
        from app.utils.braille_back import decode
        # `(가)` 를 줄 사이에 걸쳐 둔다 — 여는 표 뒤에 개행이 온다
        got = decode("⠈⠔⠦⠄⠫\n⠠⠴")
        assert "(" in got and ")" in got, got
        assert "ㅌ" not in got

    def test_한_줄_괄호는_그대로(self):
        from app.utils.braille_back import decode
        assert "(" in decode("⠦⠄⠫⠠⠴")

    def test_너무_먼_짝은_안_잡는다(self):
        """길이 상한 80셀 — 넓히면 오검출도 같이 넓어진다(원장 C-100)."""
        from app.utils.braille_back import decode
        far = "⠦⠄" + "⠫" * 100 + "⠠⠴"
        assert "﷒" not in decode(far)
