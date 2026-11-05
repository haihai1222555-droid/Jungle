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

지금까지 실제로 관측한 건조 코스 길이는 57~178분 및 시간건조 180분(3시간)
이었다. 실제 스팀통살균 코스는 약 3시간 8분(188분)으로 관측되었다.
따라서 일반 건조 코스(최장 180분)보다 위, 스팀통살균(188분)보다 아래인
185분으로 끊는다.

어느 쪽으로 틀리는 게 나은가. '통살균을 못 알아보는' 쪽이다. 그러면 지금과
같아지기만 하고 손으로 되돌리면 된다. 반대쪽은 하지 않은 청소를 했다고
말하게 된다. 그래서 문턱을 185분으로 둔다.

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
# 일반 건조가 178~180분이고 스팀통살균은 188분으로 확인되어 그 사이(185분)에 둔다.
# 필요 시 서버 환경변수 DRYER_TUB_CLEAN_MINUTES 로 조정할 수 있다.
try:
    TUB_CLEAN_MINUTES = int(os.environ.get("DRYER_TUB_CLEAN_MINUTES") or 185)
except ValueError:
    TUB_CLEAN_MINUTES = 185

# 이보다 긴 가동은 통살균으로 보지 않는다(분). 관측된 통살균은 188~248분이다.
# 3호기가 배수 호스 문제로 493~533분까지 늘어난 적이 있는데, 그런 것은 어떤 코스로도
# 설명이 안 된다.
try:
    TUB_CLEAN_MAX_MINUTES = int(os.environ.get("DRYER_TUB_CLEAN_MAX_MINUTES") or 300)
except ValueError:
    TUB_CLEAN_MAX_MINUTES = 300


def _parse_towers(raw):
    """'3' 또는 '3,7' 같은 글에서 호기 번호만 뽑는다."""
    out = set()
    for tok in str(raw or "").replace(" ", "").split(","):
        digits = "".join(ch for ch in tok if ch.isdigit())
        if digits:
            out.add(int(digits))
    return out


# 자동 통살균 인식을 끄는 호기. 호스가 고장 나 시간이 믿을 수 없는 기기에 쓴다.
# 횟수는 계속 센다. 서버 .env 에 DRYER_AUTO_CLEAN_OFF=3 처럼 적는다.
AUTO_CLEAN_OFF = _parse_towers(os.environ.get("DRYER_AUTO_CLEAN_OFF"))

# 돌고 있는 것으로 보는 상태
RUNNING_STATES = ("RUNNING", "DRYING", "COOLING", "WASHING", "RINSING", "SPINNING")
# 끝난 것으로 보는 상태. 구김 방지는 건조가 끝난 뒤의 뒷정리라 끝으로 본다.
DONE_STATES = ("END", "COMPLETE", "POWER_OFF", "INITIAL", "WRINKLE_CARE")

# 가동 도중에 거치면 그 가동의 시간을 믿을 수 없는 상태.
HARD_BREAK_STATES = ("ERROR",)
# 돌던 가동이 이만큼 계속 '돌지도 끝나지도 않은' 상태면 그 가동은 잊는다.
# 그 사이에 다른 사람이 다시 돌렸을 수 있다.
BREAK_EXPIRE_SEC = 6 * 3600
_PATH_MAX = 14

_LOCK = threading.Lock()
_DATA = None
_PREV = {}          # 타워 -> 직전에 본 모습과 돌던 가동의 기억


def _tower_no(label):
    digits = "".join(ch for ch in str(label) if ch.isdigit())
    return int(digits) if digits else None


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


def _note(path, state):
    if not path or path[-1] != state:
        path.append(state)
        if len(path) > _PATH_MAX:
            del path[1:2]


