"""I886 — 수식 지면만 MinerU `effort=high` 로 보낸다(2026-09-29 대표 결재).

판정은 한컴 수식 폰트 가운데 기울인 변수체·분수/근호 구조체가 쪽 스팬의 20%를 넘는가다.
수식 폰트가 '있나' 로는 못 가른다 — 생물 지면도 단위 기호를 수식 폰트로 쓴다.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[3]))

from app.ai.parser import mineru_runner as M  # noqa: E402

INPUT = Path(__file__).parents[2] / "test_data" / "input"
MATH = INPUT / "input_수학2_page004.pdf"      # 스팬 135 중 구조체 59
BIO = INPUT / "input_생물_page043.pdf"        # 수식 폰트 스팬 19개 — 전부 바른체(단위 기호)


def test_수학_지면은_수식_지면이다():
    assert M._is_math_page(MATH, 0)


def test_수식_폰트가_있어도_생물_지면은_아니다():
    assert M._is_math_page(BIO, 0) is False


def test_못_여는_파일은_아니다(tmp_path):
    assert M._is_math_page(tmp_path / "없음.pdf", 0) is False


@pytest.fixture
def sent(monkeypatch):
    """`_run_mineru` 가 상주 서버로 보내는 effort 를 가로챈다."""
    got = []
    from app.ai.parser import mineru_service
    monkeypatch.setattr(mineru_service, "get_url", lambda: "http://mineru.test")
    monkeypatch.setattr(M, "_post_mineru_api",
                        lambda api, pdf, out, idx, backend, effort, timeout: got.append(effort))
    monkeypatch.delenv("MINERU_EFFORT", raising=False)
    monkeypatch.delenv("MINERU_BACKEND", raising=False)
    monkeypatch.delenv("MINERU_CLIENT", raising=False)
    return got


def test_수식_지면만_high(sent, tmp_path):
    M._run_mineru(MATH, tmp_path, 0)
    M._run_mineru(BIO, tmp_path, 0)
    assert sent == ["high", "medium"]


def test_effort_를_명시하면_전_쪽에_그_값(sent, tmp_path, monkeypatch):
    # 끄기 팔 = MINERU_EFFORT=medium — 종전 기본과 같아야 한다
    monkeypatch.setenv("MINERU_EFFORT", "medium")
    M._run_mineru(MATH, tmp_path, 0)
    assert sent == ["medium"]
