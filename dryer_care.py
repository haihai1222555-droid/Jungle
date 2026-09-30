# -*- coding: utf-8 -*-
"""건조기가 몇 번 돌았는지 우리가 직접 센다.

왜 우리가 세나. 세탁기는 기기가 누적 횟수(cycleCount)를 알려준다. 그래서
"누적 30회, 통살균 필요" 를 그대로 보여줄 수 있고, 통살균을 돌리면 기기가
알아서 0 으로 되돌린다. 그런데 **건조기는 그 값을 아예 안 보내준다.**
원본이 주는 것은 runState·timer·cycle·error 넷뿐이고, 건조기 쪽에는
cycle 이 없다. 그래서 우리가 셀 수밖에 없다.

어떻게 세나. 5초마다 상태를 보고 있으므로 '돌던 것이 멈췄다' 를 본다.
    가동(DRYING·RUNNING …) → 끝(END·COMPLETE·POWER_OFF …)   = 한 번
정확한 값이 아니다. 중간에 전원을 끄면 그것도 한 번으로 센다. 그래서
화면에는 반드시 "우리가 센 것" 이라고 적어야 한다. 기기 총 누적이 아니다.

통살균을 하면 어떻게 되나. 세탁기는 기기가 알아서 누적 횟수를 0 으로
되돌린다. 건조기는 우리가 세니까 우리가 되돌려야 한다. 그런데 원본은 어떤
코스로 도는지를 안 알려준다. 알려주는 것은 **이 코스가 몇 분짜리인가**
(timer.total) 뿐이다. 그래서 길이로 가린다.

지금까지 실제로 관측한 건조 코스 길이는 57·68·70·73·87·88·103·107·178분
이었다. 가장 긴 것이 178분이다. 통살균은 그보다 훨씬 길다 — 3시간 반쯤으로
듣고 있다. 다만 LG 고객지원은 "모델마다 다르다" 고만 하고 분 수를 안 밝혀서
**확인된 값이 아니다.** 그래서 200분으로 끊는다. 관측된 최장 건조(178분)보다
위, 듣고 있는 통살균(210분)보다 아래다.

어느 쪽으로 틀리는 게 나은가. '통살균을 못 알아보는' 쪽이다. 그러면 지금과
같아지기만 하고 손으로 되돌리면 된다. 반대쪽은 하지 않은 청소를 했다고
말하게 된다. 그래서 문턱을 넉넉히 높게 둔다.

LG 안내는 건조기 드럼을 한 달에 한 번 통살균하라고 한다. 세탁기(30회)와
기준이 다르므로, 보여줄 때는 횟수와 함께 마지막 통살균이 언제였는지도 쓴다.
"""
import os
import threading
import time

import state_store

STORE_NAME = "dryer_care"

# 한 유닛에 남겨 둘 가동 기록 수. 코스 길이를 살펴보기 위한 것이라
# 최근 것 얼마쯤이면 충분하다.
MAX_RUNS = 80

# 이만큼보다 긴 코스는 통살균으로 본다(분). 위 설명 참고 — 관측된 최장
# 건조가 178분이고 통살균은 210분쯤으로 듣고 있어서 그 사이에 둔다.
# 실제 분 수가 밝혀지면 서버에서 환경변수로만 바꾸면 된다.
try:
    TUB_CLEAN_MINUTES = int(os.environ.get("DRYER_TUB_CLEAN_MINUTES") or 200)
except ValueError:
    TUB_CLEAN_MINUTES = 200

# 돌고 있는 것으로 보는 상태
RUNNING_STATES = ("RUNNING", "DRYING", "COOLING", "WASHING", "RINSING", "SPINNING")
# 끝난 것으로 보는 상태. 구김 방지는 건조가 끝난 뒤의 뒷정리라 끝으로 본다.
DONE_STATES = ("END", "COMPLETE", "POWER_OFF", "INITIAL", "WRINKLE_CARE")

_LOCK = threading.Lock()
_DATA = None
_PREV = {}          # 타워 -> 직전에 본 모습


def _load():
    global _DATA
    if _DATA is None:
        raw = state_store.state_load(STORE_NAME, {})
        _DATA = raw if isinstance(raw, dict) else {}
        _DATA.setdefault("units", {})
    return _DATA


def _unit(label):
    units = _load()["units"]
    u = units.get(label)
    if not isinstance(u, dict):
        u = {"count": 0, "since": None, "runs": [], "cleanedAt": None}
        units[label] = u
    u.setdefault("count", 0)
    u.setdefault("runs", [])
    return u


def _total_minutes(unit):
    """이 코스의 총 시간(분). 모르면 0."""
    if not isinstance(unit, dict):
        return 0
    t = unit.get("timer")
    if not isinstance(t, dict):
        return 0
    try:
        h = int(t.get("totalHour") or 0)
        m = int(t.get("totalMinute") or 0)
    except (TypeError, ValueError):
        return 0
    return h * 60 + m