def observe(tower_label, unit, state, now=None):
    """건조기 하나를 보고, 한 번 다 돌았으면 센다.

    돌려주는 값:
        None      아직 아무 일도 없다
        "run"     한 번 돌았다 (횟수 +1)
        "clean"   통살균으로 보인다 (횟수를 0 으로 되돌렸다)

    '돌던 가동' 을 기억한다. 예전에는 끝나는 순간 바로 직전 관측이 '돌고 있음'
    일 때만 세어서, 중간에 값이 끊기거나 일시정지·오류·감지 중을 한 번이라도
    거치면 그 가동이 통째로 사라졌다(통살균 반영도 함께 안 됐다).

    저장은 부르는 쪽에서 한 번에 한다. 5초마다 아홉 대를 보므로
    기기마다 저장하면 같은 일을 아홉 번 하게 된다.
    """
    now = now or time.time()
    prev = _PREV.get(tower_label) or {}
    total = _total_minutes(unit)

    cur = {
        "state": state,
        "total": total,
        "active": bool(prev.get("active")),
        "lastTotal": prev.get("lastTotal") or 0,
        "hard": bool(prev.get("hard")),
        "soft": bool(prev.get("soft")),
        "path": list(prev.get("path") or []),
        "breakSince": prev.get("breakSince"),
    }
    finished = None

    if state in RUNNING_STATES:
        if not cur["active"]:
            # 새 가동. 지난 가동의 시간이 남아 있으면 안 된다.
            cur.update(active=True, lastTotal=0, hard=False, soft=False, path=[])
        cur["breakSince"] = None
        _note(cur["path"], state)
        # 돌고 있는 동안의 총 시간을 들고 있는다. 끝나고 나면 0 으로 돌아오기 때문에
        # 끝난 뒤에 물어보면 늦는다.
        if total > 0:
            cur["lastTotal"] = total
    elif state in DONE_STATES:
        if cur["active"]:
            finished = {"minutes": cur["lastTotal"], "hard": cur["hard"],
                        "soft": cur["soft"], "path": cur["path"] + [state]}
        cur.update(active=False, lastTotal=0, hard=False, soft=False, path=[], breakSince=None)
    else:
        # 돌지도 끝나지도 않은 중간 상태(값 끊김·일시정지·오류·감지 중 …).
        # 돌던 가동은 그대로 기억한다. 다만 오래 이어지면 잊는다.
        if cur["active"]:
            if state in HARD_BREAK_STATES:
                cur["hard"] = True
            else:
                cur["soft"] = True
            _note(cur["path"], state)
            if cur["breakSince"] is None:
                cur["breakSince"] = now
            elif now - cur["breakSince"] > BREAK_EXPIRE_SEC:
                print("[관리] %s 건조기가 %d시간 넘게 돌지도 끝나지도 않아 돌던 가동을 잊습니다 (%s)"
                      % (tower_label, BREAK_EXPIRE_SEC // 3600, ">".join(cur["path"])))
                cur.update(active=False, lastTotal=0, hard=False, soft=False, path=[], breakSince=None)

    _PREV[tower_label] = cur

    if finished is None:
        return None

    minutes = finished["minutes"]
    path_text = ">".join(finished["path"])[:80]
    interrupted = finished["hard"] or finished["soft"]

    # 통살균으로 볼 수 있는지. 아닐 때는 이유를 남긴다.
    why_not = None
    if minutes < TUB_CLEAN_MINUTES:
        pass
    elif minutes > TUB_CLEAN_MAX_MINUTES:
        why_not = "%d분을 넘어 어떤 코스로도 설명이 안 됨" % TUB_CLEAN_MAX_MINUTES
    elif finished["hard"]:
        why_not = "도중에 오류를 거쳐 시간을 믿을 수 없음"
    elif _tower_no(tower_label) in AUTO_CLEAN_OFF:
        why_not = "이 호기는 자동 통살균 인식이 꺼져 있음"
    cleaned = minutes >= TUB_CLEAN_MINUTES and why_not is None

    with _LOCK:
        u = _unit(tower_label)
        u["lastAt"] = round(now, 3)
        entry = {"at": round(now, 3), "total": minutes}
        if interrupted:
            entry["path"] = path_text          # 나중에 원인을 볼 수 있게 순서를 남긴다
        if why_not:
            entry["noClean"] = True
        u["runs"].append(entry)
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

    if interrupted:
        print("[관리] %s 건조기 가동 도중 상태가 바뀌었습니다: %s (%d분)"
              % (tower_label, path_text, minutes))
    if cleaned:
        # 짐작으로 되돌린 것이므로 로그에 분 수를 남긴다. 나중에 이 문턱이
        # 맞았는지 확인할 수 있어야 한다.
        print("[관리] %s 건조기가 %d분짜리 코스를 마쳤습니다 "
              "(%d분 넘음 -> 통살균으로 보고 횟수를 0 으로 되돌립니다)"
              % (tower_label, minutes, TUB_CLEAN_MINUTES))
        return "clean"
    if why_not:
        print("[관리] %s 건조기 %d분짜리 가동은 통살균으로 보지 않습니다 (%s). 횟수만 셉니다."
              % (tower_label, minutes, why_not))
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
