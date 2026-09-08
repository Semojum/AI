"""T5-4 파인튜닝 스켈레톤 단위 테스트 (GPU-free).

데이터 포맷·JSONL 입출력·프롬프트 빌드(추론 템플릿 재사용)·시드 고정·학습 가드를 검증.
실제 학습은 스켈레톤이므로 run()이 NotImplementedError로 막혀 있는지 확인한다.
"""

from __future__ import annotations

import random

import pytest

from app.ai.llm.finetune.data_format import (
    ELEMENT_TYPES,
    TrainingExample,
    from_jsonl,
    to_jsonl,
)
from app.ai.llm.finetune.dataset import (
    build_chat_pair,
    build_prompt,
    load_sft_dataset,
    set_seed,
)


def _ex(element_type="text", input_text="안너영", target="안녕"):
    return TrainingExample(element_type=element_type, input_text=input_text, target_text=target)


class TestDataFormat:
    def test_유효_유형(self):
        for t in ELEMENT_TYPES:
            assert TrainingExample(element_type=t, input_text="x", target_text="y").element_type == t

    def test_잘못된_유형_거부(self):
        with pytest.raises(ValueError):
            TrainingExample(element_type="diagram", input_text="x", target_text="y")

    def test_jsonl_왕복(self, tmp_path):
        exs = [_ex(), _ex("formula", "x^2", "x²"), _ex("text", "안너영", "안녕")]
        path = tmp_path / "sft.jsonl"
        assert to_jsonl(exs, path) == 3
        loaded = from_jsonl(path)
        assert [e.model_dump() for e in loaded] == [e.model_dump() for e in exs]

    def test_jsonl_빈줄_무시(self, tmp_path):
        path = tmp_path / "sft.jsonl"
        path.write_text('{"element_type":"text","input_text":"a","target_text":"b"}\n\n', encoding="utf-8")
        assert len(from_jsonl(path)) == 1


class TestPromptBuild:
    def test_프롬프트_입력_삽입(self):
        out = build_prompt(_ex("text", "안너영"))
        assert "안너영" in out

    def test_유형별_템플릿(self):
        assert "x^2" in build_prompt(_ex("formula", "x^2", "x²"))
        assert "셀1 | 셀2" in build_prompt(_ex("table", "셀1 | 셀2", "[점역사주] 표"))

    def test_chat_쌍_구조(self):
        pair = build_chat_pair(_ex())
        roles = [m["role"] for m in pair["messages"]]
        assert roles == ["user", "assistant"]
        assert pair["messages"][1]["content"] == "안녕"

    def test_load_sft_dataset(self, tmp_path):
        path = tmp_path / "sft.jsonl"
        to_jsonl([_ex(), _ex("formula", "x^2", "x²")], path)
        ds = load_sft_dataset(path)
        assert len(ds) == 2
        assert all(d["messages"][0]["role"] == "user" for d in ds)

    @pytest.mark.parametrize("etype", ["cartoon", "image", "chart_graph"])
    def test_규칙조립_유형은_프롬프트학습_제외(self, etype: str):
        """규칙으로 조립하는 유형은 학습할 프롬프트가 없다 — 명확히 거부한다.

        ★ 2026-09-08(재구조화 5단계) — 만화뿐이던 이 목록에 image·chart_graph 가 들어왔다.
          시각 4안의 LLM 팔(L8)을 지우면서 `visual_drafts._PROMPT` 가 없어졌기 때문이다.
        """
        with pytest.raises(ValueError):
            build_prompt(_ex(etype, "두 컷", "..."))


class TestSeed:
    def test_시드_재현성(self):
        set_seed(123)
        a = [random.random() for _ in range(5)]
        set_seed(123)
        b = [random.random() for _ in range(5)]
        assert a == b


class TestTrainGuard:
    def test_학습_미구현_가드(self, tmp_path):
        from app.ai.llm.finetune.train import TrainConfig, run
        path = tmp_path / "sft.jsonl"
        to_jsonl([_ex()], path)
        with pytest.raises(NotImplementedError):
            run(TrainConfig(data_path=str(path), output_dir=str(tmp_path / "out")))

    def test_데이터_없으면_에러(self, tmp_path):
        from app.ai.llm.finetune.train import TrainConfig, run
        with pytest.raises(FileNotFoundError):
            run(TrainConfig(data_path=str(tmp_path / "none.jsonl"), output_dir=str(tmp_path / "out")))

    def test_빈_데이터_거부(self, tmp_path):
        from app.ai.llm.finetune.train import TrainConfig, run
        path = tmp_path / "empty.jsonl"
        path.write_text("", encoding="utf-8")
        with pytest.raises(ValueError):
            run(TrainConfig(data_path=str(path), output_dir=str(tmp_path / "out")))
