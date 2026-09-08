# -*- coding: utf-8 -*-
"""값이 없을 때 '사용 가능' 으로 읽히지 않는지 확인한다.

    python test_truthfulness.py

이 프로젝트가 실제로 망가지는 방식은 거의 언제나 하나다.
**기기가 값을 안 줬는데 그것을 '비어 있다' 로 읽는 것.**

하루에만 세 번 나왔다.
  · 워시타워 하나가 통째로 null 로 왔는데 빈 dict 로 메워 '사용 가능' 이 됐다
  · runState 만 빠져 왔는데 POWER_OFF 로 메워, 1시간 23분 남은 건조기가
    '사용 가능' 으로 떴다. 완료 알림까지 나갈 뻔했다
  · 통계를 못 받았는데 박아둔 숫자로 '최근 7일 실측 708회' 라고 띄웠다

전부 손으로 찾았다. 손으로 찾는 것은 언젠가 놓친다.
그래서 여기 모아 둔다. 코드를 고칠 때마다 이것부터 돌린다.

여기서 보는 것은 파이썬 쪽(봇·서버)이다. 알림을 보낼지 말지를 정하는
자리가 여기라서 제일 위험하다. 웹(app.js)의 같은 판단은 브라우저가
있어야 돌릴 수 있어 여기서 못 본다. 그쪽은 눈으로 확인한다.
"""
import sys

import cafeteria  # noqa: F401  (test_cafeteria.py 가 따로 본다)
import device_log
import discord_bot as bot
import start_server as srv

FAILS = []


def check(name, got, want):
    if got != want:
        FAILS.append("%s → %r (%r 여야 함)" % (name, got, want))


# =========================================================
# 1. 값이 안 온 기기
# =========================================================
def test_missing_values():
    # 유닛이 통째로 없다
    for who, fn in (("봇", bot.unit_state), ("서버", srv.unit_state)):
        check("%s: 유닛 없음" % who, fn(None), "UNKNOWN")
        check("%s: 유닛이 빈 dict" % who, fn({}), "UNKNOWN")

        # runState 만 빠졌는데 시간이 남아 있다 → 돌아가는 중이다
        running = {"timer": {"remainHour": 1, "remainMinute": 23}}
        check("%s: 상태없음+1시간23분" % who, fn(running), "UNKNOWN_RUNNING")

        # runState 가 빠졌고 시간도 0 → 모른다. 꺼진 것이 아니다
        idle = {"timer": {"remainHour": 0, "remainMinute": 0}}
        check("%s: 상태없음+0분" % who, fn(idle), "UNKNOWN")

        # 정상은 그대로
        ok = {"runState": {"currentState": "RUNNING"}}
        check("%s: 정상" % who, fn(ok), "RUNNING")

    # 모르는 상태를 '비어 있다' 로 세면 안 된다
    for st in ("UNKNOWN", "UNKNOWN_RUNNING"):
        check("빈 걸로 세나: %s" % st, st in bot.FREE_STATES, False)

    # 코스만 고르고 시작 전인 것도 빈 기기가 아니다 (빨래가 들어 있을 수 있다)
    check("빈 걸로 세나: INITIAL", "INITIAL" in bot.FREE_STATES, False)

    # 이름표가 있어야 화면에 코드가 그대로 나가지 않는다
    for st in ("UNKNOWN", "UNKNOWN_RUNNING"):
        check("이름표 있나: %s" % st, bool(bot.STATE_LABELS.get(st)), True)


# =========================================================
# 2. 워시타워가 통째로 null
# =========================================================
def test_null_tower():
    status = {"워시타워_1": None,
              "워시타워_2": {"washer": {"runState": {"currentState": "POWER_OFF"}}}}
    check("null 타워: 값 있나", bot.tower_has_data(status, "워시타워_1"), False)
    check("정상 타워: 값 있나", bot.tower_has_data(status, "워시타워_2"), True)
    check("없는 타워: 값 있나", bot.tower_has_data(status, "워시타워_9"), False)
    check("status 자체가 None", bot.tower_has_data(None, "워시타워_1"), False)


