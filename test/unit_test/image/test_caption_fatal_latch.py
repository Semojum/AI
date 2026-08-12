"""캡셔닝 설정성 오류는 **실행 단위로** 잠근다 (2026-08-12).

전 job 실측: 시각요소 11,483개 중 6,892개(60.0%)가 CAPTION_FAILED인데 job별로는
실패율 100%가 152개 · 0%가 215개로 갈렸다. 그림이 아니라 API 접근 문제라는 뜻이다.

★ 기본 백엔드는 **anthropic**(claude-sonnet-5)이지 GPT-4o가 아니다. 키가 없으면
  클라이언트 생성자는 통과하고 첫 호출에서 `TypeError: Could not resolve
  authentication method…`가 난다 — 이름만 보면 코드 버그와 구분이 안 되므로
  메시지로 가른다. 이 테스트가 그 판별을 못박는다.
"""
from __future__ import annotations

import pytest

from app.ai.builder import result_builder as rb


@pytest.fixture(autouse=True)
def _reset():
    rb.reset_caption_fatal()
    yield
    rb.reset_caption_fatal()


class TestIsFatal:
    def test_키없음_TypeError는_설정오류다(self) -> None:
        exc = TypeError("Could not resolve authentication method. Expected one of "
                        "api_key, auth_token, or credentials to be set.")
        assert rb._is_fatal(exc)

    def test_그냥_TypeError는_코드버그다(self) -> None:
        """인증과 무관한 TypeError까지 잠그면 진짜 버그를 캡셔닝 장애로 오진한다."""
        assert not rb._is_fatal(TypeError("unsupported operand type(s) for +: 'int' and 'str'"))

    @pytest.mark.parametrize("name", [
        "AnthropicError", "OpenAIError", "AuthenticationError",
        "PermissionDeniedError", "NotFoundError",
    ])
    def test_인증_권한_예외는_설정오류다(self, name: str) -> None:
        assert rb._is_fatal(type(name, (Exception,), {})("boom"))

    @pytest.mark.parametrize("name", ["RateLimitError", "APITimeoutError", "APIConnectionError"])
    def test_일시장애는_잠그지_않는다(self, name: str) -> None:
        """쿼터·타임아웃은 다시 하면 될 수 있다 — 잠그면 멀쩡한 실행을 죽인다."""
        assert not rb._is_fatal(type(name, (Exception,), {})("boom"))


class TestLatch:
    def test_한_번_잠기면_API를_다시_안_부른다(self, monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
        img = tmp_path / "a.jpg"
        img.write_bytes(b"x")
        calls = {"n": 0}

        def _boom(_path):
            calls["n"] += 1
            raise TypeError("Could not resolve authentication method. Expected one of api_key…")

        monkeypatch.setattr(rb, "classify_with_confidence", _boom)
        el = {"image_path": str(img), "type": "image", "element_id": "e1"}

        assert rb._do_caption(el)[2] is False
        assert calls["n"] == 1, "설정성 오류인데 재시도했다"
        assert rb.caption_fatal_reason(), "래치가 안 걸렸다"

        # 다음 요소는 API를 아예 안 부른다 — 200요소 페이지에서 같은 실패를 200번 반복하던 자리
        assert rb._do_caption(dict(el, element_id="e2"))[2] is False
        assert calls["n"] == 1, "잠긴 뒤에도 API를 불렀다"

    def test_사유가_플래그로_나간다(self, monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
        """사후에 '왜 실패했나'를 알 수 있어야 한다 — 로그는 파일로 안 남는다."""
        img = tmp_path / "a.jpg"
        img.write_bytes(b"x")
        monkeypatch.setattr(rb, "classify_with_confidence",
                            lambda _p: (_ for _ in ()).throw(
                                type("AuthenticationError", (Exception,), {})("401")))
        rb._do_caption({"image_path": str(img), "type": "image", "element_id": "e1"})
        assert rb.caption_fatal_reason().startswith("AuthenticationError")


def test_백엔드_상태에_키값은_안_실린다() -> None:
    """진단용이라 유무만 본다 — 값이 로그·보고서로 새면 안 된다."""
    from app.ai.captioning.captioner import backend_status

    st = backend_status()
    assert set(st) == {"backend", "model", "key_env", "key_present"}
    assert isinstance(st["key_present"], bool)
    assert st["backend"] in ("anthropic", "openai") or st["backend"]
