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

import cafeteria as cf

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


def main():
    bad = []
    for title, pinned, want in CASES:
        got = cf.classify(title, pinned)
        if got != want:
            bad.append((title, pinned, want, got))

    print("급식 공지 가려내기 — %d개 확인" % len(CASES))
    for title, pinned, want, got in bad:
        print("  틀림: %r (고정=%s) → %s (%s 여야 함)" % (title, pinned, got, want))

    if bad:
        print("\n%d개 틀렸습니다." % len(bad))
        return 1
    print("모두 통과했습니다.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
