"""TranslateText RPC — 꼬리말 점역 단위 테스트.

이 RPC는 조판 가이드 §6에서 확정된 계약이다. 본문 점역과 **같은 rule-based 경로**를 타고
LLM·MinerU를 거치지 않는다. 여기서 지키는 것은 셋 —
① 지침 실물과 일치 ② 한글+숫자·로마자 혼합 정확도 ③ 오용(본문 통째로 보내기) 거절.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import grpc
import pytest

from app.ai.braille.translator import translate_plain
from app.core import grpc_server
from protos.generated import braille_service_pb2


# ── 점역 정확도 ───────────────────────────────────────────────────────────────

def test_지침_실물_꼬리말():
    """「점자 도서 제작 지침」[예 1-8]의 꼬리말 실물과 같아야 한다.

    실물 BRF-ASCII `es"oe1` = ⠑⠎⠐⠕⠑⠂. 우리 rule-based 경로가 이걸 그대로 낸다는 것이
    이 RPC의 가장 강한 검증이다(사람이 만든 점자책과 대조).
    """
    assert translate_plain("머리말") == "⠑⠎⠐⠕⠑⠂"


@pytest.mark.parametrize(
    "text, expect",
    [
        # 한글 + 숫자 — 수표(⠼)가 숫자 앞에 붙어야 한다
        ("수특 사회문화 2", "⠠⠍⠓⠪⠁⠀⠇⠚⠽⠑⠛⠚⠧⠀⠼⠃"),
        # 한글 + 로마 숫자 — 로마자표(⠴)로 열고 대문자 구절표(⠠⠠)를 쓴다
        ("생명과학 I", "⠠⠗⠶⠑⠻⠈⠧⠚⠁⠀⠴⠠⠊⠲"),
        # 숫자로 시작하는 번호 체계 제목
        ("1. 함수의 극한", "⠼⠁⠲⠀⠚⠢⠠⠍⠺⠀⠈⠪⠁⠚⠒"),
        # 순한글
        ("차례", "⠰⠣⠐⠌"),
    ],
)
def test_꼬리말_후보(text, expect):
    assert translate_plain(text) == expect


def test_빈_입력은_빈_점자():
    assert translate_plain("") == ""
    assert translate_plain("   ") == ""


def test_여러_줄은_보존한다():
    """꼬리말은 한 줄이 정상이지만, 호출자가 무엇을 보낼지는 우리가 정하지 않는다.
    조용히 버리지 않고 개행을 살린다."""
    assert translate_plain("차례\n머리말") == "⠰⠣⠐⠌\n⠑⠎⠐⠕⠑⠂"


def test_32칸_조판을_하지_않는다():
    """조판은 braille-assist page_row 몫이다 — 이 함수는 줄을 자르지 않는다."""
    got = translate_plain("가" * 40)
    assert "\n" not in got
    assert len(got) > 32


# ── RPC 계약 ─────────────────────────────────────────────────────────────────

def _ctx() -> MagicMock:
    ctx = MagicMock()
    ctx.peer.return_value = "ipv4:127.0.0.1:0"
    ctx.abort = AsyncMock(side_effect=grpc.RpcError())
    return ctx


def _call(text: str):
    servicer = grpc_server.BrailleServiceServicer()
    req = braille_service_pb2.TranslateTextRequest(text=text)
    ctx = _ctx()
    return asyncio.run(servicer.TranslateText(req, ctx)), ctx


def test_rpc_정상():
    reply, _ = _call("머리말")
    assert reply.braille == "⠑⠎⠐⠕⠑⠂"


def test_rpc_빈_입력():
    reply, ctx = _call("")
    assert reply.braille == ""
    ctx.abort.assert_not_called()


def test_rpc_본문을_보내면_거절한다():
    """오용 방지. 조용히 자르면 BE가 잘린 줄 모르므로 INVALID_ARGUMENT로 거절한다."""
    with pytest.raises(grpc.RpcError):
        _call("가" * (grpc_server._TRANSLATE_TEXT_MAX + 1))


def test_rpc_배압에_들어가지_않는다():
    """GPU를 안 쓰는 즉시 호출이라 페이지 동시 상한에 태우지 않는다.
    상한을 꽉 채운 상태에서도 응답해야 한다."""
    grpc_server._in_flight = grpc_server.config.max_concurrent_pages
    try:
        reply, ctx = _call("차례")
        assert reply.braille == "⠰⠣⠐⠌"
        ctx.abort.assert_not_called()
    finally:
        grpc_server._in_flight = 0
