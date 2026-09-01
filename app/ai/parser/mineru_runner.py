"""
MinerU VLM 백엔드로 PDF 단일 페이지 처리.

입력:  pdf_path, page_no (1-indexed), job_id, extraction_method
출력:  storage/jobs/{job_id}/temp/page_{no:03d}/
        mineru_raw/images/{element_id}.jpg  (이미지/표 요소)
       debug=True 시 추가:
        storage/jobs/{job_id}/temp/page_{no:03d}/merged_layout.json
반환:  merged_layout (list[dict])
"""
import json
import os
import re
import shutil
import subprocess
import sys
import uuid
from difflib import SequenceMatcher
from pathlib import Path

import fitz

from app.utils.logger import get_logger

logger = get_logger(__name__)

TYPE_MAP = {
    "title":               "title",
    "text":                "text",
    "caption":             "caption",
    "interline_equation":  "formula",
    "inline_equation":     "formula",
    "equation":            "formula",
    "list":                "list_item",
    "footnote":            "footnote",
    "sidebar":             "sidebar",
    "header":              "header_footer",
    "header_footer":       "header_footer",
    "page_number":         "page_number",
    "table":               "table",
    "image":               "image",
    "chart":               "chart_graph",
    "cartoon":             "cartoon",
    "figure":              "image",
}

# ── 제목 단계(NLD 2장2절1) ──────────────────────────────────────────────────
# MinerU는 제목 블록을 이미 찾아 놓는다. 다만 `content_list`에서는 type이 "text"로
# 눕고 단계만 `text_level`에 남는다(vlm_middle_json_mkcontent.py: BlockType.TITLE →
# ContentType.TEXT + text_level). 종전에는 그 값을 통째로 버리고 heading_level=None을
# 박아, 조판이 1단계 가운데 정렬·2단계 7칸·3·4단계 5칸을 **한 번도 못 썼다**
# (QA 실측 2026-08-07: 37쪽 558요소에 title 0개·heading_level 0개).
#
# ⚠ MinerU의 표시를 그대로 믿으면 안 된다. 전 코퍼스 7,273곳을 열어 보니 65%만
#   진짜 제목이고 나머지는 **문항 발문·선택지**다(굵은 큰 글씨라 같이 잡힌다).
#   발문이 제목이 되면 가운데 정렬로 나가고 앞뒤 빈 줄까지 붙어 더 나빠진다.
#   그래서 아래 셋을 걸러 낸다.
#
# 단계 대응은 **정답 도서 실측**으로 정했다(refonly 94권 137만 줄):
#     1단계 가운데   0.93%   ← MinerU lv1
#     3·4단계 5칸    1.45%   ← MinerU lv2 이상
#     2단계 7칸      0.18%   ← 거의 안 쓴다. 쓰지 않는다
# ★ 3단계가 아니라 **4단계**다(2026-08-08 대표 결정). 정답 도서의 5칸 시작 줄 1,651줄을
#   보면 위에 빈 줄 26.7% · 아래에 빈 줄 2.7%로, 아래를 거의 안 띄운다. 4단계가 (1,0)이라
#   그 모양에 맞는다. 3단계로 두면 아래 빈 줄이 계속 들어가 정답보다 빈 줄이 많아진다.
#
# ★ 2026-08-28 — **lv1 을 1단계가 아니라 2단계로 보낸다**(원장 C-79).
#   위 refonly 수치는 2027 코퍼스에서 재현되지 않는다. dev·val-2027 gold 전수 177,750줄:
#       앞빈칸 6칸(2단계 7칸)      455줄  0.26%
#       앞빈칸 7칸 이상(가운데)      89줄  0.05%
#   **순서가 뒤집혀 있다.** refonly 가 무엇을 "가운데"로 셌는지는 여기서 확인할 수 없다 —
#   느슨한 판정(`앞빈칸 == (32-길이)//2 ±1`)을 쓰면 6칸 줄까지 가운데로 잡히는데,
#   6칸 455줄 중 **292줄은 그 계산과 어긋난다**(길이 25인데 앞 6 · 길이 2인데 앞 6).
#   즉 gold 의 6칸은 정렬이 아니라 **지침 §2.4.2(1) 의 "2단계 7칸" 고정 들여쓰기**다.
#
#   영향 범위 — **앞뒤판 전수(braille M013)로 확정했다.** 6칸으로 새로 가는 줄이
#       dev 18 · val 22 = **40줄**, 그중 gold 도 6칸인 것이 dev 75% · val 89%(합 82%).
#   ⚠ 내가 먼저 코드 출력으로 어림한 값은 dev 18 · val 8 = 26줄이었고 **val 을 낮게 봤다.**
#     원인은 `layout_braille._center` 다 — 32셀 이상이면 가운데 정렬을 **안 하고 그대로**
#     돌려줘서(그 함수 참조) 긴 강 제목이 앞빈칸 0으로 나갔다. '가운데꼴로 나온 줄'만
#     세면 그것들이 통째로 빠진다. 한국어 강 제목은 32셀을 쉽게 넘어 val(동아시아사·
#     화법과작문)에 특히 많았다. 실제 효과가 어림보다 **크다**.
#   gold 6칸 452줄 중 나머지는 우리가 **제목으로 잡지도 못한다**(MinerU 가 header_footer 로
#   뺀다 — 013 body p0061 "실전 수능 문제" 실측). 그건 이 맵으로 못 고친다.
#
#   ⚠ ZERO 티어(텍스트레이어 직행) 쪽은 `title` 요소가 없어 **효과가 구조적으로 0**이다
#     (dev 69쪽 · val 231쪽). 회귀가 아니라 적용 대상 밖이다.
#   ⚠ lv1 48건을 눈으로 전수 확인했다 — **진짜 강 제목 44건 · 오검출 4건(8%)**
#     (`是` 한 자, OCR 깨진 본문, `대표 기출  확인하기 | …` 꼴 둘). 이 맵이 만든 게 아니라
#     원래 있던 오검출이 6칸으로 나가며 눈에 띈 것이다. 제목 판정 자체는 별건이다.
#
#   ⚠ 같은 강 제목을 **책마다 다르게** 적는다(001 은 body 6칸 / ans 가운데). 어느 단계인지
#     판정할 근거가 묵자에 없다 — 원장 C-79 에 자문 항목으로 올려 뒀다.
#   ⚠ lv1 이 2단계가 되면 `_HEADING_BLANK[2] = (1, 1)` 이 처음으로 살아나 제목 **위**에도
#     빈 줄이 붙는다. 지침 §2.4.4(2)① 은 1·2단계는 아래만 띄라고 하지만 gold 는 쪽 중간
#     6칸 제목 107건 중 **99건(93%)에서 위를 띈다**. 관행형이 맞다(원장 C-80).
_HEAD_CHOICE_RE = re.compile(r"^\s*[①-⑳]")             # 선택지는 제목이 아니다
_HEAD_END_RE = re.compile(r"[.?!]\s*$|것은\s*\??$|않은\s*것\s*은?\s*\??$|하시오\.?$")
_HEAD_MAX_LEN = 28                                      # 이보다 길면 제목이 아니라 문장
_HEAD_LEVEL_MAP = {1: 2}                                # lv1 → 2단계(7칸), 그 외 → 4단계


_announced_engine: str | None = None


def _announce_engine(mineru_bin: str) -> None:
    """어느 MinerU를 쓰는지 **처음 한 번 크게 찍는다**.

    ★ 2026-08-09 — 이게 없어서 평가 세션이 20분을 날렸다. 셸에 `MINERU_BIN`이 이미
      export돼 있으면 자식이 상속받고, 우선순위가 `환경변수 > .env`라 `.env`에 vLLM을
      적어 두어도 **조용히 transformers로 돈다**. 예외가 안 나서 결과만 보면 모른다.

      우선순위를 환경변수 우선으로 둔 건 의도다(측정 스크립트가 엔진 A/B를 해야 한다).
      그래서 순서를 바꾸는 대신 **무엇이 이겼는지 보이게** 한다.

      절차: `env -u MINERU_BIN …`으로 지우고 돌린 뒤
            `grep "init successfully" storage/logs/mineru_api.log`로 엔진을 확인할 것.
    """
    global _announced_engine
    if _announced_engine == mineru_bin:
        return
    _announced_engine = mineru_bin
    src = "환경변수 MINERU_BIN" if os.environ.get("MINERU_BIN") else ".env(config.mineru_bin)"
    kind = "vLLM" if "vllm" in mineru_bin.lower() else "transformers(또는 미상)"
    logger.info("MinerU 실행 파일 = %s  [출처: %s · 추정 엔진: %s]", mineru_bin, src, kind)


def _heading_level(item: dict, mapped_type: str, content: str) -> int | None:
    """MinerU `text_level` → NLD 제목 단계. 제목이 아니면 None."""
    lvl = item.get("text_level")
    if not lvl or mapped_type != "text":
        return None
    t = (content or "").strip()
    if not t or len(t) > _HEAD_MAX_LEN:
        return None
    if _HEAD_CHOICE_RE.match(t) or _HEAD_END_RE.search(t):
        return None
    return _HEAD_LEVEL_MAP.get(int(lvl), 4)


class MineruTimeout(RuntimeError):
    """추출이 페이지 예산을 다 태운 경우. **재시도하지 않는다** — 다시 부르면 예산이 두 배다."""


# 재시도 횟수(총 시도 = 1 + 이 값). MinerU 는 같은 지면·같은 코드에서도 **비결정으로** 죽는다 —
# `The expanded size of the tensor (2) must match the existing size (0)` 가 그 얼굴이다.
# 실측(시연 12쪽, 2026-08-26): 07:26 판 폴백 0 · 12:27 판 2 · 13:15 판 1 · 13:14 재시도 성공.
# 죽으면 텍스트레이어 폴백으로 가는데, 폴백은 **인쇄 줄 하나가 요소 하나**라 표·그림 구조가
# 통째로 사라진다(대표 시연 지적 둘이 이것 하나 때문이었다 — 2쪽 표·3쪽 사진).
# 한 번 더 부르면 사라지는 손해라 재시도를 넣는다. 다 실패하면 종전대로 폴백이다.
_MINERU_RETRIES = int(os.environ.get("MINERU_RETRIES", "1"))