def observe(tower_label, unit, state, now=None):
    """건조기 하나를 보고, 한 번 다 돌았으면 센다.

    돌려주는 값:
        None      아직 아무 일도 없다
        "run"     한 번 돌았다 (횟수 +1)
        "clean"   통살균으로 보인다 (횟수를 0 으로 되돌렸다)

    저장은 부르는 쪽에서 한 번에 한다. 5초마다 아홉 대를 보므로
    기기마다 저장하면 같은 일을 아홉 번 하게 된다.
    """
    now = now or time.time()
    prev = _PREV.get(tower_label)

    cur = {
        "state": state,
        "total": _total_minutes(unit),
    }
    # 돌고 있는 동안의 총 시간을 들고 있는다. 끝나고 나면 0 으로 돌아오기 때문에
    # 끝난 뒤에 물어보면 늦는다.
    if state in RUNNING_STATES and cur["total"] > 0:
        cur["lastTotal"] = cur["total"]
    elif prev:
        cur["lastTotal"] = prev.get("lastTotal") or 0
    else:
        cur["lastTotal"] = 0

    _PREV[tower_label] = cur

    if prev is None:
        return None         # 서버가 막 떴다. 직전을 모르니 세지 않는다.
    if prev["state"] not in RUNNING_STATES:
        return None
    if state not in DONE_STATES:
        return None

    minutes = prev.get("lastTotal") or 0
    cleaned = minutes >= TUB_CLEAN_MINUTES

    with _LOCK:
        u = _unit(tower_label)
        u["lastAt"] = round(now, 3)
        u["runs"].append({"at": round(now, 3), "total": minutes})
        u["runs"] = u["runs"][-MAX_RUNS:]
        if cleaned:
            # 세탁기가 스스로 하는 것과 같은 일을 우리가 한다.
            u["count"] = 0
            u["since"] = round(now, 3)
            u["cleanedAt"] = round(now, 3)
        else:
            u["count"] = int(u.get("count") or 0) + 1
            if not u.get("since"):
                u["since"] = round(now, 3)

    if cleaned:
        # 짐작으로 되돌린 것이므로 로그에 분 수를 남긴다. 나중에 이 문턱이
        # 맞았는지 확인할 수 있어야 한다.
        print("[관리] %s 건조기가 %d분짜리 코스를 마쳤습니다 "
              "(%d분 넘음 -> 통살균으로 보고 횟수를 0 으로 되돌립니다)"
              % (tower_label, minutes, TUB_CLEAN_MINUTES))
        return "clean"
    return "run"


def _washer(label):
    data = _load()
    ws = data.setdefault("washers", {})
    w = ws.get(label)
    if not isinstance(w, dict):
        w = {"lastCount": None, "cleanedAt": None}
        ws[label] = w
    return w


def observe_washer(tower_label, unit, now=None):
    """세탁기 누적 횟수를 지켜본다. 줄었으면 통살균한 것으로 본다.

    기기가 "통살균했다" 고 말해 주지는 않는다. 다만 통살균을 하면 누적
    횟수가 되돌아간다. 그래서 값이 줄어든 것을 보면 그 사이에 했다는 뜻이다.
    (수리나 교체로 줄어들 수도 있다. 그래서 화면에는 '마지막으로 되돌아간
    때' 라는 뜻이 드러나게 적는다.)

    한 번이라도 적었으면 True.
    """
    now = now or time.time()
    if not isinstance(unit, dict):
        return False
    cyc = (unit.get("cycle") or {}).get("cycleCount")
    if not isinstance(cyc, int) or cyc < 0:
        return False

    with _LOCK:
        w = _washer(tower_label)
        prev = w.get("lastCount")
        w["lastCount"] = cyc
        if isinstance(prev, int) and cyc < prev:
            w["cleanedAt"] = round(now, 3)
            return True
    return False


def washers():
    """세탁기 쪽 기록. {타워: {lastCount, cleanedAt}}"""
    with _LOCK:
        ws = _load().get("washers") or {}
        return {k: {"lastCount": v.get("lastCount"),
                    "cleanedAt": v.get("cleanedAt")}
                for k, v in ws.items() if isinstance(v, dict)}


def save():
    """센 것을 저장소에 적는다."""
    with _LOCK:
        state_store.state_save(STORE_NAME, _load())


def counts():
    """보여줄 값. {타워: {count, since, lastAt, cleanedAt}}"""
    with _LOCK:
        units = _load()["units"]
        return {k: {"count": v.get("count", 0),
                    "since": v.get("since"),
                    "lastAt": v.get("lastAt"),
                    "cleanedAt": v.get("cleanedAt")}
                for k, v in units.items() if isinstance(v, dict)}


def durations(tower_label=None):
    """가동 한 번마다의 총 시간(분). 통살균이 몇 분짜리인지 보려는 것.

    tower_label 을 안 주면 전부 모아서 준다.
    """
    with _LOCK:
        units = _load()["units"]
        out = []
        for k, v in units.items():
            if tower_label and k != tower_label:
                continue
            if not isinstance(v, dict):
                continue
            for r in v.get("runs") or []:
                if isinstance(r, dict) and r.get("total"):
                    out.append({"tower": k, "at": r.get("at"),
                                "total": r["total"]})
    out.sort(key=lambda r: r.get("at") or 0)
    return out


def mark_cleaned(tower_label, now=None):
    """통살균을 했다고 알려준다. 센 것을 0 으로 되돌린다.

    기기가 코스를 안 알려주므로 사람이 눌러야 한다. 언젠가 가동 시간으로
    통살균을 가려낼 수 있게 되면 여기를 자동으로 부르면 된다.
    """
    now = now or time.time()
    with _LOCK:
        u = _unit(tower_label)
        u["count"] = 0
        u["since"] = round(now, 3)
        u["cleanedAt"] = round(now, 3)
    save()
    return True
