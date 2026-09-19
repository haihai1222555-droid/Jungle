# -*- coding: utf-8 -*-
"""급식 공지 가려내기가 제대로 되는지 확인한다.

    python test_cafeteria.py

이 채널에는 급식과 Grab&Go(카페) 공지가 섞여 올라온다.
잘못 가르면 알림 기능이 통째로 무의미해진다. 그래서 따로 확인한다.

앞의 아홉 개는 실제로 채널에 올라와 있는 글 제목 그대로다.
뒤의 것들은 앞으로 올라올 법한 모양을 넣어 본 것이다.
특히 '신메뉴'(그랩앤고)와 '중식당' 처럼 걸리기 쉬운 것을 넣었다.
"""
import sys
from datetime import datetime

import cafeteria as cf

# 윈도우 콘솔은 기본이 cp949 라 '—' 같은 글자에서 터진다.
try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

# (제목, 고정 여부, 이래야 한다)
CASES = [
    # ── 실제로 채널에 있는 글 아홉 개 ──────────────────────────
    ("9월 1주차 식단표", True, "weekly"),
    ("9월 8일(화) 중식 메뉴", False, "daily"),
    ("9월 7일(월) 석식 메뉴", False, "daily"),
    ("9월 7일(월) 중식 메뉴", False, "daily"),
    ("그랩앤고(카페) 여름 시즌 신메뉴 출시 안내(6/22~)", False, "other"),
    ("정글 그랩앤고(카페) 굿즈 판매 공지", False, "other"),
    ("페이코 가입 안내", False, "other"),
    ("카카오채널 안내", False, "other"),
    ("정글 편의시설 이용안내", False, "other"),

    # ── 앞으로 올 법한 급식 공지 ──────────────────────────────
    ("9월 10일(목) 조식 메뉴", False, "daily"),
    ("9월 12일(토) 석식메뉴", False, "daily"),      # 띄어쓰기 없음
    ("10월 1일(수) 중식 메뉴", False, "daily"),
    ("9월 2주차 식단표", True, "weekly"),
    ("9월 2주차 주간메뉴표", True, "weekly"),

    # ── 걸리기 쉬운 것들 ──────────────────────────────────────
    # '메뉴' 가 들어 있지만 급식이 아니다
    ("그랩앤고 신메뉴 안내", False, "other"),
    # 날짜까지 붙어도 그랩앤고면 급식이 아니다
    ("9월 10일(목) 그랩앤고 신메뉴 출시", False, "other"),
    # '중식당' 은 끼니가 아니다
    ("9월 12일(토) 중식당 팝업 안내", False, "other"),
    # 고정이 아니면 주간 식단표로 보지 않는다
    ("9월 1주차 식단표", False, "other"),
    # 날짜만 있고 끼니가 없다
    ("9월 15일(화) 식당 휴무 안내", False, "other"),
    # 끼니만 있고 날짜가 없다
    ("중식 코너 위치 변경", False, "other"),
    ("", False, "other"),
    (None, False, "other"),
]


def test_no_flood():
    """알림이 한꺼번에 쏟아지지 않는지.

    카카오에서 못 받아온 상태에서 '이미 다 봤다' 고 저장해 버리면,
    다음에 제대로 받아왔을 때 아홉 개가 전부 새 글이 되어
    신청자 전원에게 한꺼번에 나간다.
    """
    fails = []
    saved_cache, saved_seen = cf._CACHE, cf._SEEN
    try:
        # 못 받아온 상태에서는 표시를 남기지 않아야 한다
        cf._CACHE = {"weekly": None, "daily": [], "fetchedAt": 0}
        cf._SEEN = None
        got = cf.new_posts(mark=True)
        if got != []:
            fails.append("못 받아왔는데 새 글을 돌려줌: %r" % got)
        if cf._SEEN is not None:
            fails.append("못 받아왔는데 '이미 봤다' 고 저장함: %r" % cf._SEEN)

        # 한 번에 보낼 수 있는 수에 상한이 있어야 한다
        if not isinstance(getattr(cf, "MAX_BURST", None), int):
            fails.append("MAX_BURST 가 없다 (쏟아짐 상한)")
        elif cf.MAX_BURST > 5:
            fails.append("MAX_BURST 가 너무 크다: %d" % cf.MAX_BURST)
    finally:
        cf._CACHE, cf._SEEN = saved_cache, saved_seen
    return fails


