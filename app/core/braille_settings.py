"""개인 점역 기본값 — **항목 정의의 정본**.

## 왜 AI가 정의하나 (관리자 대시보드 기획서 V11 §7)

    개인 점역 기본값 | BE | T3 | 계정 단위 설정 저장. **항목 목록은 AI가 스키마로 줍니다**.

저장·화면은 BE·FE 몫이고, "무엇을 고를 수 있고 값의 범위가 무엇인지"는 AI가 안다.
조판 규칙을 가진 쪽이 여기라서다. BE가 이 스키마를 받아 설정 화면을 만들고, 저장한
값을 작업마다 `BrailleRequest.settings`에 실어 보낸다(기획서 T3: "새 작업이 이 값으로
시작합니다").

## ⚠ 지금 상태 — 배선된 것과 아직 아닌 것

스키마와 계약은 여기서 끝나지만, **값을 받아 실제로 조판을 바꾸는 배선은 항목마다
진도가 다르다.** 아래 `wired` 필드가 그 진실을 담는다. 안 된 것을 된 것처럼 BE에
넘기면 설정 화면만 만들어 놓고 아무 일도 안 일어난다.

`COLS`/`ROWS`/`DOUBLE_SIDED`는 지금 `braille/constants.py`의 **모듈 전역**이고
translator·table_braille·layout_braille 22곳에서 읽는다. 요청마다 바꾸려면 그 경로를
인스턴스 값으로 내리는 리팩터가 먼저다 — 조판은 C5 블로커가 걸린 경로라 한 번에
건드리지 않는다.
"""
from __future__ import annotations

import contextvars
from dataclasses import asdict, dataclass, field

from app.ai.braille import constants as _C


@dataclass(frozen=True)
class _Item:
    """설정 1항목의 스키마. BE는 이걸 그대로 화면으로 옮긴다."""
    key: str
    label: str            # 화면 표시명(기획서 문구 그대로)
    type: str             # "int" | "bool" | "enum"
    default: object
    choices: tuple = ()   # enum이면 (값, 표시문구) 쌍
    minimum: int = 0
    maximum: int = 0
    note: str = ""
    wired: bool = False   # AI가 실제로 이 값을 적용하는가


# 기획서 T3 §점역 기본 설정의 7항목. 순서·표시명을 화면과 맞춘다.
SCHEMA: tuple[_Item, ...] = (
    _Item("page_rows", "면 규격 — 줄 수", "int", _C.ROWS, minimum=20, maximum=30,
          note="BBPG 1장1절3 기본 26줄. 페이지행이 붙는 면은 본문이 한 줄 줄어든다."),
    _Item("page_cols", "면 규격 — 칸 수", "int", _C.COLS, minimum=28, maximum=40,
          note="BBPG 1장1절3 기본 32칸."),
    _Item("page_line", "페이지행", "enum", "every",
          choices=(("every", "매 면에"), ("odd_only", "홀수 면에만")),
          note="양면 행간인쇄 책은 홀수 면에만 넣는다(BBPG 1장2절2). "
               "현재 기본은 단면 전제라 매 면이다."),
    _Item("footer_format", "꼬리말 형식", "enum", "book_and_volume",
          choices=(("book_and_volume", "도서명 + 권 번호"),
                   ("book_only", "도서명만"), ("none", "쓰지 않음"))),
    _Item("default_mode", "기본 변환 모드", "enum", "c",
          choices=(("a", "OCR 변환"), ("b", "점역 변환"), ("c", "통합 변환")),
          note="BrailleRequest.mode로 이미 요청마다 지정된다 — BE가 이 기본값을 채워 보낸다.",
          wired=True),
    _Item("box_borders", "표·글상자 테두리", "bool", True,
          note="끄면 테두리 없이 1단으로 편다. 표 구조가 사라지므로 기본은 사용함.",
          wired=True),
    _Item("visual_omission_text", "그림 생략 표시", "enum", "write",
          choices=(("write", '"그림 생략"을 적음'), ("blank", "아무것도 적지 않음")),
          note="시각자료 1안(생략)의 문구. 자료지침 예6-8이 '그림 생략'을 쓴다.",
          wired=True),
    _Item("tn_start_col", "점역자 주 시작", "int", 3, minimum=1, maximum=7,
          note="점역자 주 표(⠠⠄)가 시작하는 칸. BBPG 1장2절6."),
)

_BY_KEY = {i.key: i for i in SCHEMA}


def schema_for_be() -> list[dict]:
    """BE에 넘길 설정 항목 목록. 화면 문구·타입·기본값·허용범위·배선 여부까지.

    `wired=False`인 항목은 **저장은 되지만 아직 조판에 반영되지 않는다** — BE가
    화면에 그렇게 표시하든, 그 항목을 나중에 열든 선택할 수 있게 사실대로 준다.
    """
    return [asdict(i) for i in SCHEMA]


@dataclass
class Settings:
    """한 요청에 적용할 설정. 빠진 값은 스키마 기본값으로 채운다."""
    values: dict = field(default_factory=dict)

    def get(self, key: str):
        item = _BY_KEY.get(key)
        if item is None:
            raise KeyError(f"모르는 설정 키: {key}")
        v = self.values.get(key)
        return item.default if v is None else v

    @classmethod
    def from_dict(cls, d: dict | None) -> "Settings":
        """모르는 키·범위 밖 값은 **조용히 버린다** — 설정 하나 때문에 점역이 멈추면 안 된다."""
        out: dict = {}
        for k, v in (d or {}).items():
            item = _BY_KEY.get(k)
            if item is None or v is None:
                continue
            if item.type == "int":
                try:
                    iv = int(v)
                except (TypeError, ValueError):
                    continue
                if item.minimum <= iv <= item.maximum:
                    out[k] = iv
            elif item.type == "bool":
                out[k] = bool(v)
            elif item.type == "enum" and v in {c[0] for c in item.choices}:
                out[k] = v
        return cls(out)


_current: contextvars.ContextVar[Settings] = contextvars.ContextVar(
    "braille_settings", default=Settings())


def set_current(s: Settings) -> None:
    _current.set(s)


def current() -> Settings:
    return _current.get()


def get(key: str):
    """지금 요청의 설정값. 요청 밖(테스트·배치)에서는 기본값."""
    return current().get(key)


if __name__ == "__main__":   # 자체 점검
    assert len(SCHEMA) == 7 + 1, "기획서 7항목(면 규격은 줄·칸 둘로 나뉜다)"
    s = Settings.from_dict({"page_rows": 24, "page_cols": 999, "box_borders": False,
                            "page_line": "odd_only", "없는키": 1, "tn_start_col": "3"})
    assert s.get("page_rows") == 24                 # 범위 안 → 반영
    assert s.get("page_cols") == _C.COLS            # 범위 밖 → 기본값
    assert s.get("box_borders") is False
    assert s.get("page_line") == "odd_only"
    assert s.get("tn_start_col") == 3               # 문자열도 int로
    assert Settings.from_dict(None).get("page_rows") == _C.ROWS
    assert Settings.from_dict({"page_line": "이상한값"}).get("page_line") == "every"
    assert all(k in {i["key"] for i in schema_for_be()} for k in
               ("page_rows", "page_line", "box_borders", "visual_omission_text"))
    print(f"braille_settings 자체 점검 통과 — {len(SCHEMA)}항목, "
          f"배선 완료 {sum(i.wired for i in SCHEMA)}개")
