"""#1323 — 줄바꿈 자리 계산이 음절 자리마다 접두를 통째로 다시 점역해 줄 길이의 제곱으로 늘던 것을, 순한글 줄은
낱말 조각 앞부분만 점역하고 수식은 한 번만 바꾸게 했다. 끊을 자리는 종전 계산(접두 통째 재점역)과 같아야 한다."""
from app.ai.braille import translator as T

LINES = [
    "대한민국의 모든 국민은 법 앞에 평등하며, 누구든지 성별이나 종교 때문에 차별받지 아니한다.",
    "(정답 찾기) ④ 공자의 입장에서 볼 때 인(仁)은 사랑이다.",       # ④ 는 홀로 점역해도 뒤에 ⠀ 를 단다
    "New York 에서 1,000명이 모였다.",                          # 낱말을 넘는 로마자 구간
    "  들여 쓴 줄과  두 칸 빈칸",                                 # 줄 머리 빈칸 · 두 칸 빈칸
    "‘나’의 말과 <!드러냄>지도자<!/드러냄>의 역할",
    "넓이는 <!수식>x^2+1<!/수식> 이고 둘레는 <!수식>x^2+1<!/수식> 의 두 배이다.",   # 같은 수식 둘(기억)
]


def _slow(src, braille, monkeypatch):
    """종전 계산 — 조각 표도 수식 기억도 없이 접두를 통째로 다시 점역한다."""
    with monkeypatch.context() as m:
        m.setattr(T, "_segment_starts", lambda s, b: None)
        return T._break_offsets_in(src, braille)


def test_끊을_자리가_종전_계산과_같다(monkeypatch):
    for src in LINES:
        braille = T.translate_tagged_text(src)
        assert T._break_offsets(src, braille) == _slow(src, braille, monkeypatch), src
    # 두 길이 다 시험에 든다 — 조각으로 갈리는 줄과 안 갈리는 줄
    assert {T._segment_starts(s, T.translate_tagged_text(s)) is None for s in LINES} == {True, False}


def test_조각으로_갈리는_줄은_접두를_통째로_다시_점역하지_않는다(monkeypatch):
    src = " ".join(["대한민국의 모든 국민은 법 앞에 평등하며, 누구든지 성별이나 종교 때문에 차별받지 아니한다."] * 8)
    braille = T.translate_tagged_text(src)
    assert T._segment_starts(src, braille) is not None
    lens, real = [], T.translate_tagged_text
    monkeypatch.setattr(T, "translate_tagged_text", lambda x, *a, **k: lens.append(len(x)) or real(x, *a, **k))
    T._break_offsets(src, braille)
    assert max(lens) <= max(len(w) for w in src.split(" ")) + 1     # 낱말 + 뒤 빈칸보다 긴 입력이 없다


def test_수식은_줄_하나에_한_번만_바꾸고_기억은_밖으로_새지_않는다(monkeypatch):
    src = "넓이는 <!수식>x^2+1<!/수식> 이고 둘레는 <!수식>x^2+1<!/수식> 의 두 배이다."
    braille = T.translate_tagged_text(src)
    seen, real = [], T._convert_latex_raw
    monkeypatch.setattr(T, "_convert_latex_raw", lambda x: seen.append(x) or real(x))
    assert T._break_offsets(src, braille)
    assert seen and len(seen) == len(set(seen))                      # 같은 LaTeX 를 두 번 바꾸지 않는다(종전 38번)
    assert T._LATEX_MEMO.get() is None                               # 끊을 자리 계산 밖에서는 기억이 없다
