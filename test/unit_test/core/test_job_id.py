"""job_id 생성·출처 판별 회귀 테스트."""
import re

from app.utils.job_id import generate, source_from_peer

_FMT = re.compile(r"^job_(be|local)_\d{10}_[0-9a-f]{6}$")


class TestGenerate:
    def test_be_형식(self):
        assert _FMT.match(generate("be"))

    def test_local_형식(self):
        assert _FMT.match(generate("local"))

    def test_매번_다름(self):
        assert generate("be") != generate("be")  # 랜덤 해시


class TestSourceFromPeer:
    def test_원격은_be(self):
        assert source_from_peer("ipv4:34.158.215.55:52686") == "be"

    def test_localhost는_local(self):
        assert source_from_peer("ipv4:127.0.0.1:53140") == "local"
        assert source_from_peer("ipv6:[::1]:5000") == "local"
        assert source_from_peer("unix:/tmp/x.sock") == "local"

    def test_None은_be(self):
        assert source_from_peer(None) == "be"