def test_photo_pick():
    """사진을 달라는 말인지, 그리고 어느 끼니 사진을 고르는지.

    글만 받던 사람들이 "같이 올라오는 급식 사진도 보여 달라" 고 해서 붙인 기능이다.
    두 가지가 어긋나면 안 된다.
      · 밥 이야기가 아닌데 사진을 붙이는 것 ("세탁기 사진 보여줘")
      · 사진을 준다고 해 놓고 사진이 없는 끼니를 고르는 것
    """
    fails = []

    for q, want in [
        ("급식 사진 보여줘", True),
        ("오늘 점심 사진 좀", True),
        ("저녁 메뉴 사진 있어?", True),
        ("밥 어떻게 생겼어", True),
        ("오늘 점심 뭐야", False),         # 글만 물었다
        ("식단표 알려줘", False),
        ("세탁기 사진 보여줘", False),     # 밥 이야기가 아니다
        ("", False),
        (None, False),
    ]:
        got = cf.wants_photo(q)
        if got != want:
            fails.append("사진 요청 판정 %r → %s (%s 여야 함)" % (q, got, want))

    lunch = {"meal": "중식", "month": 9, "day": 19, "image": "http://x/l.jpg"}
    dinner = {"meal": "석식", "month": 9, "day": 19, "image": "http://x/d.jpg"}
    noon = datetime(2026, 9, 19, 11, 30, tzinfo=cf.KST)
    night = datetime(2026, 9, 19, 18, 0, tzinfo=cf.KST)

    saved = cf.today_menus
    try:
        cf.today_menus = lambda when=None: [lunch, dinner]
        for q, when, want in [
            ("급식 사진 보여줘", noon, "중식"),    # 안 밝히면 시간에 맞춰
            ("급식 사진 보여줘", night, "석식"),
            ("저녁 사진 보여줘", noon, "석식"),    # 밝히면 그대로
            ("점심 사진", night, "중식"),
            ("아침 사진 보여줘", noon, "중식"),    # 조식이 없으면 시간 기준으로
        ]:
            got = cf.photo_for(q, when)
            meal = got and got.get("meal")
            if meal != want:
                fails.append("%r (%d시) → %s (%s 여야 함)" % (q, when.hour, meal, want))

        # 사진이 없으면 고르지 않는다. 준다고 해 놓고 빈손으로 나가면 안 된다.
        cf.today_menus = lambda when=None: [dict(lunch, image=None)]
        if cf.photo_for("급식 사진", noon) is not None:
            fails.append("사진이 없는 끼니를 골랐다")
        cf.today_menus = lambda when=None: []
        if cf.photo_for("급식 사진", noon) is not None:
            fails.append("메뉴가 없는 날인데 끼니를 골랐다")
    finally:
        cf.today_menus = saved
    return fails


def main():
    bad = []
    for title, pinned, want in CASES:
        got = cf.classify(title, pinned)
        if got != want:
            bad.append((title, pinned, want, got))

    for msg in test_no_flood():
        bad.append((msg, "-", "-", "-"))
    for msg in test_photo_pick():
        bad.append((msg, "-", "-", "-"))

    print("급식 공지 가려내기 %d가지 + 알림 쏟아짐 방지 + 사진 고르기" % len(CASES))
    for title, pinned, want, got in bad:
        print("  틀림: %r (고정=%s) → %s (%s 여야 함)" % (title, pinned, got, want))

    if bad:
        print("\n%d개 틀렸습니다." % len(bad))
        return 1
    print("모두 통과했습니다.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