def _run_mineru(pdf_path: Path, out_dir: Path, page_idx: int, timeout: float | None = None) -> None:
    # MinerU는 별도 env에 설치(transformers 버전 충돌 회피). bare 'mineru'가 PATH에
    # 없을 수 있어 MINERU_BIN으로 실행 파일 경로를 덮어쓸 수 있게 한다(GCP는 심볼릭).
    # 우선순위: 환경변수 > .env(config) > PATH. 환경변수를 위에 두어 측정 스크립트가
    # 한 번만 덮어쓸 수 있게 한다(엔진 A/B에 쓴다).
    from app.core.config import config as _cfg
    mineru_bin = os.environ.get("MINERU_BIN") or _cfg.mineru_bin or "mineru"
    _announce_engine(mineru_bin)
    cmd = [
        mineru_bin, "-p", str(pdf_path), "-o", str(out_dir),
        "-s", str(page_idx), "-e", str(page_idx),   # 도착 PDF 내 0-based 인덱스
    ]
    # 영구 mineru-api가 떠 있으면 thin client로 붙어 모델 재로드를 피한다(추출 대폭 단축).
    # 없으면 요청마다 로컬 VLM 로드(vlm-engine 폴백).
    from app.ai.parser import mineru_service
    api_url = mineru_service.get_url()
    # ★ 2026-07-29 — 백엔드를 **경로와 무관하게 명시**한다.
    #   종전엔 영구 서비스가 떠 있으면 -b를 안 넘겨 MinerU 기본값 **hybrid-engine**이 쓰이고,
    #   서비스가 없을 때만 vlm-engine이 쓰였다. 즉 **같은 문서가 서비스 가동 여부에 따라 다른
    #   백엔드로** 처리됐다. 실측 피해(사회문화 p178, 동일 페이지):
    #     hybrid+effort medium(구 기본) → text 35 · list **0**   (본문 과분절·목록 소실)
    #     vlm-engine 또는 hybrid+high   → text  8 · list  7      (07-17 캐시와 일치)
    #   목록이 사라지면 글머리 3칸 들여쓰기(NLD 2장3절5)가 통째로 빠진다.
    backend = os.environ.get("MINERU_BACKEND", "hybrid-engine")
    cmd += ["-b", backend]
    if api_url:
        cmd += ["--api-url", api_url]
    # hybrid 백엔드의 파싱 강도.
    # 품질 — 동일 페이지(사회문화 p178) 실측: medium은 text 35·list **0**(본문 과분절·목록 소실),
    #   high는 text 8·list 7로 vlm-engine과 같다. 품질 차이는 백엔드가 아니라 **effort**다.
    # ★ 그럼에도 기본값을 medium으로 둔다 — **180초 페이지 예산(C7)을 못 지키기 때문이다.**
    #   2026-07-29 실측(시각요소 최다 10쪽 + 동시성 시험):
    #     · high 최악 페이지 생물 p113 = **143.9초**(순차 1쪽, 예산의 80%)
    #     · high 추출 동시 2쪽 배율 = **1.70배**(49.2초 → 83.5초)
    #     · 최악 페이지에 적용 = 79×1.70 + 65 = **199초 → 예산 초과**
    #     · medium 환산 = 순차 80초 · 동시 2쪽 85초(여유 53%)
    #   품질 대가는 같은 dev 28쪽 짝 비교로 −0.85p뿐이라, 예산 위반·원가 +61%
    #   (쪽당 356→573원, 서버 1→2대)와 바꿀 크기가 아니다.
    # 목록 구조는 effort로 사지 말고 후처리(글머리 기호로 list_item 승격)로 회복할 것.
    # high로 올리려면 **동시 처리를 1로 낮추고 원가를 재산정**한 뒤여야 한다.
    effort = os.environ.get("MINERU_EFFORT", "medium" if "hybrid" in backend else None)
    if effort in ("medium", "high"):
        cmd += ["--effort", effort]
    try:
        # timeout: 페이지 예산(C7)을 MinerU가 다 태우기 전에 서브프로세스를 끊는다(C9).
        # 초과 시 subprocess가 프로세스를 kill하므로 고아 프로세스가 남지 않는다.
        result = subprocess.run(cmd, capture_output=False, text=True, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        raise MineruTimeout(
            f"MinerU 추출 타임아웃 (>{exc.timeout:.0f}s, page_idx={page_idx}) — 텍스트레이어 폴백 대상"
        ) from exc
    if result.returncode != 0:
        # sys.exit 금지: 라이브러리가 프로세스를 죽이면 안 된다. 예외를 올려 호출자
        # (pipeline 페이지 격리 / 러너)가 해당 페이지만 ERROR 처리하고 계속하게 한다.
        raise RuntimeError(f"MinerU 실행 실패 (returncode={result.returncode}, page_idx={page_idx})")


def _find_content_list(out_dir: Path) -> Path:
    candidates = list(out_dir.rglob("*_content_list.json"))
    if not candidates:
        raise FileNotFoundError(f"content_list.json not found under {out_dir}")
    return candidates[0]


def _cleanup_mineru_output(raw_dir: Path) -> None:
    for pattern in ("*_content_list_v2.json", "*.md", "*_layout.pdf", "*_origin.pdf"):
        for f in raw_dir.rglob(pattern):
            f.unlink()


def _flatten_mineru_output(raw_dir: Path) -> None:
    """
    MinerU가 만든 {pdf_stem}/{backend}/ 중첩 구조를 raw_dir/ 바로 아래로 펼침.
    JSON → raw_dir/*.json
    이미지 → raw_dir/images/*.jpg
    빈 서브디렉토리 제거
    """
    images_dir = raw_dir / "images"
    images_dir.mkdir(exist_ok=True)

    # JSON 파일 → raw_dir 루트
    for f in list(raw_dir.rglob("*.json")):
        if f.parent != raw_dir:
            shutil.move(str(f), str(raw_dir / f.name))

    # 이미지 파일 → raw_dir/images/
    for f in list(raw_dir.rglob("*.jpg")):
        if f.parent != images_dir:
            dst = images_dir / f.name
            if not dst.exists():
                shutil.move(str(f), str(dst))

    # 빈 서브디렉토리 제거
    for item in list(raw_dir.iterdir()):
        if item.is_dir() and item != images_dir:
            shutil.rmtree(str(item))


# ── 캡셔닝용 크롭 재렌더 ────────────────────────────────────────────────────
# MinerU가 주는 크롭은 **200DPI로 렌더된 페이지 비트맵을 자른 것**이다(실측: 크롭 픽셀
# 폭 = bbox/1000 × 페이지pt/72 × 200, 오차 1px). dev 331장 중앙 334×214px이라 도식의
# 이름표(㉠·㉡, 축 눈금, 첨자)가 뭉개져 캡션이 그걸 잘못 읽었다.
# 원본 PDF는 벡터라 같은 자리를 더 높은 DPI로 다시 렌더하면 **화소가 진짜로 는다**.
# 실측(2026-08-10, 오독 확인 도표·그래프 30장, 같은 600DPI 이미지로 판정):
#   200DPI(MinerU 그대로) 오독 77건/21장 · 300DPI 46건/13장(p=0.0015)
#   600DPI 38건/9장(p=0.0001) · 150DPI 69건/24장(개선 없음 — DPI가 원인이 맞다)
#   근거 있는 진술(ok)은 7.57 → 9.73으로 **늘었다**(짧게 써서 줄인 게 아니다).
# ⚠ 이미 렌더된 비트맵의 **업스케일은 반대로 나쁘다**(3배 확대 사실오류 35.0%→44.5%,
#   p=0.002). 없는 화소를 늘리면 모델이 더 확신하고 더 틀린다. 그래서 아래 _raster_dpi_cap이
#   스캔 쪽(래스터 원본)에서는 원본 해상도 위로 못 올라가게 막는다.
_CROP_DPI = 600        # 300→600은 표본 30장에서 유의하지 않았다(p=0.42). 점추정이 나은 쪽.
_CROP_MAX_EDGE = 1568  # 이보다 크면 API가 되레 줄여 이득 없이 토큰만 든다
_MINERU_CROP_DPI = 200


def _raster_dpi_cap(clip: fitz.Rect, img_info: list[dict]) -> float:
    """clip에 걸친 래스터 이미지의 실제 해상도(DPI). 벡터뿐이면 무한대.

    스캔 PDF에서 원본 해상도 위로 렌더하면 그냥 업스케일이라 오히려 해롭다(위 주석).
    """
    caps = [im["width"] / max(fitz.Rect(im["bbox"]).width, 1e-6) * 72
            for im in img_info
            if im.get("width") and fitz.Rect(im["bbox"]).intersects(clip)]
    return min(caps) if caps else float("inf")


def _recrop_hidpi(fitz_page: fitz.Page, bbox: list[float], dst: str,
                  img_info: list[dict]) -> bool:
    """MinerU 크롭을 원본 PDF의 고DPI 재렌더로 교체한다. 실패해도 원본 크롭이 남는다."""
    r = fitz_page.rect
    clip = fitz.Rect(r.x0 + bbox[0] / 1000 * r.width, r.y0 + bbox[1] / 1000 * r.height,
                     r.x0 + bbox[2] / 1000 * r.width, r.y0 + bbox[3] / 1000 * r.height)
    if clip.is_empty or clip.width < 1 or clip.height < 1:
        return False
    dpi = min(_CROP_DPI, _CROP_MAX_EDGE * 72 / max(clip.width, clip.height),
              _raster_dpi_cap(clip, img_info))
    if dpi <= _MINERU_CROP_DPI:
        return False                      # 더 얻을 화소가 없다 — MinerU 크롭 그대로 둔다
    try:
        # 내림 — 반올림하면 상한을 1~2px 넘겨 서버가 되레 축소한다
        fitz_page.get_pixmap(dpi=int(dpi), clip=clip).save(dst, jpg_quality=95)
    except Exception as exc:  # noqa: BLE001 — 크롭 품질은 있으면 좋은 것, 실패는 격리
        logger.warning("고DPI 재크롭 실패 %s: %s", Path(dst).name, exc)
        return False
    return True



# ── 글자를 그림으로 잡은 것을 표시한다 (원장 C-40 부록, 2026-08-23) ──────────────
# 그림이 없는 텍스트 영역이 시각 요소로 잡히면 캡셔너가 **그 글자를 읽어** 설명으로 낸다
# (실측: "그림: 본문: 28번 문제 … 인 사면체 ABCD가 있다"). 없는 그림의 설명은 점역사가
# 알아채기 제일 어려운 오류다.
#
# 가르는 신호는 **같은 자리를 두 번 잡았는가**다. 레이아웃이 텍스트와 그림을 갈라 놓으므로
# 정상이면 겹칠 이유가 없고, 글자를 그림으로 잡으면 그 텍스트 요소와 bbox가 거의 같다.
#
# ★ 손해를 전수로 재서 골랐다(dev 정상 시각 요소 830건):
#     · '텍스트에 덮인 비율'은 꼬리가 길어 임계 0.9에서 정상 25건(3.0%)이 죽는다 —
#       진짜 그림인데 축 라벨·캡션이 텍스트 요소로 겹쳐 잡힌 것들이다.
#     · **IoU는 0.8 이상이 0건**이다(0.7 이상도 1건, 0.1%). 그래서 IoU를 쓴다.
#   임계 0.8은 여유를 둔 값이다. 딱 붙이면 스캔본에서 값이 조금만 흔들려도 놓친다.
#
# ⚠ 한계: 이 분리가 잘 되는 이유가 교과서 코퍼스에서 레이아웃이 애초에 겹치게 안 잡기
#   때문일 수 있다. 스캔본에서도 그런지는 표본이 없어 확인하지 못했다(원장 C-40).
#   그래서 발동을 로그로 남긴다 — 실사용에서 세어 보는 것이 그 물음에 답하는 유일한 길이다.
_TEXT_LOOKALIKE_IOU = 0.8
_LOOKALIKE_TEXT_TYPES = frozenset({
    "text", "title", "caption", "list_item", "footnote", "sidebar",
    "header_footer", "page_number", "formula", "table",
})


def _bbox_iou(a: list[float], b: list[float]) -> float:
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0.0


def _mark_text_lookalikes(elements: list[dict], page_no: int) -> int:
    """텍스트 요소와 자리가 거의 같은 시각 요소에 표시를 남긴다. 표시한 개수 반환."""
    texts = [e["bbox"] for e in elements
             if e.get("type") in _LOOKALIKE_TEXT_TYPES
             and isinstance(e.get("bbox"), list) and len(e["bbox"]) == 4]
    if not texts:
        return 0
    n = 0
    for el in elements:
        bb = el.get("bbox")
        if el.get("type") not in ("image", "chart_graph", "cartoon", "diagram"):
            continue
        if not isinstance(bb, list) or len(bb) != 4:
            continue
        best = max((_bbox_iou(bb, t) for t in texts), default=0.0)
        if best >= _TEXT_LOOKALIKE_IOU:
            el["text_lookalike_iou"] = round(best, 3)
            n += 1
            logger.info("가드3 글자를 그림으로 잡음 — page=%d id=%s iou=%.3f",
                        page_no, str(el.get("element_id", ""))[:8], best,
                        extra={"page": page_no, "guard": 3, "iou": round(best, 3),
                               "stage": "캡셔닝", "status": "SKIPPED"})
    return n


def _extract_text_native(fitz_page: fitz.Page, bbox: list[float]) -> str:
    w, h = fitz_page.rect.width, fitz_page.rect.height
    rect = fitz.Rect(
        bbox[0] / 1000 * w, bbox[1] / 1000 * h,
        bbox[2] / 1000 * w, bbox[3] / 1000 * h,
    )
    return fitz_page.get_text("text", clip=rect).strip()


# ── 텍스트 레이어 우선(하이브리드) ────────────────────────────────────────────
# MinerU는 레이아웃(블록 경계·읽기순서·시각자료 탐지)에 쓰고, 글자는 PDF 텍스트 레이어에서
# 가져온다. 교과서 PDF는 대부분 텍스트 레이어가 있는데도 표·그림 때문에 STANDARD(OCR)로
# 라우팅돼 VLM이 글자를 다시 읽었고, 그 과정에서 오탈자가 났다
# (예: "내동댕이치고"→"내동 Charging이치고", "불을 살랐다"→"붙을 살랐다").
# dev 18p 측정: 무수정 실패 요소의 절반 이상이 이 추출 오탈자였다.
_NATIVE_TEXT_TYPES = frozenset({
    "text", "title", "caption", "list_item", "footnote", "sidebar",
    "header_footer", "page_number",
})
# 수식은 제외 — 한컴 수식 폰트 PDF는 수식을 PUA로 인코딩해 텍스트 레이어가 깨진다.
# 표도 제외 — MinerU가 내는 건 HTML 구조(table_body)라 평문으로 대체하면 구조가 사라진다.
_PUA_RATIO_MAX = 0.05     # 사설 영역 글리프가 이 비율을 넘으면 텍스트 레이어를 믿지 않는다
_SIM_MIN = 0.45           # MinerU 결과와 이만큼도 안 닮으면 bbox가 어긋난 것 → 대체 안 함


# ── 표 셀 글머리 기호 복원 ───────────────────────────────────────────────────
# 「한국 점자 규정」 제72항(규정_텍스트.txt:2892)은 ○ □ △ •를 **글머리 기호**로 규정한다.
# 즉 표 셀 안의 •는 장식이 아니라 항목 경계다. MinerU가 이를 놓치면(통째 소실 또는
# 가운뎃점 ·로 하향 오독) 셀이 "…가능함연구 대상에…"처럼 항목이 들러붙은 런온 문장이 되고,
# 점자에서도 항목 구분이 사라진다.
# 표는 위 _NATIVE_TEXT_TYPES에서 제외돼 있다(HTML 구조를 평문으로 덮으면 표가 깨진다).
# 그래서 텍스트 전면 대체 대신 **글머리 글리프만** 텍스트 레이어를 근거로 되돌린다.
# 판단 근거는 PDF 원문(레이어)이지 정답 코퍼스가 아니며, 특정 페이지·과목 조건은 쓰지 않는다.
_BULLET_GLYPHS = "•‣▪▫●■∙⁃"      # 원문이 글머리로 쓰는 글리프
_BULLET_DEGRADED = "·・･‧"        # 글머리가 하향 오독되는 가운뎃점 계열
_BULLET_KEY_LEN = 10              # 글머리 뒤 본문 n글자를 '항목 지문'으로 삼아 셀에서 찾는다
_BULLET_KEY_MIN = 6               # 이보다 짧아지면 우연 일치 위험 → 셀 첫머리에서만 인정
_BULLET_ANY_RE = re.compile(f"[{_BULLET_GLYPHS}]")
# 레이어 대조에서 무시할 마크업: MinerU가 셀 안 수식에 두르는 $ (묵자 원문에 없다)
_BULLET_SKIP_CHARS = " \t\r\n\f\v$　"


def _bullet_item_keys(layer: str) -> list[str]:
    """레이어 텍스트에서 '글머리 뒤 본문 지문'을 등장 순서대로 뽑는다(공백 제거 기준).

    항목이 짧으면(예 '배우자') 지문도 짧다 — 버리지 않고 그대로 두고, 대조 쪽에서
    셀 첫머리 조건으로 안전을 확보한다.
    """
    ns = re.sub(r"\s+", "", layer)
    keys: list[str] = []
    for m in _BULLET_ANY_RE.finditer(ns):
        tail = ns[m.end():m.end() + _BULLET_KEY_LEN]
        keys.append(_BULLET_ANY_RE.split(tail)[0])   # 다음 글머리 전까지만
    return keys


# 블록 수식을 감싼 `$$`/`$` 한 쌍(QA 11번). 양끝에 붙은 것만 본다 — 식 안에 달러가
# 남아 있으면(통화 표기 등) 짝이 안 맞으므로 손대지 않는다.
_BLOCK_MATH_WRAP_RE = re.compile(r"^\s*(\${1,2})\s*(.*?)\s*\1\s*$", re.DOTALL)


def _strip_block_math_delim(content: str) -> str:
    r"""`$$\n식\n$$` → `식`. 구분자가 없으면 그대로(멱등)."""
    m = _BLOCK_MATH_WRAP_RE.match(content or "")
    return m.group(2) if m else content


def _restore_table_bullets(fitz_page: fitz.Page, bbox: list[float], html: str) -> str:
    """표 셀에서 유실·오독된 글머리 기호를 텍스트 레이어를 근거로 되살린다.

    레이어에 글머리가 없으면 아무것도 하지 않는다(대다수 표는 여기서 끝난다).
    ★ 부분 복원 금지: 한 항목이라도 못 찾으면 그 표는 통째로 손대지 않는다. 같은 셀에서
    항목 하나만 글머리를 달면 나머지 항목이 그 항목의 이어짐처럼 읽혀, 아무것도 안 한
    것보다 위계가 더 어긋난다(생물 p180 실측: 10개 중 4개만 복원 시 편집 +36셀).
    """
    if not html or not bbox:
        return html
    layer = _extract_text_native(fitz_page, bbox)
    if not layer or not _BULLET_ANY_RE.search(layer):
        return html
    if _layer_untrustworthy(layer):
        return html
    keys = _bullet_item_keys(layer)
    if not keys or not all(keys):
        return html

    # 공백·수식 구분자를 뺀 대조본 ↔ 원문 인덱스 대응표
    # (지문은 이 대조본에서 찾고, 수정은 원문 자리에 한다)
    ns_chars, ns_idx = [], []
    for i, ch in enumerate(html):
        if ch not in _BULLET_SKIP_CHARS:
            ns_chars.append(ch)
            ns_idx.append(i)
    ns = "".join(ns_chars)

    ops: dict[int, int] = {}   # 원문 위치 → 덮어쓸 길이(0=삽입, 1=글리프 교체)
    cur = 0
    for key in keys:
        # 지문 꼬리는 레이어 줄바꿈 때문에 옆 블록 글자를 물고 올 수 있다 → 뒤에서 줄여 가며
        # 확실히 공유되는 앞부분만 쓴다.
        occ: list[int] = []
        used_len = len(key)
        for ln_ in range(len(key), 0, -1):
            occ = [m.start() for m in re.finditer(re.escape(key[:ln_]), ns)]
            if occ:
                used_len = ln_
                break
        if not occ:
            return html                     # 한 항목이라도 못 찾으면 이 표는 포기
        if len(occ) == 1:
            p = occ[0]                      # 유일하면 순서와 무관하게 확정
        else:
            later = [x for x in occ if x >= cur]   # 같은 문구가 여러 행에 반복되는 표
            if not later:
                return html
            p = later[0]
        cur = max(cur, p + 1)
        start = ns_idx[p]
        j = start - 1                       # 항목 바로 앞의 '내용' 글자(공백·$ 건너뜀)
        while j >= 0 and html[j] in _BULLET_SKIP_CHARS:
            j -= 1
        if j >= 0 and html[j] in _BULLET_GLYPHS:
            continue                        # 이미 살아 있다
        if used_len < _BULLET_KEY_MIN and not (j >= 0 and html[j] in ">" + _BULLET_DEGRADED):
            return html   # 짧은 지문은 셀 첫머리(또는 남은 글머리 자리)에서만 믿는다
        if j >= 0 and html[j] in _BULLET_DEGRADED:
            pos, ln_over = j, 1             # 가운뎃점으로 하향 오독 → 글머리로 환원
        else:
            # 통째 소실 → 항목 앞 빈 구간 중 **수식 밖**인 가장 이른 자리에 되살린다.
            # ($ 짝 안쪽에 넣으면 수식이 깨진다 — MinerU가 셀 안 수식을 $…$로 감싼다.)
            pos, ln_over = start, 0
            for k in range(j + 1, start + 1):
                if html.count("$", 0, k) % 2 == 0:
                    pos = k
                    break
        if pos in ops:
            return html                     # 두 항목이 같은 자리를 가리킨다 → 신뢰 불가
        ops[pos] = ln_over
    if not ops:
        return html
    out = html
    for pos in sorted(ops, reverse=True):
        out = out[:pos] + "•" + out[pos + ops[pos]:]
    return out


# ── 표 셀 글자 교정 ──────────────────────────────────────────────────────────
# 표는 _NATIVE_TEXT_TYPES에서 빠져 있어(HTML 구조를 평문으로 덮으면 표가 깨진다)
# MinerU OCR 글자가 그대로 남는다. 실측(코퍼스 1131p·표 384개)에서 남은 오독의
# 사실상 전부가 여기 있었다: 흔성반(혼성반)·건년방(건넌방)·상총(상충)·디담돌(디딤돌)·
# 쇠큐(쇄국)·카유웨이(캉유웨이)·설탐(설탕)·이미노산(아미노산) 등.
#
# 셀을 레이어 값으로 **통째 교체하지 않는다.** 레이어는 시각적 줄 단위라 셀 경계에서
# 잘리고(`빛(400~700nm의 가시광선)` → `빛(400~700nm의 가시`), 밑줄 마커·PUA 잔재가
# 섞여 들어온다. 통째 교체하면 글자를 고치는 대신 문장을 잘라먹는다.
# 그래서 **한글 음절 ↔ 한글 음절, 같은 길이** 치환만 적용한다:
#   - 길이가 바뀌는 편집(삽입·삭제)은 전부 버린다 → 잘림·중복이 반영될 수 없다.
#   - 기호·숫자·로마자는 건드리지 않는다. 물결표(~ vs ∼)·붙임표(– vs -)는 레이어 쪽이
#     원문 글리프지만, 그건 특수기호 축이 따로 규정으로 다루는 영역이라 여기서 손대면
#     담당이 섞인다.
_CELL_RE = re.compile(r"(<t[dh][^>]*>)(.*?)(</t[dh]>)", re.IGNORECASE | re.DOTALL)
_HANGUL_RUN_RE = re.compile(r"^[가-힣]+$")
_CELL_SIM_MIN = 0.80      # 셀이 레이어에서 이만큼도 안 닮은 자리밖에 없으면 대조 실패
_CELL_SUB_MAX = 4         # 한 번에 이보다 길게 바꾸지 않는다(문장 교체 방지)


def _best_layer_window(cell: str, layer_ns: str) -> tuple[float, int]:
    """레이어(공백 제거)에서 cell과 가장 닮은 **같은 길이** 구간의 (유사도, 시작위치)."""
    n = len(cell)
    if n == 0 or n > len(layer_ns):
        return 0.0, -1
    probe = cell[:4]
    starts: list[int] = []
    if len(probe) >= 3:
        starts = [m.start() for m in re.finditer(re.escape(probe), layer_ns)]
    if not starts:
        starts = list(range(0, len(layer_ns) - n + 1, max(1, n // 4)))
    best, best_pos = 0.0, -1
    for s in starts:
        seg = layer_ns[s:s + n]
        if not seg:
            continue
        r = SequenceMatcher(None, cell, seg, autojunk=False).ratio()
        if r > best:
            best, best_pos = r, s
    return best, best_pos


def _hangul_substitutions(cell: str, window: str) -> list[tuple[int, int, str]]:
    """(셀 내 오프셋, 길이, 대체문자열). 한글↔한글 동일 길이 치환만."""
    out: list[tuple[int, int, str]] = []
    for tag, i1, i2, j1, j2 in SequenceMatcher(None, cell, window,
                                               autojunk=False).get_opcodes():
        if tag != "replace":
            continue
        a, b = cell[i1:i2], window[j1:j2]
        if len(a) != len(b) or len(a) > _CELL_SUB_MAX:
            continue
        if not (_HANGUL_RUN_RE.match(a) and _HANGUL_RUN_RE.match(b)):
            continue
        out.append((i1, i2 - i1, b))
    return out


# ── 괘선 없는 '표'는 표가 아니다 (QA 9번, 2026-08-08) ────────────────────────
# MinerU의 표 모델은 **글이 격자처럼 늘어선 쪽**을 통째로 표로 싼다. 대표 QA 실측:
# 2026학년도 수능 수학 문제지 2쪽이 각각 쪽 본문 전체(폭 80%·높이 75%)가 <table> 한
# 덩이였고, 문항 하나가 <td> 하나였다. 그러면 32칸 표 테두리와 두 칸 셀 구분이 붙어
# 초안이 통째로 망가진다.
#
# 가르는 신호는 대표님 말 그대로 **가로 괘선**이다(실측):
#   dev-2027 200쪽의 표 104개 — 가로 괘선 최소 2 · 중앙값 5 (하나도 예외 없음)
#   대표 QA가 올린 원본(2026학년도 수능 수학 문제지)의 그 bbox — 가로 괘선 1
# ⚠ 판단할 근거가 없는 두 경우는 **손대지 않는다**(표로 둔다):
#     · 쪽에 벡터 선이 아예 없다(스캔본)
#     · 그 자리가 래스터 이미지로 덮여 있다 — 표를 그림으로 붙인 쪽(언어 p223 실측).
#       괘선이 화소 안에 있어 벡터로는 0으로 세어져, 진짜 표를 내릴 뻔했다.
# ⚠ MinerU가 차트에서 뽑아 준 데이터 표(_chart_data_table)는 원래 괘선이 없으므로 제외 —
#   이 판정은 MinerU가 직접 "table"이라고 한 요소에만 건다.
_RULE_FLAT = 1.5      # 이보다 얇으면 '선'
_RULE_PAD = 4.0       # bbox 여유(pt) — 테두리는 bbox에 딱 붙거나 살짝 밖이다
_RULE_SPAN = 0.4      # 표 폭의 이 비율 이상 뻗어야 괘선(밑줄 토막·화살표 제외)
_RULE_MIN_H = 2       # 가로 괘선이 이보다 적으면 표가 아니다
_RULE_IMG_COVER = 0.6  # 래스터 이미지가 이 비율 이상 덮으면 벡터로 판단 불가


def _h_rules(fitz_page: fitz.Page, bbox: list[float]) -> int | None:
    """bbox 안 가로 괘선 수. 벡터로 판단할 수 없으면 None."""
    w, h = fitz_page.rect.width, fitz_page.rect.height
    r = fitz.Rect(bbox[0] / 1000 * w, bbox[1] / 1000 * h,
                  bbox[2] / 1000 * w, bbox[3] / 1000 * h)
    rot = fitz_page.rotation_matrix
    if r.get_area() > 0:
        for blk in fitz_page.get_text("rawdict").get("blocks", []):
            if blk.get("type") != 1:        # 1 = 이미지 블록
                continue
            ib = fitz.Rect(blk.get("bbox") or (0, 0, 0, 0)) * rot
            ib.normalize()
            if (ib & r).get_area() >= r.get_area() * _RULE_IMG_COVER:
                return None
    segs: list[tuple[float, float, float, float]] = []
    for g in fitz_page.get_drawings():
        for it in g["items"]:
            if it[0] == "l":
                p1, p2 = it[1] * rot, it[2] * rot
                segs.append((min(p1.x, p2.x), min(p1.y, p2.y),
                             max(p1.x, p2.x), max(p1.y, p2.y)))
            elif it[0] == "re":
                q = fitz.Rect(it[1]) * rot
                q.normalize()
                # 얇은 사각형은 그 자체가 선, 두꺼우면 위·아래 변이 행 구분선(음영 머리행)
                segs += ([(q.x0, q.y0, q.x1, q.y1)] if min(q.width, q.height) <= _RULE_FLAT
                         else [(q.x0, q.y0, q.x1, q.y0), (q.x0, q.y1, q.x1, q.y1)])
    if not segs:
        return None
    bx0, by0 = r.x0 - _RULE_PAD, r.y0 - _RULE_PAD
    bx1, by1 = r.x1 + _RULE_PAD, r.y1 + _RULE_PAD
    # ⚠ PyMuPDF의 Rect.intersects()는 높이 0인 사각형(=가로선)을 '빈' 것으로 보고 False를
    #   낸다. 그래서 겹침은 사각형이 아니라 좌표로 직접 따진다.
    spans: dict[int, float] = {}
    for x0, y0, x1, y1 in segs:
        if y1 - y0 > _RULE_FLAT or x1 < bx0 or x0 > bx1 or y1 < by0 or y0 > by1:
            continue
        cut = min(x1, bx1) - max(x0, bx0)
        if cut > 1:                       # 조각난 괘선은 y가 같으면 하나로 합산한다
            k = round((y0 + y1) / 2)
            spans[k] = spans.get(k, 0.0) + cut
    need = max(r.width, 1.0) * _RULE_SPAN
    return sum(1 for length in spans.values() if length >= need)


# ── 테두리뿐인 '표'는 글상자다 (F15, 2026-08-26) ─────────────────────────────
# 위 괘선 판정은 **가로선 2개**를 표의 조건으로 삼는데, 글상자는 제 위·아래 테두리만으로
# 그 2개를 채운다. 그래서 "글상자 안 문항 + 그 아래 보기"가 표로 남았다(대표 시연 4쪽 지적).
# 가르는 신호는 **속 구분선**이다 — 표는 속에 행이나 열을 가르는 선이 있고, 글상자는 없다.
#   실측 2027 dev+val 1,746쪽·표 924개: 속 구분선이 하나도 없는 표 16개.
#   그 16개 중 답 모음 표(‘Level 1 기초 연습’ 형식, 짧은 셀 여러 행)는 진짜 표라 살려야 한다.
#   → 셀이 줄글이거나(가장 긴 셀 > _COL_CELL_LEN) 한 행뿐일 때만 강등한다.
#   그러면 4개가 강등된다: 수학 (가)(나) 조건 상자·사료 인용 상자·조약 조문 상자·설문지 양식.
#   (설문지는 「제작 지침」 §6.6.3 양식이라 어차피 글상자로 적는다.)
_BOX_EDGE = 6.0          # bbox 변에서 이 안쪽 선은 테두리로 본다(pt)
_BOX_COVER = 0.9         # 글상자 사각형이 표 자리를 이만큼 덮으면 '상자 안'


def _inner_separators(fitz_page: fitz.Page, bbox: list[float]) -> tuple[int, int]:
    """bbox **속**(테두리 제외) 가로·세로 구분선 수."""
    w, h = fitz_page.rect.width, fitz_page.rect.height
    r = fitz.Rect(bbox[0] / 1000 * w, bbox[1] / 1000 * h,
                  bbox[2] / 1000 * w, bbox[3] / 1000 * h)
    rot = fitz_page.rotation_matrix
    segs: list[tuple[float, float, float, float]] = []
    for g in fitz_page.get_drawings():
        for it in g["items"]:
            if it[0] == "l":
                p1, p2 = it[1] * rot, it[2] * rot
                segs.append((min(p1.x, p2.x), min(p1.y, p2.y),
                             max(p1.x, p2.x), max(p1.y, p2.y)))
            elif it[0] == "re":
                q = fitz.Rect(it[1]) * rot
                q.normalize()
                segs += ([(q.x0, q.y0, q.x1, q.y1)] if min(q.width, q.height) <= _RULE_FLAT
                         else [(q.x0, q.y0, q.x1, q.y0), (q.x0, q.y1, q.x1, q.y1)])
    bx0, by0 = r.x0 - _RULE_PAD, r.y0 - _RULE_PAD
    bx1, by1 = r.x1 + _RULE_PAD, r.y1 + _RULE_PAD
    hs: dict[int, float] = {}
    vs: dict[int, float] = {}
    for x0, y0, x1, y1 in segs:
        if x1 < bx0 or x0 > bx1 or y1 < by0 or y0 > by1:
            continue
        if y1 - y0 <= _RULE_FLAT:                       # 가로선
            cut = min(x1, bx1) - max(x0, bx0)
            if cut > 1:
                k = round((y0 + y1) / 2)
                hs[k] = hs.get(k, 0.0) + cut
        elif x1 - x0 <= _RULE_FLAT:                     # 세로선
            cut = min(y1, by1) - max(y0, by0)
            if cut > 1:
                k = round((x0 + x1) / 2)
                vs[k] = vs.get(k, 0.0) + cut
    n_h = sum(1 for y, ln in hs.items()
              if ln >= max(r.width, 1.0) * _RULE_SPAN
              and abs(y - r.y0) > _BOX_EDGE and abs(y - r.y1) > _BOX_EDGE)
    n_v = sum(1 for x, ln in vs.items()
              if ln >= max(r.height, 1.0) * _RULE_SPAN
              and abs(x - r.x0) > _BOX_EDGE and abs(x - r.x1) > _BOX_EDGE)
    return n_h, n_v


def _prose_grid(html: str) -> bool:
    """격자가 아니라 **줄글 덩이**인가 — 셀 하나가 길거나 행이 하나뿐인가."""
    rows = len(_TR_RE.findall(html or ""))
    cells = [re.sub(r"<[^>]+>", "", m[1]).strip() for m in _TD_RE.findall(html or "")]
    if not cells:
        return False
    return rows <= 1 or max(len(c) for c in cells) > _COL_CELL_LEN


def _is_boxed_prose(fitz_page: fitz.Page, bbox: list[float], html: str,
                    box_rects_pt: list) -> bool:
    """그 '표'가 실은 글상자에 든 줄글인가 (위 절 주석 참조)."""
    if not box_rects_pt or not _prose_grid(html):
        return False
    w, h = fitz_page.rect.width, fitz_page.rect.height
    r = fitz.Rect(bbox[0] / 1000 * w, bbox[1] / 1000 * h,
                  bbox[2] / 1000 * w, bbox[3] / 1000 * h)
    if r.get_area() <= 0:
        return False
    if not any((r & q).get_area() > r.get_area() * _BOX_COVER for q in box_rects_pt):
        return False
    return _inner_separators(fitz_page, bbox) == (0, 0)


_TR_RE = re.compile(r"<tr[^>]*>(.*?)</tr>", re.S | re.I)
_TD_RE = re.compile(r"<t[dh]([^>]*)>(.*?)</t[dh]>", re.S | re.I)
_COLSPAN_RE = re.compile(r"colspan\s*=\s*[\"']?(\d+)", re.I)


# 셀 글자 중앙값이 이보다 길면 '표의 셀'이 아니라 **단에 흐르는 글**로 본다
_COL_CELL_LEN = 40


def _table_to_text(html: str) -> str:
    """괘선 없는 '표' HTML → 평문. 격자 모양에 따라 읽는 방향이 다르다.

    · 셀이 긴 글이면 **다단 조판**이다 → 단 순서(세로)로 읽는다. 수능 문제지는 한 <tr>이
      [1번 문항, 3번 문항]이라 행으로 읽으면 1·3·2·4가 된다(단으로 읽어야 1·2·3·4).
      다단 쪽을 단 순서로 읽는 판단은 pipeline._reorder_columns에도 이미 있다.
    · 셀이 짧으면 **선택지 표**다(① 뜯기 / 치기) → 행이 곧 인쇄 줄이므로 행 순서로 읽고
      한 행은 한 줄로 두 칸씩 띄어 잇는다(「점자 도서 제작 지침」 3장 3절 4)(3)①).
    """
    grid: list[list[tuple[int, str]]] = []
    for tr in _TR_RE.findall(html):
        row: list[tuple[int, str]] = []
        col = 0
        for attr, cell in _TD_RE.findall(tr):
            row.append((col, re.sub(r"<[^>]+>", "", cell).strip()))
            m = _COLSPAN_RE.search(attr)
            col += int(m.group(1)) if m else 1
        if row:
            grid.append(row)
    if not grid:
        return re.sub(r"<[^>]+>", " ", html).strip()
    lens = sorted(len(t) for row in grid for _, t in row if t)
    ncol = max(row[-1][0] + 1 for row in grid)
    if ncol > 1 and lens and lens[len(lens) // 2] >= _COL_CELL_LEN:
        return "\n".join(txt for c in range(ncol) for row in grid
                         for col, txt in row if col == c and txt)
    return "\n".join("  ".join(t for _, t in row if t) for row in grid
                     if any(t for _, t in row))


def _correct_table_cells(fitz_page: fitz.Page, bbox: list[float], html: str) -> str:
    """표 셀의 한글 오독을 텍스트 레이어를 근거로 고친다. 구조(HTML)는 건드리지 않는다.

    ★ 부분 교정 금지(_restore_table_bullets와 같은 원칙): 내용 있는 셀 하나라도 레이어에서
    못 찾으면 그 표는 통째로 손대지 않는다. 못 찾는다는 건 레이어와 표가 다른 것을
    가리킨다는 뜻이라, 찾은 셀의 교정도 근거가 없다.
    """
    if not html or not bbox:
        return html
    layer = _native_text_spaced(fitz_page, bbox)
    if not layer or _layer_untrustworthy(layer):
        return html
    # 레이어에는 우리가 붙이는 인라인 태그(<!강조> 등)가 들어 있다 — 대조 전에 걷어낸다.
    layer_ns = re.sub(r"\s+", "", re.sub(r"<!/?[^>]*>", "", layer))
    if not layer_ns:
        return html

    edits: list[tuple[int, int, str]] = []
    for m in _CELL_RE.finditer(html):
        inner = m.group(2)
        # 대조본(태그·공백·수식 구분자 $ 제거) ↔ 원문 인덱스 대응
        ns_chars: list[str] = []
        ns_idx: list[int] = []
        i = 0
        while i < len(inner):
            ch = inner[i]
            if ch == "<":                       # 셀 안 중첩 태그는 건너뛴다
                j = inner.find(">", i)
                if j < 0:
                    break
                i = j + 1
                continue
            if ch not in _BULLET_SKIP_CHARS:
                ns_chars.append(ch)
                ns_idx.append(i)
            i += 1
        cell = "".join(ns_chars)
        if not cell:
            continue                            # 빈 셀은 대조 대상이 아니다
        sim, pos = _best_layer_window(cell, layer_ns)
        if sim < _CELL_SIM_MIN:
            return html                         # 한 셀이라도 실패 → 이 표는 포기
        if sim >= 1.0:
            continue
        for off, ln, repl in _hangul_substitutions(cell, layer_ns[pos:pos + len(cell)]):
            src = ns_idx[off:off + ln]
            # 원문에서도 연속이어야 한다 — 중간에 태그·공백이 끼어 있으면 건드리지 않는다.
            if src != list(range(src[0], src[0] + ln)):
                continue
            edits.append((m.start(2) + src[0], ln, repl))

    if not edits:
        return html
    out = html
    for pos, ln, repl in sorted(edits, reverse=True):
        out = out[:pos] + repl + out[pos + ln:]
    return out


def _pua_ratio(s: str) -> float:
    if not s:
        return 0.0
    pua = sum(1 for ch in s if 0xE000 <= ord(ch) <= 0xF8FF)
    return pua / len(s)


def _layer_untrustworthy(s: str) -> bool:
    """텍스트 레이어를 믿으면 안 되는가 — PUA **또는** 글꼴 매핑 거짓말.

    ★ 2026-08-09 — 종전엔 PUA 비율만 봤다. 그런데 코퍼스 1,251쪽 중 **753쪽(60.2%)**은
      PUA가 0%인데도 글꼴이 거짓말을 한다: `/Encoding`과 `/ToUnicode`가 실제로 그려지는
      글리프와 **다른 문자**를 가리킨다(수학2는 147/147 전량). 예: STkboNA의 코드 0x02는
      스스로를 `∂`(U+2202)라 부르는데 실제로 그려지는 건 근호 `√`다.
      그래서 PUA만 보면 이 쪽들이 전부 "믿을 만함"으로 통과해, 깨진 텍스트가 멀쩡한
      MinerU OCR을 덮어쓴다.

      판정은 `pdf_analyzer.mangled_glyph_chars`가 한다 — "교과서에 절대 안 나오는
      코드포인트"(± ™ £ ¥ ¢ § œ æ ç ß ﬂ Ã ´ ¨ 등)를 신호로 쓰고 전수 1,251쪽에서
      **오탐 0**이었다. 폰트 이름·영폭 글리프·`/Widths` 퇴화도는 전부 분리에 실패해 기각됐다.
    """
    if not s:
        return False
    if _pua_ratio(s) > _PUA_RATIO_MAX:
        return True
    from app.ai.preprocessor.pdf_analyzer import mangled_glyph_chars
    layer_bad, _symbol_bad = mangled_glyph_chars(s)
    return bool(layer_bad)          # 조판을 무너뜨리는 종류만 — 기호 하나짜리는 통과시킨다


def _native_text_spaced(fitz_page: fitz.Page, bbox: list[float]) -> str:
    """bbox 안의 텍스트를 어절 경계 복원해서 뽑는다.

    ⚠ get_text("text")를 그대로 쓰면 안 된다 — 교과서 PDF 다수가 공백 글리프 없이 글자
    위치(커닝)로만 어절을 띄우므로 "명중기왕수인이성리학의"처럼 붙어 나온다. 점자는 띄어쓰기가
    규칙이라 그대로 점역하면 정답과 크게 어긋난다(세계사 p086 실측: cell_ns 0.87→0.39).
    pdf_analyzer의 글자 간격 기반 복원(_page_text_blocks_spaced)을 재사용한다.
    """
    from app.ai.preprocessor.pdf_analyzer import (
        _line_text_with_word_gaps, rows_to_text, underline_rects)

    w, h = fitz_page.rect.width, fitz_page.rect.height
    uls = underline_rects(fitz_page)   # 밑줄(드러냄표, 규정 제56항) — 벡터 선으로만 존재
    rect = fitz.Rect(bbox[0] / 1000 * w, bbox[1] / 1000 * h,
                     bbox[2] / 1000 * w, bbox[3] / 1000 * h)
    # ⚠ 회전된 페이지(교과서 PDF에 흔함 — 언어 영역은 270°): rawdict의 줄 bbox는 회전 전
    # 좌표계라 MinerU가 쓰는 렌더(표시) 좌표와 어긋난다. rotation_matrix로 표시 좌표로 옮긴다.
    # (이걸 빠뜨리면 회전 페이지에서 매칭이 전부 실패해 OCR 오탈자가 그대로 남는다.)
    rot = fitz_page.rotation_matrix
    lines: list[tuple] = []
    for blk in fitz_page.get_text("rawdict").get("blocks", []):
        if blk.get("type") != 0:      # 0 = 텍스트 블록
            continue
        for ln in blk.get("lines", []):
            lb = fitz.Rect(ln.get("bbox") or (0, 0, 0, 0)) * rot
            # 줄 단위로 고른다(블록 단위는 다단 레이아웃에서 요소 경계와 어긋난다).
            # 줄 면적의 과반이 요소 bbox 안에 들어와야 채택 — 이웃 단 글자 혼입 방지.
            if lb.get_area() <= 0 or (lb & rect).get_area() / lb.get_area() < 0.6:
                continue
            t = _line_text_with_word_gaps(ln, rot, uls)
            if t:
                # ★ 같은 인쇄 줄이 여러 line으로 쪼개진 것(정답표·선택지)은 rows_to_text가
                #   한 줄로 이어 두 칸을 띈다 — 지침 3장 3절 4)(3)① (QA S4)
                lines.append((lb, t))
    return rows_to_text(lines)


def _native_override(fitz_page: fitz.Page, bbox: list[float], mineru_text: str) -> str | None:
    """텍스트 레이어로 대체할 값. 못 믿으면 None(= MinerU 결과 유지)."""
    native = _native_text_spaced(fitz_page, bbox)
    if not native or _layer_untrustworthy(native):
        return None
    base = (mineru_text or "").strip()
    if not base:
        return native
    # 같은 블록을 가리키는지 확인 — clip은 겹치는 글리프를 다 가져오므로 bbox가 어긋나면
    # 옆 블록 글자가 섞여 들어온다. 그런 경우는 MinerU 쪽을 그대로 둔다.
    from difflib import SequenceMatcher
    a = "".join(native.split())
    b = "".join(base.split())
    if SequenceMatcher(None, a, b).ratio() < _SIM_MIN:
        return None
    return native


_MD_SEP_RE = re.compile(r"^\s*\|?[\s:|-]+\|?\s*$")


def _chart_data_table(md: str) -> str:
    """MinerU가 차트에서 뽑은 markdown 표 → 표 점역이 먹는 '|' 격자. 표가 아니면 "".

    MinerU는 그래프(막대·원·꺾은선)를 읽어 `| Category | Value |` 형태의 데이터 표를 낸다.
    정답 도서도 그래프를 이렇게 전사하므로(수치가 본문에 살아 있어야 함) 그대로 표로 넘긴다.
    """
    if not md or "|" not in md:
        return ""
    if "mermaid" in md or "-->" in md:
        return ""   # 흐름도(mermaid)는 라벨에 '|'를 쓴다 — 표로 오인하면 도식이 깨진다
    rows: list[str] = []
    for ln in md.splitlines():
        s = ln.strip()
        if not s or "|" not in s or _MD_SEP_RE.match(s):   # markdown 구분선(|---|) 제거
            continue
        cells = [c.strip() for c in s.strip("|").split("|")]
        if any(cells):
            rows.append(" | ".join(cells))
    return "\n".join(rows) if len(rows) >= 2 else ""


# mermaid 노드 선언: A["영국"] · B(청) — 따옴표형을 먼저 잡는다("청 (광저우)"처럼 괄호가
# 라벨 안에 들어 있어 따옴표 없이 자르면 잘린다).
_MM_NODE_Q = re.compile(r'(\w+)\s*[\[({]\s*"([^"]*)"\s*[\])}]')
_MM_NODE_U = re.compile(r'(\w+)\s*[\[({]\s*([^"\])}]+?)\s*[\])}]')
_MM_ARROW = re.compile(r"(?:-->|---|==>|-\.->)")
_MM_EDGE_RE = re.compile(r"(\w+)\s*(?:-->|---|==>|-\.->)\s*(?:\|([^|]*)\|)?\s*(\w+)")
_HANGUL_RE = re.compile(r"[가-힣]")


def _flowchart_lines(md: str) -> str:
    """MinerU가 흐름도에서 뽑은 mermaid → 정답 도서식 화살표 줄.

    정답 표기: "영국-은-→청"(라벨 있는 간선) · "영국→청"(라벨 없음).
    MinerU가 도식을 이미 구조로 읽어 주므로 캡셔닝 없이 그대로 옮긴다(rule-based).
    """
    if not md or ("mermaid" not in md and not _MM_ARROW.search(md)):
        return ""
    names: dict[str, str] = {}
    for k, v in _MM_NODE_U.findall(md):
        names[k] = v.strip()
    for k, v in _MM_NODE_Q.findall(md):      # 따옴표형이 우선
        names[k] = v.strip()
    # 노드 선언을 식별자만 남기고 지운다 — 안 지우면 `A["영국"] --> B` 의 첫 간선이 안 잡힌다
    stripped = _MM_NODE_Q.sub(r"\1", md)
    stripped = _MM_NODE_U.sub(r"\1", stripped)
    lines: list[str] = []
    for src, label, dst in _MM_EDGE_RE.findall(stripped):
        a, b = names.get(src, src), names.get(dst, dst)
        lab = (label or "").strip()
        lines.append(f"{a}-{lab}-→{b}" if lab else f"{a}→{b}")
    text = "\n".join(lines)
    return text if _HANGUL_RE.search(text) else ""



# ── 안 그려지는 글자 버리기(C006) ────────────────────────────────────────────
# 크롭으로 만든 PDF 는 **잘려 나간 바깥 글자를 텍스트 레이어에 그대로 갖고 있다.**
# 화면에는 안 그려지는데 추출기는 읽는다. 그래서 3쪽 글이 4쪽 요소로 섞여 나온다.
#
# ★ 원인 실측(시연문서 p07): 같은 글이 **두 벌** 있다.
#     '•매체 자료의 왜곡 여부 확인'  [263,741] 잉크 0.00 (안 그려짐)
#                                    [269,709] 잉크 0.21 (그려짐)
#   Form XObject 프레임 rect 로는 못 가른다 — 프레임 bbox 는 PDF 좌표(하단 원점)라
#   위아래가 뒤집히고, 애초에 지면이 프레임 안에서 옮겨 앉으며 바깥 글자도 같이
#   변환돼 프레임 **안쪽** 좌표로 들어온다. 그러니 프레임이 아니라
#   **실제로 그려졌는지**로 판정한다.
#
# ⚠ 멀쩡한 글을 버리면 훨씬 나쁘다. 그래서 **흰색 아닌 화소가 하나도 없을 때만** 버린다.
#   글자가 있으면 안티에일리어싱만으로도 회색 화소가 남고, 흰 글자면 바탕이 어둡다.
#   음영 상자·테두리가 걸쳐도 화소가 남아 그냥 살린다(놓치는 쪽이 안전하다).
_INK_DPI = 100                    # 쪽당 한 번만 렌더한다
_INK_WHITE = 250                  # 이보다 밝으면 아무것도 안 그려진 화소로 본다
# 글자 요소만 본다. 그림·표·시각자료는 안 건드린다 — 요소째 사라지면 학생은 거기
# 무엇이 있었다는 사실조차 모른다(불변규칙 1 빈 결과 금지).
_UNPAINTED_TYPES = {"text", "title", "list_item", "caption",
                    "footnote", "sidebar", "header_footer", "page_number"}


def _is_painted(pix: "fitz.Pixmap", bb: list[float]) -> bool:
    """0~1000 bbox 자리에 흰색 아닌 화소가 하나라도 있나."""
    x0 = max(0, int(bb[0] / 1000 * pix.width))
    x1 = min(pix.width, int(round(bb[2] / 1000 * pix.width)))
    y0 = max(0, int(bb[1] / 1000 * pix.height))
    y1 = min(pix.height, int(round(bb[3] / 1000 * pix.height)))
    if x1 <= x0 or y1 <= y0:
        return True                        # 잴 수 없으면 살린다
    s, n, stride = pix.samples, pix.n, pix.stride
    for y in range(y0, y1):
        row = s[y * stride + x0 * n: y * stride + x1 * n]
        if row and min(row) < _INK_WHITE:  # 바이트 min 은 C 속도다
            return True
    return False


def _drop_unpainted(elements: list[dict], fitz_page: fitz.Page,
                    page_no: int) -> list[dict]:
    """지면에 실제로 그려지지 않은 글자 요소를 버린다. 위 주석의 판정을 쓴다."""
    # ★ 회전 지면도 그대로 본다. 한때 여기서 회전 지면을 통째로 건너뛰었는데
    #   (270° 478쪽에서 오검출 410건이 나온다고 봤다) 그건 **재는 쪽이 틀린 값**이었다 —
    #   경계 파일(*_txt_result.json)을 재구성한 하네스로 쟀기 때문이다. 경계 파일은
    #   파이프라인 **산출물**이고 bbox 좌표계가 파일마다 갈린다(result_builder.build 의
    #   bbox_out 분기). 여기 들어오는 bbox 는 MinerU 원본 content_list 값이고, 그걸로
    #   다시 재면 회전 지면 텍스트 요소 569개 중 **569개(100%)**가 제자리에 있다
    #   (보정을 넣으면 오히려 69%로 떨어진다). 코퍼스 전수 재측정도 회전 지면 6,854요소
    #   오검출 0 이다. **보정도 게이팅도 필요 없다.**
    try:
        pix = fitz_page.get_pixmap(dpi=_INK_DPI)
    except Exception as exc:               # 렌더가 안 되면 아무것도 안 버린다
        logger.warning("page %d: 렌더 실패로 안 그려진 글자 판정을 건너뛴다 (%s)",
                       page_no, exc)
        return elements
    kept, dropped = [], []
    for el in elements:
        bb = el.get("bbox")
        if (el.get("type") in _UNPAINTED_TYPES and (el.get("content") or "").strip()
                and isinstance(bb, list) and len(bb) == 4
                and not _is_painted(pix, bb)):
            dropped.append(el)
            continue
        kept.append(el)
    if dropped:
        logger.info("page %d: 안 그려진 글자 요소 %d개 버림 (예: %r)", page_no,
                    len(dropped), (dropped[0].get("content") or "")[:30])
        for i, el in enumerate(kept):
            el["reading_order"] = i
    return kept


def run(
    pdf_path: str,
    page_no: int,
    job_id: str,
    extraction_method: str,
    mineru_cache_dir: str | None = None,
    debug: bool = False,
    timeout: float | None = None,
) -> list[dict]:
    """
    pdf_path: 전체 PDF 경로
    page_no: 1-indexed
    job_id: 저장 경로 식별자
    extraction_method: 'TEXT_NATIVE' | 'OCR'
    mineru_cache_dir: 이미 mineru 결과가 있으면 재사용 (None이면 새로 실행)
    debug: True이면 merged_layout.json을 test/results/page_{no:03d}/에 저장
    timeout: MinerU 서브프로세스 타임아웃(초). None이면 무제한(오프라인 러너 호환)

    반환: merged_layout (list[dict])
    """
    pdf_path = Path(pdf_path)
    base = Path("storage") / "jobs" / job_id / "temp" / f"page_{page_no:03d}"

    # proto 계약상 pdf_data는 '단일 페이지' PDF(BE가 페이지마다 1장씩 전송). page_no는
    # 원본 문서 페이지 번호(저장경로용)이므로 도착 PDF 인덱스로 그대로 쓰면 단일 페이지에서
    # 범위 초과. 페이지 수에 맞게 클램프(단일=0, 멀티=page_no-1).
    with fitz.open(str(pdf_path)) as _d:
        page_idx = max(0, min(page_no - 1, _d.page_count - 1))

    raw_dir = Path(mineru_cache_dir) if mineru_cache_dir else base / "mineru_raw"
    if not list(raw_dir.rglob("*_content_list.json")):
        raw_dir.mkdir(parents=True, exist_ok=True)
        for _attempt in range(1 + _MINERU_RETRIES):
            try:
                _run_mineru(pdf_path, raw_dir, page_idx, timeout=timeout)
                if _attempt:
                    logger.warning("MinerU %d번째 시도에 성공 (page_idx=%d)", _attempt + 1, page_idx)
                break
            except MineruTimeout:
                raise                       # 예산을 이미 다 썼다 — 다시 부르면 두 배다
            except RuntimeError as exc:     # 비결정 실패 — 한 번 더 불러 본다
                if _attempt >= _MINERU_RETRIES:
                    raise
                logger.warning("MinerU %d번째 시도 실패, 다시 부른다 (page_idx=%d): %s",
                               _attempt + 1, page_idx, exc)
                shutil.rmtree(raw_dir, ignore_errors=True)
                raw_dir.mkdir(parents=True, exist_ok=True)
        _cleanup_mineru_output(raw_dir)
        _flatten_mineru_output(raw_dir)

    cl_path = _find_content_list(raw_dir)
    with open(cl_path, encoding="utf-8") as f:
        content_list = json.load(f)

    images_dir = raw_dir / "images"
    images_dir.mkdir(exist_ok=True)

    # 이미지 이름 매핑 (hash_stem → element_id): 캐시 재실행 시에도 동일 element_id 유지
    mapping_file = images_dir / "mapping.json"
    hash_to_eid: dict[str, str] = {}
    if mapping_file.exists():
        hash_to_eid = json.loads(mapping_file.read_text(encoding="utf-8"))

    # PDF 페이지 크기 (bbox 픽셀 변환용, 2x 렌더 기준)
    doc = fitz.open(str(pdf_path))
    fitz_page = doc[page_idx]
    rect = fitz_page.rect
    img_w = int(rect.width * 2)
    img_h = int(rect.height * 2)
    page_img_info = fitz_page.get_image_info()   # 재크롭 DPI 상한 판정용, 쪽당 1회

    merged_layout = []
    order = 1

    # 글상자 사각형은 쪽당 한 번만 찾는다(표 판정에만 쓰이므로 표가 있을 때 처음 찾는다).
    _box_cache: list = []

    def _page_box_rects() -> list:
        if not _box_cache:
            try:
                from app.ai.preprocessor.pdf_analyzer import box_rects
                _box_cache.append(box_rects(fitz_page))
            except Exception:  # noqa: BLE001 — 상자를 못 찾으면 종전대로 표로 둔다
                _box_cache.append([])
        return _box_cache[0]

    for item in content_list:
        item_type = item.get("type", "text")
        mapped_type = TYPE_MAP.get(item_type, "text")
        # ★ MinerU 는 `header` / `footer` / `page_number` 를 나눠서 준다. 위 표에 `footer` 가
        #   없어 기본값 `"text"` 로 떨어지고 **그 구분이 여기서 사라진다**(원장 C-86).
        #   타입을 `header_footer` 로 바꾸지는 **않는다** — 실측하면 출력이 한 글자도 안 바뀌고
        #   (`_is_running_foot` 962건 전원 통과 · `header_footer` 도 본문으로 조판된다),
        #   꼬리말을 적을지 말지는 **규정↔관행이 갈려 자문 대기**다(§2.1.2 는 적으라 하는데
        #   gold 는 91.4%를 안 적는다 · 25,382셀). 그래서 **판정은 미루고 신호만 남긴다.**
        raw_footer = item_type == "footer"
        if mapped_type == "image" and item.get("sub_type") == "flowchart":
            mapped_type = "chart_graph"
        # 인쇄 캡션이 있는 시각자료는 생성 설명(GPT-4o+점역자주) 대신 인쇄 캡션을 그대로
        # plain text(caption)로 방출한다 — 정답 점역 컨벤션 정렬(rule-based vs generation 분리).
        # 캡션 없는 도식만 생성 경로로 남긴다.
        # ★ 단, MinerU가 도식/그래프에서 데이터를 뽑아 준 경우에는 캡션으로 갈아치우지 않는다.
        #   ("(가)" 캡션 하나만 남고 삼각무역 도식이 통째로 사라지던 버그 — 세계사 p160)
        printed_cap = item.get("image_caption")
        if isinstance(printed_cap, list):
            printed_cap = " ".join(x for x in printed_cap if x)
        forced_caption = (printed_cap or "").strip() if mapped_type in ("image", "chart_graph", "cartoon") else ""
        has_data = bool(_chart_data_table(item.get("content", ""))
                        or _flowchart_lines(item.get("content", "")))
        if forced_caption and not has_data:
            mapped_type = "caption"
        bb = item.get("bbox")
        if bb is None:
            continue

        element_id = str(uuid.uuid4())
        img_path_rel = item.get("img_path")
        image_path = None

        if img_path_rel:
            # flatten 후 이미지는 raw_dir/images/{hash}.jpg 에 있음
            hash_stem = Path(img_path_rel).stem
            src = images_dir / Path(img_path_rel).name
            if src.exists():
                dst = images_dir / f"{element_id}.jpg"
                shutil.move(str(src), str(dst))
                hash_to_eid[hash_stem] = element_id
                image_path = str(dst)
            elif hash_stem in hash_to_eid:
                # 캐시 재실행: 이미 이름 변경된 파일 재사용
                element_id = hash_to_eid[hash_stem]
                existing = images_dir / f"{element_id}.jpg"
                if existing.exists():
                    image_path = str(existing)
            if item_type == "table":
                content = item.get("table_body", "")
            elif mapped_type in ("image", "chart_graph", "cartoon"):
                # ★ MinerU가 차트에서 데이터 표를 뽑아 주면(markdown) 그걸 쓴다 — 정답 도서도
                #   그래프를 데이터 표로 전사한다("언어 문제  64.9"). 이걸 버리고 캡셔닝을
                #   기다리면 API 없이는 요소가 통째로 비고, 있어도 생성 설명이 수치를 놓친다.
                #   (rule-based vs generation 분리 원칙: 추출된 데이터는 규칙으로 옮긴다)
                raw_content = item.get("content", "")
                data = _chart_data_table(raw_content)
                flow = _flowchart_lines(raw_content) if not data else ""
                if data:
                    content, mapped_type = data, "table"
                elif flow:
                    # 흐름도(삼각무역 도식 등) — 정답도 화살표 줄로 전사한다.
                    # 인쇄 캡션("(가)")이 있으면 앞에 붙여 어느 도식인지 알 수 있게 한다.
                    content = f"{forced_caption}\n{flow}" if forced_caption else flow
                    mapped_type = "text"
                else:
                    # ⚠ 그림 속 평문(지도 지명 라벨 등)은 쓰지 않는다. MinerU가 "전(합)"처럼
                    #   같은 라벨을 수십 번 게워내고, 정답 도서도 지명을 그렇게 나열하지 않는다
                    #   (실측: 세계사 p022 정밀도 0.954→0.518). 지도 설명은 캡셔닝 소관.
                    content = "이미지 캡셔닝 대기"
            else:
                content = item.get("content", "")
        elif mapped_type in ("image", "chart_graph", "cartoon"):
            content = "이미지 캡셔닝 대기"
        elif item_type == "list":
            content = "\n".join(item.get("list_items", []))
        else:
            content = item.get("text", "")

        # MinerU 첨자 마크업 정화(2026-07-19): 외국어 장식 타이포("Reaching beyond…"의
        # 글자 크기 변주)를 MinerU가 <sub>/<sup>로 도배 — 태그가 그대로 점역돼 페이지가
        # 폭주했다(외국어 p014: 6045셀 vs gold 1434, CER 201%). 태그만 벗기고 글자는 보존.
        # 진짜 수식 첨자는 interline_equation(LaTeX) 경로라 여기 영향 없다.
        if content and "<su" in content:
            content = re.sub(r"</?su[bp]>", "", content)

        # 블록 수식 구분자 벗기기(QA 11번, 2026-08-08). MinerU는 수식을 마크다운 관례대로
        # `$$\n식\n$$` 세 줄로 내보낸다 — 한 줄짜리 수식인데 경계 파일에 줄바꿈이 두 개
        # 들어가고, 점역사 편집창에도 `$$`가 그대로 보인다. 경계 계약은
        # `formula(content=LaTeX)`(SPEC-INTERFACE §2)이므로 구분자는 우리 몫이 아니다.
        # 점자에는 영향이 없다(convert_latex의 _MATH_DELIM_RE가 어차피 지운다) — 이건
        # 사람이 읽고 고치는 텍스트를 계약대로 되돌리는 것이다.
        # ⚠ 본문(text) 요소 안의 인라인 `$…$`는 건드리지 않는다. translator가 그 구분자로
        #   수식을 라우팅한다(_INLINE_MATH_RE) — 지우면 \frac이 영어 단어로 점역된다.
        if mapped_type == "formula":
            content = _strip_block_math_delim(content)

        # 글자는 PDF 텍스트 레이어 우선(하이브리드) — 티어와 무관하게 블록별로 시도한다.
        # TEXT_NATIVE(스캔 아님이 확실)면 가드 없이 대체, 그 외(OCR 라우팅)는 가드 통과 시만.
        if mapped_type in _NATIVE_TEXT_TYPES:
            if extraction_method == "TEXT_NATIVE":
                content = _native_text_spaced(fitz_page, bb) or content
            else:
                content = _native_override(fitz_page, bb, content) or content
        elif mapped_type == "table":
            # 괘선 없는 '표'는 표가 아니다 — 위 _h_rules 주석 참조(QA 9번)
            n_rules = _h_rules(fitz_page, bb) if item_type == "table" else None
            if n_rules is not None and n_rules < _RULE_MIN_H:
                mapped_type, content = "text", _table_to_text(content)
            elif (n_rules is not None            # None = 벡터로 판단 불가, 손대지 않는다
                    and _is_boxed_prose(fitz_page, bb, content, _page_box_rects())):
                # 테두리뿐인 '표' = 글상자에 든 줄글 — 위 _is_boxed_prose 절 주석(F15)
                mapped_type, content = "text", _table_to_text(content)
            else:
                # 표는 구조 때문에 전면 대체를 못 하므로 글머리 기호(제72항)만 되돌리고,
                # 셀 안 글자는 레이어를 근거로 한글 오독만 고친다(둘 다 전부-아니면-전무).
                content = _restore_table_bullets(fitz_page, bb, content)
                content = _correct_table_cells(fitz_page, bb, content)

        # 인쇄 캡션 강제 적용(위 forced_caption) — 생성 placeholder/빈 content를 덮어쓴다.
        if forced_caption and mapped_type == "caption":
            content = forced_caption

        # page_number인데 숫자가 아닌 경우 type을 text로 정정
        if mapped_type == "page_number" and not content.strip().lstrip('-').isnumeric():
            mapped_type = "text"

        # 제목 단계(NLD 2장2절1) — MinerU가 이미 찾아 둔 것을 살린다. 위 _heading_level 주석 참조.
        hlevel = _heading_level(item, mapped_type, content)
        if hlevel:
            mapped_type = "title"

        # 캡셔닝으로 갈 시각요소만 원본에서 다시 자른다(위 _recrop_hidpi 주석).
        # 타입이 다 정해진 뒤에 한다 — 도중에 table/text로 바뀌면 캡셔닝을 안 타므로
        # 그림 쪽에만 비용(중앙 41ms/장)이 붙게 둔다.
        if image_path and mapped_type in ("image", "chart_graph", "cartoon"):
            _recrop_hidpi(fitz_page, bb, image_path, page_img_info)

        # MinerU bbox는 0~1000 정규화 좌표 → 실제 픽셀로 변환
        bb_px = [bb[0] / 1000 * img_w, bb[1] / 1000 * img_h,
                 bb[2] / 1000 * img_w, bb[3] / 1000 * img_h]

        merged_layout.append({
            "element_id": element_id,
            "reading_order": order,
            "type": mapped_type,
            "bbox": bb,
            "bbox_px": bb_px,
            # 페이지 픽셀 크기(2x 렌더 기준) — bbox_px와 같은 좌표계. BE/FE가 bbox를
            # image_width/height에 대한 비율로 매핑할 수 있게 경계파일까지 흘려보낸다.
            "page_width": img_w,
            "page_height": img_h,
            "content": content,
            "image_path": image_path,
            "heading_level": hlevel,
            "caption_ref": None,
            "flags": ["MINERU_FOOTER"] if raw_footer else [],
        })
        order += 1

    # 지면에 안 그려진 글자 요소 버리기(C006) — fitz_page 를 닫기 전에 한다.
    merged_layout = _drop_unpainted(merged_layout, fitz_page, page_no)

    doc.close()

    # 매핑 파일 업데이트 (다음 캐시 재실행에 대비)
    with open(mapping_file, "w", encoding="utf-8") as f:
        json.dump(hash_to_eid, f)

    if debug:
        layout_json = [
            {k: v for k, v in el.items() if k not in ("bbox_px", "content")}
            for el in merged_layout
        ]
        with open(base / "merged_layout.json", "w", encoding="utf-8") as f:
            json.dump(layout_json, f, ensure_ascii=False, indent=2)

    _mark_text_lookalikes(merged_layout, page_no)
    logger.info("page %d: %d개 요소, 이미지 %d개", page_no, len(merged_layout),
                sum(1 for e in merged_layout if e.get("image_path")))
    return merged_layout
