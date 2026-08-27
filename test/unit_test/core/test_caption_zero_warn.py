"""시각자료 설명 0건 알림은 **설정이 어긋난 자리에서만** ERROR 다 (2026-08-27).

성공 0건이라고 다 사고는 아니다. 가드3(글자를 그림으로 잡은 것)·DISABLE_LLM_FALLBACK 은
의도된 생략이라 ERROR 로 올리면 정상 실행이 빨간 줄로 덮인다(실측: dev-2027 첫 쪽부터 났다).
키가 없거나 캡셔너가 잠긴 경우만 ERROR.
"""
import logging

import pytest

from app.ai.builder import result_builder as rb


@pytest.fixture(autouse=True)
def _reset():
    rb._caption_fatal = None
    rb._backend_logged = True          # 기동 1회 로그는 이 테스트 대상이 아니다
    yield
    rb._caption_fatal = None


def _one_visual():
    return [{"type": "image", "element_id": "e1", "bbox": [0, 0, 10, 10],
             "content": "", "image_path": None}]


def _no_caption(monkeypatch):
    """캡셔닝이 아무것도 못 냈다(성공 0건) — 이유는 바깥에서 정한다."""
    monkeypatch.setattr(rb, "_do_caption_logged",
                        lambda el, ctx="": ("", el["type"], False, None))


def test_키가_있고_잠기지_않았으면_INFO(monkeypatch, caplog):
    _no_caption(monkeypatch)
    monkeypatch.setattr(rb, "backend_status",
                        lambda: {"backend": "anthropic", "model": "m",
                                 "key_env": "ANTHROPIC_API_KEY", "key_present": True})
    with caplog.at_level(logging.INFO):
        rb._caption_all(_one_visual())
    assert not [r for r in caplog.records if r.levelno >= logging.ERROR]
    assert any("하나도 설명되지 않았다" in r.getMessage() for r in caplog.records)


def test_키가_없으면_ERROR(monkeypatch, caplog):
    _no_caption(monkeypatch)
    monkeypatch.setattr(rb, "backend_status",
                        lambda: {"backend": "anthropic", "model": "m",
                                 "key_env": "ANTHROPIC_API_KEY", "key_present": False})
    with caplog.at_level(logging.INFO):
        rb._caption_all(_one_visual())
    assert [r for r in caplog.records if r.levelno >= logging.ERROR]


def test_캡셔너가_잠겼으면_ERROR(monkeypatch, caplog):
    _no_caption(monkeypatch)
    monkeypatch.setattr(rb, "_caption_fatal", "AuthenticationError: 401")
    monkeypatch.setattr(rb, "backend_status",
                        lambda: {"backend": "anthropic", "model": "m",
                                 "key_env": "ANTHROPIC_API_KEY", "key_present": True})
    with caplog.at_level(logging.INFO):
        rb._caption_all(_one_visual())
    errs = [r for r in caplog.records if r.levelno >= logging.ERROR]
    assert errs and "잠김" in errs[0].getMessage()
