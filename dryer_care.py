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
되돌린다. 건조기는 우리가 세니까 우리가 되돌려야 한다. **통살균을 한 사람이
사이트의 기기 상세 창에서 직접 누른다.**

예전에는 코스 길이로 알아맞혔는데 틀렸다. 원본은 어떤 코스인지 안 알려주고
길이(timer.total)만 준다. 배수 호스가 고장 난 기기는 시간이 부풀어, 하지 않은
청소가 했다고 적혔다. 실제 통살균은 문턱보다 짧아 못 알아봤고, 기기 종류마다
길이도 다르다. 그래서 짐작을 그만두었다. 길이는 기록에 계속 남긴다.

LG 안내는 건조기 드럼을 한 달에 한 번 통살균하라고 한다. 세탁기(30회)와
기준이 다르므로, 보여줄 때는 횟수와 함께 마지막 통살균이 언제였는지도 쓴다.
"""
import hmac
import secrets
import threading
import time

import state_store

STORE_NAME = "dryer_care"

# 한 유닛에 남겨 둘 가동 기록 수. 코스 길이를 살펴보기 위한 것이라
# 최근 것 얼마쯤이면 충분하다.
MAX_RUNS = 80

# 돌고 있는 것으로 보는 상태
RUNNING_STATES = ("RUNNING", "DRYING", "COOLING", "WASHING", "RINSING", "SPINNING")
# 끝난 것으로 보는 상태. 구김 방지는 건조가 끝난 뒤의 뒷정리라 끝으로 본다.
DONE_STATES = ("END", "COMPLETE", "POWER_OFF", "INITIAL", "WRINKLE_CARE")

# 돌던 가동이 이만큼 계속 '돌지도 끝나지도 않은' 상태면 그 가동은 잊는다.
# 그 사이에 다른 사람이 다시 돌렸을 수 있다.
BREAK_EXPIRE_SEC = 6 * 3600
_PATH_MAX = 14

# 같은 기기는 한 번 초기화하면 이만큼 다시 못 누른다.
RESET_COOLDOWN_SEC = 6 * 3600
# 잘못 눌렀을 때 되돌릴 수 있는 시간.
UNDO_SEC = 10 * 60

_LOCK = threading.Lock()
_DATA = None
_PREV = {}          # 타워 -> 직전에 본 모습과 돌던 가동의 기억


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

    '돌던 가동' 을 기억한다. 예전에는 끝나는 순간 바로 직전 관측이 '돌고 있음'
    일 때만 세어서, 중간에 값이 끊기거나 일시정지·오류·감지 중을 한 번이라도
    거치면 그 가동이 통째로 사라졌다.

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
        "broken": bool(prev.get("broken")),
        "path": list(prev.get("path") or []),
        "breakSince": prev.get("breakSince"),
    }
    finished = None

    if state in RUNNING_STATES:
        if not cur["active"]:
            # 새 가동. 지난 가동의 시간이 남아 있으면 안 된다.
            cur.update(active=True, lastTotal=0, broken=False, path=[])
        cur["breakSince"] = None
        _note(cur["path"], state)
        # 돌고 있는 동안의 총 시간을 들고 있는다. 끝나고 나면 0 으로 돌아오기 때문에
        # 끝난 뒤에 물어보면 늦는다.
        if total > 0:
            cur["lastTotal"] = total
    elif state in DONE_STATES:
        if cur["active"]:
            finished = {"minutes": cur["lastTotal"], "broken": cur["broken"],
                        "path": cur["path"] + [state]}
        cur.update(active=False, lastTotal=0, broken=False, path=[], breakSince=None)
    else:
        # 돌지도 끝나지도 않은 중간 상태(값 끊김·일시정지·오류·감지 중 …).
        # 돌던 가동은 그대로 기억한다. 다만 오래 이어지면 잊는다.
        if cur["active"]:
            cur["broken"] = True
            _note(cur["path"], state)
            if cur["breakSince"] is None:
                cur["breakSince"] = now
            elif now - cur["breakSince"] > BREAK_EXPIRE_SEC:
                print("[관리] %s 건조기가 %d시간 넘게 돌지도 끝나지도 않아 돌던 가동을 잊습니다 (%s)"
                      % (tower_label, BREAK_EXPIRE_SEC // 3600, ">".join(cur["path"])))
                cur.update(active=False, lastTotal=0, broken=False, path=[], breakSince=None)

    _PREV[tower_label] = cur

    if finished is None:
        return None

    minutes = finished["minutes"]
    path_text = ">".join(finished["path"])[:80]
    interrupted = finished["broken"]

    with _LOCK:
        u = _unit(tower_label)
        u["lastAt"] = round(now, 3)
        entry = {"at": round(now, 3), "total": minutes}
        if interrupted:
            entry["path"] = path_text          # 나중에 원인을 볼 수 있게 순서를 남긴다
        u["runs"].append(entry)
        u["runs"] = u["runs"][-MAX_RUNS:]
        u["count"] = int(u.get("count") or 0) + 1
        if not u.get("since"):
            u["since"] = round(now, 3)

    if interrupted:
        print("[관리] %s 건조기 가동 도중 상태가 바뀌었습니다: %s (%d분)"
              % (tower_label, path_text, minutes))
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
    """보여줄 값. {타워: {count, seq, since, lastAt, cleanedAt}}

    count 는 통살균하면 0 이 된다. seq 는 줄지 않는다. 알림이 '내 빨래가
    끝났는지' 를 셀 때는 seq 를 쓴다. count 를 쓰면 누가 초기화하는 순간
    그 건조기에 걸어 둔 알림이 지난 것으로 지워진다.
    되돌리기 열쇠(undo)는 내보내지 않는다.
    """
    with _LOCK:
        units = _load()["units"]
        return {k: {"count": v.get("count", 0),
                    "seq": int(v.get("count") or 0) + int(v.get("cleared") or 0),
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


def _clear(u, now):
    u["cleared"] = int(u.get("cleared") or 0) + int(u.get("count") or 0)
    u["count"] = 0
    u["since"] = round(now, 3)
    u["cleanedAt"] = round(now, 3)


def mark_cleaned(tower_label, now=None):
    """운영자가 손으로 되돌린다. 대기 시간 제한이 없다."""
    now = now or time.time()
    with _LOCK:
        _clear(_unit(tower_label), now)
    save()
    return True


def manual_reset(tower_label, now=None):
    """사이트에서 '통살균 했어요' 를 눌렀다.

    누구나 누를 수 있으므로 같은 기기는 RESET_COOLDOWN_SEC 에 한 번만 받고,
    UNDO_SEC 안에는 누른 사람이 되돌릴 수 있게 열쇠를 돌려준다.
    """
    now = now or time.time()
    with _LOCK:
        u = _unit(tower_label)
        wait = (u.get("manualAt") or 0) + RESET_COOLDOWN_SEC - now
        if wait > 0:
            return {"ok": False, "reason": "cooldown", "waitSec": int(wait) + 1}
        count = int(u.get("count") or 0)
        token = secrets.token_urlsafe(12)
        u["undo"] = {"token": token, "until": round(now + UNDO_SEC, 3),
                     "count": count, "since": u.get("since"),
                     "cleanedAt": u.get("cleanedAt"), "manualAt": u.get("manualAt")}
        _clear(u, now)
        u["manualAt"] = round(now, 3)
    save()
    return {"ok": True, "prevCount": count, "token": token, "undoSec": UNDO_SEC}


def undo_reset(tower_label, token, now=None):
    """방금 한 초기화를 되돌린다. 그 사이에 돈 횟수는 더해서 남긴다."""
    now = now or time.time()
    with _LOCK:
        u = _unit(tower_label)
        last = u.get("undo")
        if (not isinstance(last, dict) or not isinstance(token, str)
                or not hmac.compare_digest(str(last.get("token")).encode(), token.encode())
                or now > (last.get("until") or 0)):
            return {"ok": False, "reason": "expired"}
        back = int(last.get("count") or 0)
        u["count"] = int(u.get("count") or 0) + back
        u["cleared"] = max(0, int(u.get("cleared") or 0) - back)
        for key in ("since", "cleanedAt", "manualAt"):
            u[key] = last.get(key)
        del u["undo"]
        total = u["count"]
    save()
    return {"ok": True, "count": total}