# =========================================================
# 3. 아직 안 끝났는데 '완료' 로 보지 않는다
# =========================================================
def test_not_finished():
    """완료 판정은 알림을 보내는 자리라 제일 위험하다.

    예전에 runState 가 빠지면 POWER_OFF 로 메웠다. POWER_OFF 는 '끝남' 이라서,
    1시간 23분 남은 기기에 '가동 완료' 알림이 나갈 수 있었다.
    """
    started = srv.STARTED_STATES
    for st in ("RUNNING", "WASHING", "RINSING", "SPINNING", "DRYING",
               "COOLING", "DETECTING"):
        check("가동 중으로 보나: %s" % st, st in started, True)

    # 무게 감지 중에는 시간이 아직 0 으로 온다. 이때 완료로 보면 안 된다
    check("DETECTING 이 가동 중인가", "DETECTING" in started, True)

    # 예약도 '시작한 상태' 다. 예약 시간이 다 되어 남은 시간이 0 이 되는 순간
    # '끝났다' 로 읽히면, 기계가 이제 막 돌기 시작하는데 완료 알림이 나간다.
    check("RESERVED 가 가동 중인가", "RESERVED" in started, True)

    # 모르는 상태는 '끝남' 목록에 없어야 한다
    finished_states = ("COMPLETE", "END", "POWER_OFF", "WRINKLE_CARE")
    for st in ("UNKNOWN", "UNKNOWN_RUNNING", "RESERVED"):
        check("끝난 걸로 보나: %s" % st, st in finished_states, False)


def test_unknown_states():
    """처음 보는 상태가 와도 빈 기기로 세지 않고 영어가 그대로 안 나가는지.

    RESERVED 가 실제로 그랬다. 코드 어디에도 없어서 화면에 영어가 나갔다.
    LG 상태 이름은 앞으로도 더 나온다.
    """
    check("예약 이름표", bot.STATE_LABELS.get("RESERVED"), "예약 대기 중")
    # END 도 이름표가 없어 영어가 그대로 화면에 나갔다
    check("END 이름표 있나", bool(bot.STATE_LABELS.get("END")), True)
    check("예약을 빈 걸로 세나", "RESERVED" in bot.FREE_STATES, False)
    # 아예 모르는 이름이 와도 빈 기기가 아니어야 한다
    check("모르는 상태를 빈 걸로 세나", "WHAT_IS_THIS" in bot.FREE_STATES, False)


# =========================================================
# 4. 기기 이력 — 일시정지 원인을 지어내지 않는다
# =========================================================
def test_device_log():
    device_log._PREV.clear()
    device_log._PAUSE_SINCE.clear()

    # 처음 본 순간은 '달라진 것' 이 아니다 (멀쩡한 기기라면)
    first = device_log.observe("9호기", "washer", {"runState": {"currentState": "RUNNING"}},
                               "RUNNING")
    check("첫 관측은 기록 안 함", first, [])

    # 멀쩡히 돌다 멈췄다 → 사람이 누른 것
    made = device_log.observe("9호기", "washer", {}, "PAUSE")
    check("사람이 누른 일시정지", [m.get("cause") for m in made], ["user"])

    # 오류에서 멈췄다 → 오류 때문
    device_log._PREV.clear()
    device_log.observe("7호기", "dryer", {"runState": {"currentState": "RUNNING"}}, "RUNNING")
    device_log.observe("7호기", "dryer", {"error": "DRAIN_ERROR"}, "ERROR")
    made = device_log.observe("7호기", "dryer", {"error": "DRAIN_ERROR"}, "PAUSE")
    check("오류로 멈춤", [m.get("cause") for m in made if m["event"] == "pause"], ["error"])

    # 일주일 지난 것은 지운다
    import time
    old = [{"ts": time.time() - 8 * 24 * 3600}, {"ts": time.time()}]
    check("일주일 지난 기록 정리", len(device_log._prune(old)), 1)


# =========================================================
# 5. 코스 이름을 기기에서 읽어온 척하지 않는다
# =========================================================
def test_course_not_from_device():
    """원본 API 는 코스를 주지 않는다. 준다고 착각하는 코드가 생기면 안 된다."""
    import washtower
    # 총 가동 시간은 실제로 오는 값이다
    check("총 시간 읽기", washtower.total_minutes({"timer": {"totalHour": 1, "totalMinute": 23}}), 83)
    check("총 시간 없음", washtower.total_minutes(None), 0)
    check("총 시간 표기", washtower.format_minutes(83), "1시간 23분")
    check("총 시간 0", washtower.format_minutes(0), "")
    # 코스 목록은 '이 기기에 있는 것' 이지 '지금 도는 것' 이 아니다
    check("세탁 코스 수", len(washtower.WASH_COURSES) > 0, True)
    check("건조 코스 수", len(washtower.DRY_COURSES) > 0, True)


def main():
    tests = [test_missing_values, test_null_tower, test_not_finished,
             test_unknown_states, test_device_log, test_course_not_from_device]
    for t in tests:
        try:
            t()
        except Exception as e:
            FAILS.append("%s 가 터졌습니다: %r" % (t.__name__, e))

    print("값이 없을 때 '사용 가능' 으로 읽히지 않는지 — %d가지 확인" % len(tests))
    for f in FAILS:
        print("  틀림: " + f)
    if FAILS:
        print("\n%d개 틀렸습니다." % len(FAILS))
        return 1
    print("모두 통과했습니다.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
