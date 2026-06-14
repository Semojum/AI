"""점자 조판 공용 상수.

여러 braille 모듈(translator·layout·text/table/image/… braille)에서 중복 정의하던
32칸·26줄을 한 곳으로 모은다. (BBPG 1장1절3: 가로 32칸·세로 26줄 기본 규격.)
"""

COLS = 32  # 한 줄 칸 수
ROWS = 26  # 한 페이지 줄 수 (BBPG 1장1절3: 세로 26줄)
