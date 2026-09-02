import os
import re
import sys
import io
import json
import asyncio
import urllib.request
import urllib.error
from datetime import datetime
import discord
from discord import app_commands
from discord.ext import commands, tasks
from PIL import Image, ImageDraw, ImageFont

# 콘솔 출력 버퍼링 해제
try:
    sys.stdout.reconfigure(encoding='utf-8', line_buffering=True)
    sys.stderr.reconfigure(encoding='utf-8', line_buffering=True)
except Exception:
    pass

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# =========================================================
# 설정 및 환경 변수 (.env 및 다양한 경로 자동 탐색)
# =========================================================
try:
    from dotenv import load_dotenv
    load_dotenv()
    load_dotenv(os.path.join(BASE_DIR, ".env"))
except Exception:
    pass

# 수동 .env 파일 탐색 (루트, 현재 폴더, 스크립트 폴더)
possible_env_paths = [
    os.path.join(BASE_DIR, ".env"),
    os.path.join(os.getcwd(), ".env"),
    os.path.join(BASE_DIR, "token.txt"),
    os.path.join(os.getcwd(), "token.txt")
]

for p in possible_env_paths:
    if os.path.exists(p):
        try:
            with open(p, 'r', encoding='utf-8-sig') as f:
                content = f.read().strip()
                if '=' in content:
                    for line in content.splitlines():
                        line = line.strip()
                        if line and not line.startswith('#') and '=' in line:
                            k, v = line.split('=', 1)
                            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
                elif len(content) > 30 and ' ' not in content:
                    os.environ.setdefault("DISCORD_BOT_TOKEN", content)
        except Exception:
            pass

# 다양한 키 이름 지원 (DISCORD_BOT_TOKEN, BOT_TOKEN, DISCORD_TOKEN, TOKEN)
DISCORD_BOT_TOKEN = (
    os.environ.get("DISCORD_BOT_TOKEN")
    or os.environ.get("BOT_TOKEN")
    or os.environ.get("DISCORD_TOKEN")
    or os.environ.get("TOKEN")
    or ""
).strip().strip('"').strip("'")

STATUS_API_URL = os.environ.get("STATUS_API_URL") or "https://jungle-wash.onrender.com/api/status"
BOT_DATA_FILE = os.path.join(BASE_DIR, "discord_alarms.json")

# 워시타워 9대 메타데이터
TOWERS = [
    {"id": 1, "name": "워시타워_1", "zone": "men",    "label": "No.1", "zoneName": "남성 전용"},
    {"id": 2, "name": "워시타워_2", "zone": "men",    "label": "No.2", "zoneName": "남성 전용"},
    {"id": 3, "name": "워시타워_3", "zone": "men",    "label": "No.3", "zoneName": "남성 전용"},
    {"id": 4, "name": "워시타워_4", "zone": "men",    "label": "No.4", "zoneName": "남성 전용"},
    {"id": 5, "name": "워시타워_5", "zone": "men",    "label": "No.5", "zoneName": "남성 전용"},
    {"id": 6, "name": "워시타워_6", "zone": "common", "label": "No.6", "zoneName": "공용"},
    {"id": 7, "name": "워시타워_7", "zone": "common", "label": "No.7", "zoneName": "공용"},
    {"id": 8, "name": "워시타워_8", "zone": "women",  "label": "No.8", "zoneName": "여성 전용"},
    {"id": 9, "name": "워시타워_9", "zone": "women",  "label": "No.9", "zoneName": "여성 전용"},
]

# 가동 중인 상태 목록 (알림 등록 대상 = 남은 시간을 계산할 수 있는 상태)
RUNNING_STATES = ('RUNNING', 'WASHING', 'RINSING', 'SPINNING', 'DRYING', 'COOLING')

# 사용자가 새 빨래를 시작했다고 볼 수 있는 상태.
# DETECTING(무게 감지 중)은 방금 돌리기 시작한 것이므로 여기 포함한다.
STARTED_STATES = RUNNING_STATES + ('DETECTING',)

# 정말로 비어 있는 상태. 이 둘이 아니면 누군가 쓰고 있는 것으로 본다.
FREE_STATES = ('POWER_OFF', 'INITIAL')

# 이보다 오래된 알림 등록은 지난 빨래로 보고 정리한다 (한 사이클은 길어야 2시간)
MAX_ALARM_AGE_SEC = 4 * 60 * 60

# 세탁이 끝난 뒤 이 시간이 지나도록 기기가 그대로면 '수거 안 함' 으로 보고 한 번 더 알린다.
STALE_PICKUP_SEC = int(os.environ.get("STALE_PICKUP_SEC") or 15 * 60)

# =========================================================
# 폰트 로더 헬퍼
# =========================================================
def get_font(size, bold=False):
    bundled = os.path.join(BASE_DIR, "NanumGothic-Bold.ttf" if bold else "NanumGothic-Regular.ttf")
    if os.path.exists(bundled):
        try:
            return ImageFont.truetype(bundled, size)
        except Exception:
            pass

    font_names = [
        "C:/Windows/Fonts/malgunbd.ttf" if bold else "C:/Windows/Fonts/malgun.ttf",
        "C:/Windows/Fonts/Pretendard-Bold.ttf" if bold else "C:/Windows/Fonts/Pretendard-Regular.ttf",
        "/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf" if bold else "/usr/share/fonts/truetype/nanum/NanumGothic.ttf",
    ]
    for fn in font_names:
        try:
            return ImageFont.truetype(fn, size)
        except Exception:
            continue
    return ImageFont.load_default()

# =========================================================
# 데이터 로드 / 저장 헬퍼
# =========================================================
active_alarms = []

def load_alarms():
    global active_alarms
    if os.path.exists(BOT_DATA_FILE):
        try:
            with open(BOT_DATA_FILE, 'r', encoding='utf-8') as f:
                active_alarms = json.load(f)
        except Exception as e:
            print(f"[Alarm Load Error] {e}")
            active_alarms = []

def save_alarms():
    try:
        tmp = BOT_DATA_FILE + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(active_alarms, f, ensure_ascii=False, indent=2)
        if os.path.exists(BOT_DATA_FILE):
            os.remove(BOT_DATA_FILE)
        os.rename(tmp, BOT_DATA_FILE)
    except Exception as e:
        print(f"[Alarm Save Error] {e}")

def fetch_live_status():
    """Render API 또는 터널에서 실시간 세탁실 데이터 조회"""
    try:
        req = urllib.request.Request(STATUS_API_URL, headers={'User-Agent': 'JungleDiscordBot/2.0'})
        with urllib.request.urlopen(req, timeout=5) as res:
            if res.status == 200:
                return json.loads(res.read().decode('utf-8'))
    except Exception as e:
        print(f"[API Fetch Error] {e}")
    return {}

def format_timer(hour, minute):
    if not hour and not minute:
        return "대기 중"
    if hour > 0:
        return f"{hour}시간 {minute}분"
    return f"{minute}분"

def is_unit_running(state, remain_min):
    return state in RUNNING_STATES or (remain_min > 0 and state != 'ERROR' and state != 'POWER_OFF')

# =========================================================
# 디스코드 봇 클라이언트 초기화 (슬래시 커맨드 전용)
# =========================================================
intents = discord.Intents.default()

# 멘션과 DM 은 이 인텐트 없이도 내용을 읽을 수 있다 (디스코드가 그 두 경우는 예외로 준다).
# 멘션 없이 채널에 그냥 쓴 말까지 읽으려면 message_content 인텐트가 필요한데,
# 이건 '특권 인텐트'라 개발자 포털에서 먼저 켜야 하고
# 포털에서 켜지 않은 채 여기서 요청하면 봇이 접속 자체를 못 한다.
# 그래서 포털에서 켠 뒤 ENABLE_MESSAGE_CONTENT=1 을 줬을 때만 활성화한다.
if str(os.environ.get("ENABLE_MESSAGE_CONTENT", "")).lower() in ("1", "true", "yes", "on"):
    intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)

# =========================================================
# 현실 세탁실 초고화질 카드 뷰 이미지 렌더러 (Web UI 100% 동일)
# =========================================================
def render_floorplan_image(status_data):
    """웹의 '현실 배치 뷰' 카드를 그대로 옮겨 그린다.

    나눔고딕에는 이모지 글리프가 없어 🔔 🌀 같은 문자는 빈 칸으로 나온다.
    그래서 아이콘은 전부 도형(원·사각형)으로 직접 그린다.
    """
    MARGIN, GAP = 35, 24
    W = 2000
    CARD_H = 300
    ROW1_Y, ROW2_Y = 168, 543
    H = ROW2_Y + CARD_H + MARGIN

    usable = W - MARGIN * 2
    CARD_W5 = (usable - GAP * 4) // 5
    CARD_W4 = (usable - GAP * 3) // 4

    BG = (10, 13, 20)
    CARD_BG = (17, 23, 36)
    LINE = (32, 41, 58)
    TXT_DIM = (148, 163, 184)
    TXT_MUTED = (100, 116, 139)

    img = Image.new("RGB", (W, H), color=BG)
    draw = ImageDraw.Draw(img)

    f_header = get_font(34, bold=True)
    f_sub = get_font(21, bold=False)
    f_sec = get_font(25, bold=True)
    f_num = get_font(30, bold=True)
    f_tag = get_font(17, bold=True)
    f_unit = get_font(19, bold=False)
    f_state = get_font(21, bold=True)
    f_time = get_font(26, bold=True)
    f_badge = get_font(17, bold=True)

    def tw(txt, font):
        b = draw.textbbox((0, 0), txt, font=font)
        return b[2] - b[0]

    def pill(x1, y1, x2, y2, fill=None, outline=None, width=1, radius=7):
        draw.rounded_rectangle([(x1, y1), (x2, y2)], radius=radius, fill=fill, outline=outline, width=width)

    def dim(c, f):
        return (int(c[0] * f), int(c[1] * f), int(c[2] * f))

    # ── 헤더 ──
    pill(MARGIN, 24, W - MARGIN, 96, fill=(15, 21, 33), radius=14)
    draw.text((MARGIN + 26, 44), "크래프톤 정글 스마트 세탁실 현실 배치도", fill=(240, 245, 255), font=f_header)

    # 카드 테두리/상태 뱃지와 같은 색을 쓴다
    legend = [((100, 116, 139), "사용 가능"), ((16, 185, 129), "전체 가동 중"),
              ((59, 130, 246), "세탁 가동 중"), ((245, 158, 11), "건조 가동 중"),
              ((239, 68, 68), "점검 필요")]
    lx = W - MARGIN - 28
    for col, label in reversed(legend):
        lw = tw(label, f_sub)
        draw.text((lx - lw, 50), label, fill=TXT_DIM, font=f_sub)
        draw.ellipse([(lx - lw - 28, 55), (lx - lw - 12, 71)], fill=col)
        lx -= lw + 28 + 30

    def draw_unit(x, uy, cw, name, unit, state, minutes, err, is_dryer):
        """기기 한 칸: 도어 원 + [이름 ... 시간] + [상태 · 코스 · 알림뱃지]"""
        if err:
            accent = (239, 68, 68)
            state_txt = "기기 점검/에러"
        elif state in ("WRINKLE_CARE", "COMPLETE", "END"):
            accent = (56, 189, 248)
            state_txt = "구김 방지 중" if state == "WRINKLE_CARE" else "완료 · 수거 가능"
        elif minutes > 0:
            accent = (245, 158, 11) if is_dryer else (59, 130, 246)
            state_txt = "작동 중"
        elif state in FREE_STATES:
            accent = (71, 85, 105)
            state_txt = "대기 중 (사용 가능)"
        else:
            accent = (234, 179, 8)
            state_txt = STATE_LABELS.get(state, state)

        # 드럼 도어 (바깥 링 + 안쪽 원) — 세탁기 도어처럼 보이게
        cxp, cyp, r = x + 44, uy + 34, 25
        draw.ellipse([(cxp - r, cyp - r), (cxp + r, cyp + r)],
                     outline=accent, width=3, fill=dim(accent, 0.18))
        draw.ellipse([(cxp - 13, cyp - 13), (cxp + 13, cyp + 13)], fill=dim(accent, 0.42))
        draw.ellipse([(cxp - 5, cyp - 9), (cxp + 1, cyp - 3)], fill=dim(accent, 0.85))

        tx = x + 82

        # 1행: 기기 이름 + 남은 시간(오른쪽)
        draw.text((tx, uy + 4), name, fill=TXT_DIM, font=f_unit)
        if minutes > 0:
            t = format_timer(unit.get("timer", {}).get("remainHour", 0),
                             unit.get("timer", {}).get("remainMinute", 0))
            draw.text((x + cw - tw(t, f_time) - 20, uy), t,
                      fill=accent if err else (255, 255, 255), font=f_time)
        else:
            lbl = "점검 필요" if err else "대기 중"
            draw.text((x + cw - tw(lbl, f_state) - 20, uy + 4), lbl,
                      fill=accent if err else TXT_MUTED, font=f_state)

        # 2행: 상태
        draw.text((tx, uy + 30), state_txt, fill=accent, font=f_state)

        # 3행: 에러 안내 / 코스 뱃지 + 5분전 알림 뱃지
        by = uy + 62
        if err:
            pill(x + 20, by, x + cw - 20, by + 30, fill=(69, 16, 16), outline=(185, 28, 28))
            draw.text((x + 34, by + 5), ("건조기" if is_dryer else "세탁기") + " 배수관 점검 필요",
                      fill=(254, 202, 202), font=f_badge)
        elif minutes > 0:
            course = "표준 건조" if is_dryer else "표준 세탁"
            cw_ = tw(course, f_badge)
            pill(tx, by, tx + cw_ + 26, by + 30, fill=(30, 41, 59), outline=(51, 65, 85))
            draw.ellipse([(tx + 10, by + 11), (tx + 18, by + 19)], fill=accent)
            draw.text((tx + 24, by + 5), course, fill=(203, 213, 225), font=f_badge)


    def draw_card(t, x, y, cw):
        data = status_data.get(t["name"], {})
        d, w = data.get("dryer", {}), data.get("washer", {})
        d_state = d.get("runState", {}).get("currentState", "POWER_OFF")
        w_state = w.get("runState", {}).get("currentState", "POWER_OFF")
        d_min = (d.get("timer", {}).get("remainHour", 0) * 60) + d.get("timer", {}).get("remainMinute", 0)
        w_min = (w.get("timer", {}).get("remainHour", 0) * 60) + w.get("timer", {}).get("remainMinute", 0)
        d_err = bool(d.get("error")) or d_state == "ERROR"
        w_err = bool(w.get("error")) or w_state == "ERROR"

        if d_err or w_err:
            border, label, bg = (239, 68, 68), "점검 필요", (69, 16, 16)
        elif d_min > 0 and w_min > 0:
            border, label, bg = (16, 185, 129), "전체 가동 중", (6, 78, 59)
        elif d_min > 0:
            border, label, bg = (245, 158, 11), "건조 가동 중", (69, 45, 8)
        elif w_min > 0:
            border, label, bg = (59, 130, 246), "세탁 가동 중", (23, 46, 105)
        else:
            border, label, bg = (51, 65, 85), "전체 대기 중", (30, 41, 59)

        pill(x, y, x + cw, y + CARD_H, fill=CARD_BG, outline=border, width=3, radius=18)

        draw.text((x + 20, y + 14), t["label"], fill=(255, 255, 255), font=f_num)
        zc = (59, 130, 246) if "남성" in t["zoneName"] else ((168, 85, 247) if "공용" in t["zoneName"] else (236, 72, 153))
        zx = x + 22 + tw(t["label"], f_num) + 12
        zw = tw(t["zoneName"], f_tag)
        pill(zx, y + 19, zx + zw + 20, y + 45, fill=dim(zc, 0.22), outline=zc, radius=6)
        draw.text((zx + 10, y + 22), t["zoneName"], fill=zc, font=f_tag)

        sw = tw(label, f_tag)
        pill(x + cw - sw - 38, y + 19, x + cw - 18, y + 45, fill=bg, outline=border, radius=6)
        draw.text((x + cw - sw - 28, y + 22), label, fill=(255, 255, 255), font=f_tag)

        draw.line([(x + 16, y + 58), (x + cw - 16, y + 58)], fill=LINE, width=2)

        draw_unit(x, y + 70, cw, "건조기", d, d_state, d_min, d_err, True)

        # 웹처럼 점 두 개로 구분
        mid = x + cw // 2
        draw.line([(x + 16, y + 180), (mid - 22, y + 180)], fill=LINE, width=2)
        draw.line([(mid + 22, y + 180), (x + cw - 16, y + 180)], fill=LINE, width=2)
        draw.ellipse([(mid - 10, y + 176), (mid - 2, y + 184)], fill=(71, 85, 105))
        draw.ellipse([(mid + 2, y + 176), (mid + 10, y + 184)], fill=(71, 85, 105))

        draw_unit(x, y + 192, cw, "세탁기", w, w_state, w_min, w_err, False)

    def section(y, text, chips, bg, fg):
        wtxt = tw(text, f_sec)
        box = 30 + len(chips) * 24 + wtxt + 22
        pill(MARGIN, y, MARGIN + box, y + 40, fill=bg, radius=9)
        cx = MARGIN + 16
        for c in chips:
            pill(cx, y + 12, cx + 16, y + 28, fill=c, radius=4)
            cx += 24
        draw.text((cx + 4, y + 7), text, fill=fg, font=f_sec)

    section(112, "남성 구역 (No.1 ~ No.5)", [(59, 130, 246)], (23, 46, 105), (191, 219, 254))
    for i, t in enumerate(TOWERS[:5]):
        draw_card(t, MARGIN + i * (CARD_W5 + GAP), ROW1_Y, CARD_W5)

    section(487, "공용 (No.6~7) & 여성 구역 (No.8~9)", [(168, 85, 247), (236, 72, 153)], (69, 26, 106), (233, 213, 255))
    for i, t in enumerate(TOWERS[5:]):
        draw_card(t, MARGIN + i * (CARD_W4 + GAP), ROW2_Y, CARD_W4)

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return buf

# =========================================================
# 알림 등록 / 해제 공통 헬퍼
# =========================================================
def alarm_key(user_id, tower_id, unit_type):
    return f"{user_id}_{tower_id}_{unit_type}"


def has_alarm(user_id, tower_id, unit_type):
    """이 사용자가 그 기기에 알림을 걸어뒀는지."""
    k = alarm_key(user_id, tower_id, unit_type)
    return any(a.get("key") == k for a in active_alarms)


def toggle_alarm_state(user_id, tower_id, unit_type, remain_min, device_name):
    """등록/해제만 수행한다. 응답 방식이 호출부마다 달라서 여기서는 상태만 바꾼다.
    등록되면 True, 해제되면 False 를 돌려준다."""
    k = alarm_key(user_id, tower_id, unit_type)
    existing = next((a for a in active_alarms if a.get("key") == k), None)
    if existing:
        active_alarms.remove(existing)
        save_alarms()
        return False

    active_alarms.append({
        "key": k,
        "userId": user_id,
        "towerId": tower_id,
        "unitType": unit_type,
        "deviceName": device_name,
        "targetMs": int(datetime.now().timestamp() * 1000) + (remain_min * 60 * 1000),
        "remainMinutes": remain_min,
        "notified5Min": False,
        "notified0Min": False,
        "createdAt": datetime.now().timestamp(),
        "registeredAt": int(datetime.now().timestamp() * 1000),
    })
    save_alarms()
    return True


def parse_option_value(val):
    """드롭다운 value 형식: towerId_unitType_remainMin_deviceName"""
    parts = val.split("_")
    return int(parts[0]), parts[1], int(parts[2]), "_".join(parts[3:])


async def register_or_toggle_alarm(interaction: discord.Interaction, tower_id, unit_type, remain_min, device_name):
    user_id = interaction.user.id

    if not toggle_alarm_state(user_id, tower_id, unit_type, remain_min, device_name):
        await interaction.response.send_message(
            f"🔕 **[{device_name}]** 알림 등록이 해제되었습니다.",
            ephemeral=True
        )
        return

    try:
        await interaction.user.send(
            f"🔔 **[정글 스마트 세탁실]** `{device_name}` 알림이 정상 등록되었습니다!\n"
            f"• 현재 잔여 시간: **약 {remain_min}분**\n"
            f"• 완료 **5분 전**과 **세탁 완료 시** 이 DM으로 즉시 안내해 드립니다. 🧺"
        )
        await interaction.response.send_message(
            f"✅ **[{device_name}]** 5분 전 개인 DM 알림이 등록되었습니다! (DM 창을 확인해 주세요)",
            ephemeral=True
        )
    except discord.Forbidden:
        await interaction.response.send_message(
            f"⚠️ **[{device_name}]** 알림이 등록되었으나, **디스코드 서버 개인 DM 받기 설정이 꺼져 있어 DM을 보낼 수 없습니다.**\n"
            f"👉 `서버 설정 > 개인정보 보호 설정 > 서버 멤버가 보내는 다이렉트 메시지 허용`을 켜주세요!",
            ephemeral=True
        )

# =========================================================
# 가동 기기 옵션 생성 헬퍼
# =========================================================
def get_running_options(status_data):
    running_options = []
    for t in TOWERS:
        data = status_data.get(t["name"], {})
        w = data.get("washer", {})
        d = data.get("dryer", {})

        w_state = w.get("runState", {}).get("currentState", "POWER_OFF")
        d_state = d.get("runState", {}).get("currentState", "POWER_OFF")
        w_min = (w.get("timer", {}).get("remainHour", 0) * 60) + w.get("timer", {}).get("remainMinute", 0)
        d_min = (d.get("timer", {}).get("remainHour", 0) * 60) + d.get("timer", {}).get("remainMinute", 0)
        
        w_err = w.get("error") or (w_state == "ERROR")
        d_err = d.get("error") or (d_state == "ERROR")

        # 상단 건조기 검증 (에러/대기 제외, 진짜 가동 중인 기기만)
        if not d_err and is_unit_running(d_state, d_min):
            time_str = format_timer(d.get("timer", {}).get("remainHour", 0), d.get("timer", {}).get("remainMinute", 0))
            running_options.append(discord.SelectOption(
                label=f"[{t['zoneName'][:2]}] {t['label']} 건조기 ({time_str} 남음)",
                description=f"가동 상태: {d_state} · 완료 5분 전 DM 알림",
                value=f"{t['id']}_dryer_{d_min}_{t['label']} 건조기",
                emoji="💨"
            ))

        # 하단 세탁기 검증
        if not w_err and is_unit_running(w_state, w_min):
            time_str = format_timer(w.get("timer", {}).get("remainHour", 0), w.get("timer", {}).get("remainMinute", 0))
            running_options.append(discord.SelectOption(
                label=f"[{t['zoneName'][:2]}] {t['label']} 세탁기 ({time_str} 남음)",
                description=f"가동 상태: {w_state} · 완료 5분 전 DM 알림",
                value=f"{t['id']}_washer_{w_min}_{t['label']} 세탁기",
                emoji="🫧"
            ))
    return running_options

# =========================================================
# 가동 중인 기기 선택 드롭다운 (Select Menu View)
# =========================================================
class LaundryAlarmSelect(discord.ui.Select):
    def __init__(self, running_options):
        super().__init__(
            placeholder="🔔 5분 전 알림을 받을 가동 중인 기기를 선택하세요...",
            min_values=1,
            max_values=1,
            options=running_options
        )

    async def callback(self, interaction: discord.Interaction):
        selected_val = self.values[0]  # format: "towerId_unitType_remainMin_deviceName"
        parts = selected_val.split("_")
        tower_id = int(parts[0])
        unit_type = parts[1]
        remain_min = int(parts[2])
        device_name = "_".join(parts[3:])
        await register_or_toggle_alarm(interaction, tower_id, unit_type, remain_min, device_name)

# =========================================================
# 개인 알림 패널 (버튼 아이콘으로 내 등록 여부 표시)
#
# 디스코드 버튼은 '메시지에 붙는' 요소라 모든 사람에게 똑같이 보인다.
# 즉 공개 메시지의 버튼으로는 "나만" 알림을 걸었는지 표시할 수 없다.
# 그래서 이 패널은 본인에게만 보이는(ephemeral) 메시지로 띄운다.
# =========================================================
class AlarmSectionButton(discord.ui.Button):
    """기기 한 줄에 붙는 알림 토글 버튼. 아이콘으로 내 등록 여부를 보여준다."""

    def __init__(self, user_id, option_value, all_values):
        tower_id, unit_type, _remain, device_name = parse_option_value(option_value)
        on = has_alarm(user_id, tower_id, unit_type)
        super().__init__(
            label="알림 켜짐" if on else "5분전 알림",
            emoji="🔔" if on else "🔕",
            style=discord.ButtonStyle.success if on else discord.ButtonStyle.secondary,
        )
        self.user_id = user_id
        self.option_value = option_value
        self.all_values = all_values

    async def callback(self, interaction: discord.Interaction):
        tower_id, unit_type, remain_min, device_name = parse_option_value(self.option_value)
        turned_on = toggle_alarm_state(self.user_id, tower_id, unit_type, remain_min, device_name)

        if turned_on:
            try:
                await interaction.user.send(
                    f"🔔 **[정글 스마트 세탁실]** `{device_name}` 알림이 등록되었습니다!\n"
                    f"• 현재 잔여 시간: **약 {remain_min}분**\n"
                    f"• 완료 **5분 전**, **완료 시**, 오래 안 가져가면 **수거 요청**까지 DM 으로 알려드립니다. 🧺"
                )
            except Exception:
                pass

        # 버튼 아이콘이 즉시 바뀌도록 패널을 그 자리에서 다시 그린다
        await interaction.response.edit_message(
            view=MyAlarmPanel(self.user_id, self.all_values)
        )


# 한 메시지에 들어갈 수 있는 컴포넌트 수가 제한되어 있어(40개) 카드 수를 제한한다.
MAX_ALARM_CARDS = 11

ZONE_STYLE = {
    "men": ("👦 남성 전용 (No.1 ~ No.5)", (59, 130, 246)),
    "common": ("🤝 공용 (No.6 ~ No.7)", (168, 85, 247)),
    "women": ("👧 여성 전용 (No.8 ~ No.9)", (236, 72, 153)),
}


class MyAlarmPanel(discord.ui.LayoutView):
    """기기마다 카드 한 줄 + 자기 버튼. 본인에게만 보인다."""

    def __init__(self, user_id, option_values):
        super().__init__(timeout=300)
        self.user_id = user_id
        self.option_values = option_values

        shown = option_values[:MAX_ALARM_CARDS]
        mine = [a for a in active_alarms if a.get("userId") == user_id]

        head = discord.ui.Container(accent_colour=discord.Colour.from_rgb(16, 185, 129))
        head.add_item(discord.ui.TextDisplay(
            "## 🔔 내 알림 관리\n"
            + (f"현재 **{len(mine)}개** 등록됨 — " + ", ".join(f"`{a['deviceName']}`" for a in mine)
               if mine else "아직 등록한 알림이 없습니다.")
            + "\n-# 🔔 초록 = 등록됨 · 🔕 회색 = 꺼짐 · 이 메시지는 나에게만 보입니다."
        ))
        self.add_item(head)

        if not shown:
            empty = discord.ui.Container(accent_colour=discord.Colour.from_rgb(100, 116, 139))
            empty.add_item(discord.ui.TextDisplay(
                "지금 가동 중인 기기가 없습니다.\n-# 세탁기·건조기가 돌기 시작하면 여기에 나타납니다."
            ))
            self.add_item(empty)
            return

        # 구역별로 묶어서 컨테이너 하나씩
        for zone_key in ("men", "common", "women"):
            title, colour = ZONE_STYLE[zone_key]
            rows = [v for v in shown
                    if next((t for t in TOWERS if t["id"] == parse_option_value(v)[0]), {}).get("zone") == zone_key]
            if not rows:
                continue

            box = discord.ui.Container(accent_colour=discord.Colour.from_rgb(*colour))
            box.add_item(discord.ui.TextDisplay(f"### {title}"))
            for v in rows:
                tower_id, unit_type, remain_min, device_name = parse_option_value(v)
                icon = "🌀" if unit_type == "dryer" else "🫧"
                on = has_alarm(user_id, tower_id, unit_type)
                btn = AlarmSectionButton(user_id, v, option_values)
                box.add_item(discord.ui.Section(
                    discord.ui.TextDisplay(
                        f"{icon} **{device_name}** {'· 🔔 알림 켜짐' if on else ''}\n"
                        f"-# 작동 중 · 약 **{remain_min}분** 남음"
                    ),
                    accessory=btn,
                ))
            self.add_item(box)

        if len(option_values) > MAX_ALARM_CARDS:
            tail = discord.ui.Container(accent_colour=discord.Colour.from_rgb(100, 116, 139))
            tail.add_item(discord.ui.TextDisplay(
                f"-# 가동 중인 기기가 많아 {MAX_ALARM_CARDS}개까지만 표시했습니다. "
                f"나머지는 위 드롭다운으로 등록할 수 있습니다."
            ))
            self.add_item(tail)


class OpenMyAlarmButton(discord.ui.Button):
    def __init__(self, option_values):
        super().__init__(label="내 알림 관리", emoji="🔔", style=discord.ButtonStyle.primary)
        self.option_values = option_values

    async def callback(self, interaction: discord.Interaction):
        uid = interaction.user.id
        await interaction.response.send_message(
            view=MyAlarmPanel(uid, self.option_values),
            ephemeral=True,
        )


class LaundryFloorplanView(discord.ui.View):
    def __init__(self, running_options):
        super().__init__(timeout=300)
        if running_options:
            self.add_item(LaundryAlarmSelect(running_options))
            self.add_item(OpenMyAlarmButton([o.value for o in running_options]))

def build_floorplan_embed():
    embed = discord.Embed(
        title="🧺 크래프톤 정글 스마트 세탁실 현황 & 알림",
        description="아래 **현실 배치도 카드 뷰**를 확인하고, **5분 전 DM 알림을 받을 가동 중인 기기를 선택**하세요!",
        color=discord.Color.from_rgb(16, 185, 129),
        timestamp=datetime.now()
    )
    embed.set_image(url="attachment://floorplan.png")
    embed.set_footer(
        text="크래프톤 정글 스마트 세탁실 · Realtime LG ThinQ Data",
        icon_url="https://jungle-wash.onrender.com/jungle-logo-192.png"
    )
    return embed

# =========================================================
# 상태 조회 명령어 (/세탁기 · /건조기 · /정보)
# =========================================================
STATE_LABELS = {
    "POWER_OFF": "대기 중", "INITIAL": "준비 완료", "COMPLETE": "완료 (수거 대기)",
    "END": "완료", "RUNNING": "작동 중", "WASHING": "세탁 중", "RINSING": "헹굼 중",
    "SPINNING": "탈수 중", "DRYING": "건조 중", "COOLING": "쿨링 중",
    "WRINKLE_CARE": "구김 방지 중", "PAUSE": "일시정지", "ERROR": "기기 점검/에러",
    "DETECTING": "무게 감지 중",
}

ZONE_SECTIONS = [
    ("men", "👦 남성 전용 (No.1 ~ No.5)"),
    ("common", "🤝 공용 (No.6 ~ No.7)"),
    ("women", "👧 여성 전용 (No.8 ~ No.9)"),
]


def build_unit_list_embed(unit_type):
    """세탁기 또는 건조기 9대의 현재 상태를 정리한 embed."""
    label = "건조기" if unit_type == "dryer" else "세탁기"
    icon = "🌀" if unit_type == "dryer" else "🫧"
    status_data = fetch_live_status()

    if not status_data:
        return discord.Embed(
            title=f"{icon} {label} 현황",
            description="⚠️ 실시간 데이터를 가져오지 못했습니다. 잠시 후 다시 시도해 주세요.",
            color=discord.Color.from_rgb(239, 68, 68),
        )

    free = running = errors = 0
    sections = []

    for zone_key, zone_title in ZONE_SECTIONS:
        lines = []
        for t in [x for x in TOWERS if x["zone"] == zone_key]:
            unit = (status_data.get(t["name"]) or {}).get(unit_type) or {}
            state = (unit.get("runState") or {}).get("currentState", "POWER_OFF")
            timer = unit.get("timer") or {}
            minutes = (timer.get("remainHour", 0) or 0) * 60 + (timer.get("remainMinute", 0) or 0)
            is_err = state == "ERROR" or bool(unit.get("error"))

            if is_err:
                mark, tail = "🔴", "점검 필요"
                errors += 1
            elif minutes > 0:
                mark = "🟠" if unit_type == "dryer" else "🔵"
                tail = f"**{format_timer(timer.get('remainHour', 0), timer.get('remainMinute', 0))}** 남음"
                running += 1
            elif state == "WRINKLE_CARE":
                mark, tail = "🟣", "완료 · 수거 가능"
            elif state not in FREE_STATES:
                # DETECTING 처럼 막 시작해서 아직 시간이 안 잡힌 상태.
                # 비어 있다고 안내하면 헛걸음하게 된다.
                mark, tail = "🟡", "사용 중 · 시간 계산 중"
                running += 1
            else:
                mark, tail = "⚪", "**사용 가능**"
                free += 1

            lines.append(f"{mark} `{t['label']}` {STATE_LABELS.get(state, state)} · {tail}")
        sections.append((zone_title, "\n".join(lines)))

    if errors:
        color = discord.Color.from_rgb(239, 68, 68)
    elif free == 0:
        color = discord.Color.from_rgb(245, 158, 11)
    else:
        color = discord.Color.from_rgb(16, 185, 129)

    embed = discord.Embed(
        title=f"{icon} {label} 현황",
        description=f"사용 가능 **{free}대** · 가동 중 **{running}대** · 점검 필요 **{errors}대**",
        color=color,
        timestamp=datetime.now(),
    )
    for name, value in sections:
        embed.add_field(name=name, value=value, inline=False)
    embed.set_footer(text="가동 중인 기기 알림은 /알림 · 크래프톤 정글 스마트 세탁실")
    return embed


def build_info_embed(user_id=None):
    """봇 사용법 안내."""
    embed = discord.Embed(
        title="🧺 정글 세탁실 봇 안내",
        description="세탁실 현황을 확인하고, 내 빨래가 끝나기 전에 DM 으로 알려주는 봇입니다.",
        color=discord.Color.from_rgb(16, 185, 129),
        timestamp=datetime.now(),
    )
    embed.add_field(
        name="📋 명령어",
        value=(
            "`/알림` · 배치도 확인 + 기기 선택해 알림 등록\n"
            "🗣️ **봇을 멘션하거나 DM 으로 그냥 말해도 됩니다**\n"
            "-# 예) `@봇 3번 건조기 알림 걸어줘`\n"
            "`/비서` · 말로 알림 걸기 (예: 3번 건조기 알림 걸어줘)\n"
            "`/내알림` · 내가 건 알림 확인 + 켜고 끄기\n"
            "`/세탁기` · 세탁기 9대 현황\n"
            "`/건조기` · 건조기 9대 현황\n"
            "`/정보` · 이 안내\n"
            "-# 명령어를 몰라도 그냥 말을 걸면 알아듣습니다."
        ),
        inline=False,
    )
    embed.add_field(
        name="🔔 알림 규칙",
        value=(
            "• 완료 **5분 전** DM\n"
            "• **완료** 시 DM\n"
            f"• 완료 후 **{STALE_PICKUP_SEC // 60}분** 지나도 안 가져가면 수거 요청 DM\n"
            "• 가동 중 **에러** 발생 시 즉시 DM\n"
            "• 다음 사람이 새로 돌리면 자동으로 해제됩니다"
        ),
        inline=False,
    )
    embed.add_field(
        name="🗺️ 구역",
        value="👦 남성 `No.1~5` · 🤝 공용 `No.6~7` · 👧 여성 `No.8~9`",
        inline=False,
    )
    embed.add_field(
        name="💻 웹 대시보드",
        value="https://jungle-wash.onrender.com\n혼잡도·골든타임·AI 비서는 웹에서 볼 수 있습니다.",
        inline=False,
    )

    if user_id is not None:
        mine = [a for a in active_alarms if a.get("userId") == user_id]
        if mine:
            embed.add_field(
                name="📌 내가 등록한 알림",
                value="\n".join(f"• {a['deviceName']}" for a in mine),
                inline=False,
            )
        else:
            embed.add_field(name="📌 내가 등록한 알림", value="없음 — `/알림` 으로 등록하세요.", inline=False)

    embed.set_footer(text="크래프톤 정글 스마트 세탁실 · Realtime LG ThinQ Data")
    return embed


@bot.tree.command(name="세탁기", description="세탁기 9대의 현재 상태를 확인합니다.")
async def cmd_washer_slash(interaction: discord.Interaction):
    await interaction.response.defer()
    await interaction.followup.send(embed=build_unit_list_embed("washer"))


@bot.tree.command(name="건조기", description="건조기 9대의 현재 상태를 확인합니다.")
async def cmd_dryer_slash(interaction: discord.Interaction):
    await interaction.response.defer()
    await interaction.followup.send(embed=build_unit_list_embed("dryer"))


@bot.tree.command(name="정보", description="봇 사용법과 알림 규칙을 확인합니다.")
async def cmd_info_slash(interaction: discord.Interaction):
    await interaction.response.defer()
    await interaction.followup.send(embed=build_info_embed(interaction.user.id))


# =========================================================
# 자연어 비서 (/비서) — "1번 세탁기 알림 걸어줘" 같은 말을 알아듣는다
# =========================================================
GEMINI_API_KEY = (os.environ.get("GEMINI_API_KEY") or "").strip()
# 앞에서부터 시도한다. 앞쪽이 더 똑똑하고, 뒤로 갈수록 가볍고 빠르다.
# (뒤쪽은 앞 모델이 혼잡할 때를 대비한 예비용이다)
GEMINI_MODELS = [
    "gemini-3.7-flash",
    "gemini-3.5-flash",
    "gemini-flash-latest",
    "gemini-flash-lite-latest",
]

# 사람별 대화 기억. 공용 채널에서 여러 명이 말해도 섞이면 안 되므로
# 반드시 사용자 ID 를 열쇠로 쓴다.
CHAT_HISTORY = {}
CHAT_TTL_SEC = 10 * 60      # 이보다 오래된 대화는 잊는다
CHAT_MAX_TURNS = 8          # 최근 8개만 기억 (토큰 절약)


def get_history(user_id):
    h = CHAT_HISTORY.get(user_id)
    if not h:
        return []
    if datetime.now().timestamp() - h.get("at", 0) > CHAT_TTL_SEC:
        CHAT_HISTORY.pop(user_id, None)
        return []
    return h.get("turns", [])


def push_history(user_id, role, text):
    if not text:
        return
    h = CHAT_HISTORY.setdefault(user_id, {"turns": [], "at": 0})
    h["turns"].append({"role": role, "parts": [{"text": text[:1500]}]})
    h["turns"] = h["turns"][-CHAT_MAX_TURNS:]
    h["at"] = datetime.now().timestamp()


def clear_history(user_id):
    CHAT_HISTORY.pop(user_id, None)
    LAST_CONTEXT.pop(user_id, None)

UNIT_WORDS = {"세탁기": "washer", "세탁": "washer", "건조기": "dryer", "건조": "dryer"}

# 웹의 에러 진단 가이드를 요약한 것. AI 가 원인과 조치까지 답할 수 있게 넘긴다.
ERROR_GUIDE = {
    "EMPTY_WATER_ALERT_ERROR": "건조기 자동 배수 이상. 워시타워는 물통 없는 직배수 구조라 후면 배수 호스가 꺾였거나 필터 먼지 과다일 때 발생. 호스 펴기 + 2중 먼지 필터 청소 후 재가동",
    "FILTER_CLEAN_ERROR": "건조기 2중 먼지 필터 막힘. 도어 안쪽 하단 필터 2개를 분리해 털고 미온수 세척, 완전히 말린 뒤 장착",
    "DRAIN_ERROR": "세탁기 배수 펌프 이상(OE). 좌측 하단 서비스 커버를 열고 잔수 제거 후 거름망 이물질 청소",
    "UNBALANCE_ERROR": "세탁물 뭉침(UE). 도어를 열고 한쪽으로 쏠린 옷감을 고르게 편 뒤 탈수 재시작",
    "DOOR_OPEN_ERROR": "도어 덜 닫힘(dE). 고무 패킹 틈에 낀 옷감을 확인하고 딸깍 소리가 나게 닫기",
}

# 웹 챗봇이 쓰는 세탁 지식을 요약한 것
LAUNDRY_GUIDE = (
    "[세탁 상식]\n"
    "- 데일리 빨래: 표준 + 터보샷(약 39분)\n"
    "- 수건/타월: 타월 코스 + 표준 건조. 섬유유연제 절대 금지(흡수력 저하·냄새 원인)\n"
    "- 운동복/기능성: 울·섬세 코스 찬물 + 저온 건조 (고온은 옷감 상함)\n"
    "- 담배/땀 냄새: 온수 40~60도 + 헹굼 3회 추가 + 고온 건조\n"
    "- 이불: 이불 코스(대용량)\n"
    "- 세탁조는 누적 30회마다 통살균 권장\n"
    "- 식초·구연산·베이킹소다 같은 민간요법은 공용 세탁기에 잔여물이 남으므로 권하지 말 것\n"
    "- 에티켓: 끝나면 즉시 수거, 건조 후 먼지 필터 털기"
)

# 사람별로 '방금 어떤 기기를 말했는지' 를 따로 기억한다.
# 공용 채널에서 여러 명이 동시에 말을 걸어도 서로 섞이면 안 되므로
# 반드시 사용자 ID 를 열쇠로 쓴다.
LAST_CONTEXT = {}
CONTEXT_TTL_SEC = 5 * 60   # 오래된 문맥은 버린다 (엉뚱한 기기를 건드리지 않도록)


def get_context(user_id):
    ctx = LAST_CONTEXT.get(user_id)
    if not ctx:
        return None
    if datetime.now().timestamp() - ctx.get("at", 0) > CONTEXT_TTL_SEC:
        LAST_CONTEXT.pop(user_id, None)
        return None
    return ctx


def set_context(user_id, tower_id, unit_type):
    LAST_CONTEXT[user_id] = {"towerId": tower_id, "unitType": unit_type,
                             "at": datetime.now().timestamp()}


def find_unit(status_data, tower_id, unit_type):
    """해당 기기의 현재 상태와 남은 시간을 돌려준다."""
    tower = next((t for t in TOWERS if t["id"] == tower_id), None)
    if not tower:
        return None
    unit = (status_data.get(tower["name"]) or {}).get(unit_type) or {}
    timer = unit.get("timer") or {}
    minutes = (timer.get("remainHour", 0) or 0) * 60 + (timer.get("remainMinute", 0) or 0)
    state = (unit.get("runState") or {}).get("currentState", "POWER_OFF")
    return {
        "tower": tower,
        "state": state,
        "minutes": minutes,
        "error": bool(unit.get("error")) or state == "ERROR",
        "name": f"{tower['label']} {'건조기' if unit_type == 'dryer' else '세탁기'}",
    }


def parse_by_rules(text, ctx=None):
    """API 를 쓰지 않고 알아들을 수 있는 문장은 여기서 바로 처리한다.
    (빠르고, 무료고, 결과가 항상 같다)"""
    t = text.replace(" ", "")

    if any(k in t for k in ("전부해제", "모두해제", "다해제", "전부취소", "모두취소", "다꺼", "전체해제")):
        return {"action": "cancel_all"}
    if any(k in t for k in ("내알림", "알림목록", "뭐걸었", "등록한알림")):
        return {"action": "list_alarms"}

    if any(k in t for k in ("뭐할수있", "무엇을할수있", "도움말", "사용법", "명령어", "어떻게써")):
        return {"action": "info"}
    if re.search(r"(세탁기|세탁).*(현황|상태|목록|보여|알려|있어|없어|남는|남았|비어|사용가능|쓸수있|가능한)", t) and not re.search(r"\d", t):
        return {"action": "unit_list", "unitType": "washer"}
    if re.search(r"(건조기|건조).*(현황|상태|목록|보여|알려|있어|없어|남는|남았|비어|사용가능|쓸수있|가능한)", t) and not re.search(r"\d", t):
        return {"action": "unit_list", "unitType": "dryer"}

    m = re.search(r"(\d+)\s*(?:번|호기|호)?\s*(세탁기|건조기|세탁|건조)", t)
    if m:
        tower_id = int(m.group(1))
        unit_type = UNIT_WORDS.get(m.group(2))
        if 1 <= tower_id <= 9 and unit_type:
            if any(k in t for k in ("해제", "취소", "꺼줘", "끄기", "끄고", "삭제")):
                return {"action": "cancel", "towerId": tower_id, "unitType": unit_type}
            if any(k in t for k in ("알림", "알람", "등록", "설정", "걸어", "켜")):
                return {"action": "register", "towerId": tower_id, "unitType": unit_type}
            return {"action": "unit_status", "towerId": tower_id, "unitType": unit_type}

    # 기기 번호 없이 이어서 말한 경우, 그 사람이 직전에 말한 기기를 쓴다.
    # (문맥은 사람별로 따로 보관하므로 다른 사람 요청과 섞이지 않는다)
    if ctx:
        if any(k in t for k in ("해제", "취소", "꺼줘", "끄기", "끄고", "삭제")):
            return {"action": "cancel", "towerId": ctx["towerId"], "unitType": ctx["unitType"], "fromContext": True}
        # 질문("알림 있어?")이 아니라 명령일 때만 등록한다
        if any(k in t for k in ("등록", "설정", "걸어", "걸어줘", "켜줘", "해줘", "알림해", "알람해")):
            return {"action": "register", "towerId": ctx["towerId"], "unitType": ctx["unitType"], "fromContext": True}
    return None


def ask_gemini(text, status_data, mine, history=None):
    """규칙으로 못 알아들은 문장을 Gemini 에게 물어 행동을 정한다."""
    if not GEMINI_API_KEY:
        return None

    lines = []
    for t in TOWERS:
        d = status_data.get(t["name"], {})
        cycle = ((d.get("washer") or {}).get("cycle") or {}).get("cycleCount", 0)
        for ut, label in (("washer", "세탁기"), ("dryer", "건조기")):
            u = d.get(ut) or {}
            st = (u.get("runState") or {}).get("currentState", "POWER_OFF")
            tm = u.get("timer") or {}
            mnt = (tm.get("remainHour", 0) or 0) * 60 + (tm.get("remainMinute", 0) or 0)
            err = u.get("error")

            part = f"{t['id']}번 {label}({t['zoneName']}): {STATE_LABELS.get(st, st)}"
            if mnt:
                part += f", {mnt}분 남음"
            if err or st == "ERROR":
                code = err or "UNKNOWN"
                part += f" | 에러코드 {code} — {ERROR_GUIDE.get(code, '점검 필요')}"
            if ut == "washer" and cycle:
                part += f" | 누적 {cycle}회" + ("[통살균 필요]" if cycle >= 30 else "")
            lines.append(part)

    system_text = (
        "너는 크래프톤 정글 기숙사 세탁실 봇이다. 사용자의 한국어 요청을 읽고 할 일을 정해라.\n\n"
        "[가능한 action]\n"
        "- register: 특정 기기 완료 5분 전 알림 등록 (towerId 1~9, unitType washer/dryer 필요)\n"
        "- cancel: 특정 기기 알림 해제\n"
        "- cancel_all: 내 알림 전부 해제\n"
        "- list_alarms: 내가 등록한 알림 목록\n"
        "- status: 세탁실 전체 현황\n"
        "- chat: 위 어디에도 해당하지 않음. reply 에 답을 직접 써라\n\n"
        "[지금 기기 상태]\n" + "\n".join(lines) + "\n\n"
        "[내가 등록한 알림]\n" + ("\n".join(f"- {a['deviceName']}" for a in mine) if mine else "없음") + "\n\n"
        + LAUNDRY_GUIDE + "\n\n"
        "에러가 난 기기를 물어보면 위에 적힌 에러코드 해설을 근거로 원인과 조치를 알려줘라.\n"
        "세탁 방법을 물어보면 위 세탁 상식을 근거로 답하고, action 은 chat 으로 둬라.\n"
        "reply 에는 사용자에게 보여줄 한국어 답변을 담아라. 필요하면 여러 줄로 써도 된다.\n"
        "이전 대화가 있으면 그 맥락을 이어서 이해해라. "
        "예를 들어 사용자가 앞서 3번 건조기를 말했고 이번에 '그거 해제해줘' 라고 하면 3번 건조기를 뜻한다."
    )

    contents = list(history or [])
    contents.append({"role": "user", "parts": [{"text": text}]})

    body = {
        "systemInstruction": {"parts": [{"text": system_text}]},
        "contents": contents,
        "generationConfig": {
            "temperature": 0.2,
            # 3.7 같은 상위 모델은 내부 추론에도 토큰을 쓴다.
            # 한도가 낮으면 JSON 이 중간에 잘려 파싱에 실패한다.
            "maxOutputTokens": 2048,
            "responseMimeType": "application/json",
            "responseSchema": {
                "type": "OBJECT",
                "properties": {
                    "action": {"type": "STRING",
                               "enum": ["register", "cancel", "cancel_all", "list_alarms", "status", "chat"]},
                    "towerId": {"type": "INTEGER"},
                    "unitType": {"type": "STRING", "enum": ["washer", "dryer"]},
                    "reply": {"type": "STRING"},
                },
                "required": ["action", "reply"],
            },
        },
    }

    for model in GEMINI_MODELS:
        try:
            req = urllib.request.Request(
                f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={GEMINI_API_KEY}",
                data=json.dumps(body).encode("utf-8"),
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=15) as res:
                data = json.loads(res.read().decode("utf-8"))
            raw = data["candidates"][0]["content"]["parts"][0]["text"].strip()
            # 일부 모델이 ```json ... ``` 로 감싸 보낸다. 그대로 파싱하면 실패한다.
            if raw.startswith("```"):
                raw = re.sub(r"^```[a-zA-Z]*\s*", "", raw)
                raw = re.sub(r"\s*```$", "", raw)
            return json.loads(raw)
        except Exception as e:
            print(f"[Gemini] {model} 실패: {e}")
    return None


async def run_assistant(user_id, text):
    """자연어 요청 하나를 처리한다. 항상 (보여줄 문장, embed 또는 None) 을 돌려준다."""
    result = await _run_assistant_inner(user_id, text)
    # 반환값 길이를 (문장, embed, 배치도필요) 세 개로 맞춘다
    text_out = result[0] if len(result) > 0 else ""
    embed_out = result[1] if len(result) > 1 else None
    board = result[2] if len(result) > 2 else False
    if text_out:
        push_history(user_id, "model", text_out)
    return text_out, embed_out, board


async def make_board_file():
    """배치도 이미지를 그려 첨부 파일로 만든다. 글보다 한눈에 들어온다."""
    try:
        status_data = await asyncio.to_thread(fetch_live_status)
        if not status_data:
            return None
        buf = await asyncio.to_thread(render_floorplan_image, status_data)
        return discord.File(buf, filename="floorplan.png")
    except Exception as e:
        print(f"[Board Error] {e}")
        return None


# 이 행동들에 대해서는 배치도 이미지를 함께 보낸다
BOARD_ACTIONS = ("unit_list", "status")


async def _run_assistant_inner(user_id, text):
    status_data = fetch_live_status()
    if not status_data:
        return "⚠️ 실시간 데이터를 가져오지 못했습니다. 잠시 후 다시 시도해 주세요.", None

    mine = [a for a in active_alarms if a.get("userId") == user_id]

    # 규칙으로 알아들을 수 있으면 API 를 쓰지 않는다 (빠르고 무료고 결과가 항상 같다)
    # "새로 시작" 같은 말이면 기억을 비운다
    if any(k in text.replace(" ", "") for k in ("대화초기화", "새로시작", "기억지워", "리셋")):
        clear_history(user_id)
        return "🧹 대화 기억을 지웠습니다. 처음부터 다시 말씀해 주세요.", None

    plan = parse_by_rules(text, get_context(user_id))
    if plan is None:
        plan = await asyncio.to_thread(ask_gemini, text, status_data, mine, get_history(user_id))
    if plan is None:
        return ("무슨 말씀인지 파악하지 못했습니다.\n"
                "-# 예) `3번 건조기 알림 걸어줘` · `내 알림 보여줘` · `전부 해제해줘`"), None

    # 다음 말에 맥락이 이어지도록 사람별로 기록해 둔다
    push_history(user_id, "user", text)

    action = plan.get("action")
    reply = (plan.get("reply") or "").strip()

    if action == "info":
        return "", build_info_embed(user_id)

    if action == "unit_list":
        # 글 목록 + 배치도 그림을 같이 준다 (한눈에 보이도록)
        return "", build_unit_list_embed(plan.get("unitType") or "washer"), True

    if action == "cancel_all":
        removed = len(mine)
        for a in mine:
            active_alarms.remove(a)
        if removed:
            save_alarms()
        return (f"🔕 알림 **{removed}개**를 모두 해제했습니다." if removed else "해제할 알림이 없습니다."), None

    if action == "list_alarms":
        if not mine:
            return "등록된 알림이 없습니다.\n-# `3번 세탁기 알림 걸어줘` 처럼 말해보세요.", None
        return "🔔 현재 등록된 알림\n" + "\n".join(f"• **{a['deviceName']}**" for a in mine), None

    if action in ("register", "cancel", "unit_status"):
        tower_id, unit_type = plan.get("towerId"), plan.get("unitType")
        if not tower_id or not unit_type:
            return (reply or "어떤 기기인지 알려주세요. 예) `3번 건조기 알림 걸어줘`"), None

        info = find_unit(status_data, tower_id, unit_type)
        if not info:
            return f"{tower_id}번 기기를 찾을 수 없습니다. (1~9번만 있습니다)", None

        # 다음 말("그거 해제해줘")을 위해 이 사람의 문맥으로 남긴다
        set_context(user_id, tower_id, unit_type)
        state_label = STATE_LABELS.get(info["state"], info["state"])


        if action == "unit_status":
            tail = f"**{info['minutes']}분** 남음" if info["minutes"] else "사용 가능"
            return f"**{info['name']}** · {state_label} · {tail}", None

        if action == "cancel":
            if not has_alarm(user_id, tower_id, unit_type):
                return f"**{info['name']}** 에는 걸어둔 알림이 없습니다.", None
            toggle_alarm_state(user_id, tower_id, unit_type, info["minutes"], info["name"])
            return f"🔕 **{info['name']}** 알림을 해제했습니다.", None

        if info["error"]:
            return f"⚠️ **{info['name']}** 는 지금 점검이 필요한 상태라 알림을 걸 수 없습니다.", None
        if info["minutes"] <= 0:
            return (f"**{info['name']}** 는 지금 가동 중이 아닙니다 ({state_label}).\n"
                    "-# 돌아가기 시작하면 그때 알림을 걸 수 있습니다."), None
        if has_alarm(user_id, tower_id, unit_type):
            return f"이미 **{info['name']}** 알림이 걸려 있습니다. (약 {info['minutes']}분 남음)", None

        toggle_alarm_state(user_id, tower_id, unit_type, info["minutes"], info["name"])
        return (f"🔔 **{info['name']}** 알림을 등록했습니다! (약 **{info['minutes']}분** 남음)\n"
                "-# 완료 5분 전 · 완료 시 · 오래 안 가져가면 수거 요청까지 DM 으로 보내드립니다."), None

    if action == "status":
        free = 0
        for t in TOWERS:
            for ut in ("washer", "dryer"):
                u = (status_data.get(t["name"]) or {}).get(ut) or {}
                if (u.get("runState") or {}).get("currentState", "POWER_OFF") in FREE_STATES:
                    free += 1
        head = (reply + "\n") if reply else ""
        return head + f"-# 지금 비어 있는 기기: **{free}대**", None, True

    return (reply or "무슨 말씀인지 파악하지 못했습니다."), None


@bot.tree.command(name="채널설정", description="이 채널에서 멘션 없이 봇과 대화할 수 있게 합니다. (다시 누르면 해제)")
async def cmd_set_channel(interaction: discord.Interaction):
    if interaction.guild is None:
        await interaction.response.send_message(
            "DM 에서는 따로 설정하지 않아도 언제든 그냥 말을 걸면 됩니다.", ephemeral=True)
        return

    cid = str(interaction.channel_id)
    if cid in assistant_channels:
        assistant_channels.discard(cid)
        save_settings()
        await interaction.response.send_message(
            "🔕 이 채널에서 **멘션 없이 대화하는 기능을 껐습니다.**\n"
            "-# `@봇` 으로 부르거나 DM 은 계속 됩니다.")
        return

    assistant_channels.add(cid)
    save_settings()

    msg = ("🗣️ 이제 이 채널에서는 **멘션 없이 그냥 말을 걸어도** 답합니다!\n"
           "-# 예) `남는 세탁기 있어?` · `3번 건조기 알림 걸어줘`\n"
           "-# 다시 `/채널설정` 을 누르면 해제됩니다.")
    if not intents.message_content:
        msg += ("\n\n⚠️ **다만 지금은 동작하지 않습니다.**\n"
                "메시지 내용을 읽을 권한이 꺼져 있습니다. 다음 두 가지가 필요합니다.\n"
                "1. Discord 개발자 포털 → Bot → **MESSAGE CONTENT INTENT** 켜기\n"
                "2. 환경변수 `ENABLE_MESSAGE_CONTENT=1` 설정 후 재시작\n"
                "-# 그때까지는 `@봇` 멘션이나 DM 을 이용해 주세요.")
    await interaction.response.send_message(msg)


@bot.tree.command(name="비서", description="말로 알림을 걸 수 있어요. 예) 3번 건조기 알림 걸어줘")
@app_commands.describe(말="예) 3번 건조기 알림 걸어줘 / 내 알림 보여줘 / 전부 해제해줘")
async def cmd_assistant(interaction: discord.Interaction, 말: str):
    await interaction.response.defer(ephemeral=True)
    try:
        result, embed, board = await run_assistant(interaction.user.id, 말)
    except Exception as e:
        print(f"[Assistant Error] {e}")
        result, embed, board = "⚠️ 처리 중 문제가 발생했습니다. 잠시 후 다시 시도해 주세요.", None, False
    header = f"> {말}"
    kwargs = {"ephemeral": True}
    if board:
        board_file = await make_board_file()
        if board_file is not None:
            kwargs["file"] = board_file
    if embed is not None:
        await interaction.followup.send(content=header, embed=embed, **kwargs)
    else:
        await interaction.followup.send(header + "\n\n" + result, **kwargs)


@bot.tree.command(name="내알림", description="내가 등록한 알림을 확인하고 켜거나 끕니다.")
async def cmd_myalarm_slash(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    status_data = fetch_live_status()
    values = [o.value for o in get_running_options(status_data)] if status_data else []
    await interaction.followup.send(
        view=MyAlarmPanel(interaction.user.id, values),
        ephemeral=True,
    )


# =========================================================
# 슬래시 명령어 (/알림) & 접두사 명령어 (!알림) 동시 지원
# =========================================================
@bot.tree.command(name="알림", description="실시간 세탁실 현실 배치도를 확인하고 가동 중인 기기 5분 전 DM 알림을 등록합니다.")
async def cmd_alarm_slash(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=False)
    status_data = fetch_live_status()
    running_options = get_running_options(status_data)

    img_buf = render_floorplan_image(status_data)
    discord_file = discord.File(img_buf, filename="floorplan.png")
    embed = build_floorplan_embed()

    if not running_options:
        embed.add_field(
            name="💡 알림 등록 안내",
            value="현재 세탁실에 가동 중인 세탁기/건조기가 없습니다. (모든 기기가 대기 중이거나 완료 상태입니다)",
            inline=False
        )
        await interaction.followup.send(file=discord_file, embed=embed)
    else:
        view = LaundryFloorplanView(running_options[:25])
        await interaction.followup.send(file=discord_file, embed=embed, view=view)

# =========================================================
# 백그라운드 태스크: 10초마다 실시간 센서 감시 & DM 발송
# =========================================================
@tasks.loop(seconds=10)
async def check_laundry_alarms():
    if not active_alarms:
        return

    status_data = fetch_live_status()
    if not status_data:
        return

    changed = False
    to_remove = []

    now_ts = datetime.now().timestamp()

    for item in list(active_alarms):
        tower = next((t for t in TOWERS if t["id"] == item["towerId"]), None)
        if not tower:
            continue

        # 한 사이클은 길어야 2시간이다. 그보다 오래 남아있는 등록은
        # 완료 판정을 놓친 것이므로 정리한다. (안 그러면 다음 사람 빨래에 울린다)
        created = item.get("createdAt") or 0
        if not created:
            item["createdAt"] = now_ts
            changed = True
        elif now_ts - created > MAX_ALARM_AGE_SEC:
            print(f"[Alarm] 오래된 알림 정리: {item.get('deviceName', '?')}")
            to_remove.append(item)
            continue

        data = status_data.get(tower["name"], {})
        unit_data = data.get("dryer", {}) if item["unitType"] == "dryer" else data.get("washer", {})
        timer = unit_data.get("timer", {})
        run_state = unit_data.get("runState", {}).get("currentState", "POWER_OFF")
        
        remain_min = (timer.get("remainHour", 0) * 60) + timer.get("remainMinute", 0)
        is_error = run_state == "ERROR" or bool(unit_data.get("error"))

        user = bot.get_user(item["userId"])
        if not user:
            try:
                user = await bot.fetch_user(item["userId"])
            except Exception:
                user = None

        # 🚨 1) 가동 중 에러/중단 발생 시 즉시 알림
        if is_error and not item.get("notifiedError"):
            item["notifiedError"] = True
            changed = True
            if user:
                try:
                    await user.send(
                        f"🚨 **[긴급 점검: {item['deviceName']}]** 세탁/건조 중단 오류가 발생했습니다!\n"
                        f"• 기기 동작이 멈췄으니 세탁실에서 기기 상태(도어 닫힘/배수관)를 확인해 주세요!"
                    )
                except Exception as e:
                    print(f"[DM Send Error] {e}")

        # 🔔 2) 5분 이하 남았을 때 5분 전 알림
        if remain_min <= 5 and remain_min > 0 and not item.get("notified5Min"):
            item["notified5Min"] = True
            changed = True
            if user:
                try:
                    await user.send(
                        f"🧺 **[5분 전 알림] {item['deviceName']}** 가동이 약 **5분 뒤** 완료됩니다!\n"
                        f"👉 빨래 바구니를 챙겨 세탁실로 이동할 준비를 해주세요! 🏃💨"
                    )
                except Exception as e:
                    print(f"[DM Send Error] {e}")

        # 🏁 3) 완료되었을 때 (0분 또는 완료 상태)
        if (remain_min == 0 or run_state in ('COMPLETE', 'POWER_OFF', 'WRINKLE_CARE')) and not item.get("notified0Min"):
            item["notified0Min"] = True
            item["completedAt"] = now_ts
            changed = True
            # 여기서 알림을 지우지 않는다. 실제로 빨래를 가져갔는지 계속 지켜본다.
            if user:
                try:
                    await user.send(
                        f"🏁 **[세탁 완료] {item['deviceName']}** 가동이 모두 끝났습니다!\n"
                        f"👉 다음 정글러를 위해 세탁실에서 빨래를 즉시 수거해 주세요! 🫧"
                    )
                except Exception as e:
                    print(f"[DM Send Error] {e}")
            continue

        # 🚨 4) 완료된 뒤에도 안 가져갔을 때 수거 요청
        if item.get("notified0Min"):
            # 기기가 다시 돌기 시작했다 = 누군가 꺼내고 새로 돌렸다는 뜻 -> 감시 종료
            if run_state in STARTED_STATES:
                to_remove.append(item)
                continue

            if item.get("notifiedStale"):
                to_remove.append(item)
                continue

            completed = item.get("completedAt") or 0
            if not completed:
                item["completedAt"] = now_ts
                changed = True
                continue

            waited = now_ts - completed
            if waited >= STALE_PICKUP_SEC:
                item["notifiedStale"] = True
                changed = True
                to_remove.append(item)
                mins = int(waited // 60)
                print(f"[Alarm] 방치 감지: {item.get('deviceName', '?')} (완료 후 {mins}분 경과)")
                if user:
                    try:
                        await user.send(
                            f"🚨 **[수거 요청] {item['deviceName']}** 빨래가 아직 그대로 있어요!\n"
                            f"👉 가동이 끝난 지 **{mins}분**이 지났습니다. 다음 정글러를 위해 빨래를 수거해 주세요! 🧺"
                        )
                    except Exception as e:
                        print(f"[DM Send Error] {e}")
            continue

    # 완료된 알림 제거
    if to_remove:
        for r in to_remove:
            if r in active_alarms:
                active_alarms.remove(r)
        changed = True

    if changed:
        save_alarms()

@check_laundry_alarms.before_loop
async def before_alarm_loop():
    await bot.wait_until_ready()

# =========================================================
# 봇 준비 완료 이벤트 (Slash Command 즉시 동기화)
# =========================================================
# =========================================================
# 그냥 말 걸기 (멘션 / DM / 지정 채널)
#
# 디스코드는 특권 인텐트가 없어도 아래 두 경우에는 메시지 내용을 준다.
#   1) 봇을 멘션한 메시지   2) 봇과의 DM
# 그래서 멘션과 DM 은 추가 설정 없이 바로 동작한다.
# 멘션 없이 채널에 그냥 쓴 말까지 읽으려면 개발자 포털에서
# MESSAGE CONTENT INTENT 를 켜고 ENABLE_MESSAGE_CONTENT=1 을 줘야 한다.
# =========================================================
SETTINGS_FILE = os.path.join(BASE_DIR, "bot_settings.json")

# 멘션 없이 대화할 채널 목록. /채널설정 으로 디스코드 안에서 바꾼다.
# (환경변수로도 기본값을 줄 수 있지만, 그건 바꿀 때마다 재배포가 필요하다)
assistant_channels = set()


def load_settings():
    global assistant_channels
    found = set()
    env_default = (os.environ.get("ASSISTANT_CHANNEL_ID") or "").strip()
    if env_default:
        found.add(env_default)
    try:
        if os.path.exists(SETTINGS_FILE):
            with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            found.update(str(c) for c in data.get("assistantChannels", []))
    except Exception as e:
        print(f"[Settings Load Error] {e}")
    assistant_channels = found


def save_settings():
    try:
        tmp = SETTINGS_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"assistantChannels": sorted(assistant_channels)}, f, ensure_ascii=False, indent=2)
        os.replace(tmp, SETTINGS_FILE)
    except Exception as e:
        print(f"[Settings Save Error] {e}")


def strip_mention(content, me):
    for token in (f"<@{me.id}>", f"<@!{me.id}>"):
        content = content.replace(token, " ")
    return content.strip()


@bot.event
async def on_message(message: discord.Message):
    # 봇 자신과 다른 봇의 말은 무시한다 (서로 무한 응답하는 것을 막는다)
    if message.author.bot:
        return

    is_dm = message.guild is None
    mentioned = bot.user is not None and bot.user in message.mentions
    in_assistant_channel = str(message.channel.id) in assistant_channels

    # 아무 말에나 끼어들지 않는다. 말을 건 경우에만 답한다.
    if not (is_dm or mentioned or in_assistant_channel):
        return

    text = strip_mention(message.content or "", bot.user) if mentioned else (message.content or "").strip()

    if not text:
        return

    try:
        async with message.channel.typing():
            result, embed, board = await run_assistant(message.author.id, text)
        # 공용 채널에서는 여러 명이 동시에 말을 걸 수 있으므로
        # 누구에게 하는 답인지 이름을 붙여 헷갈리지 않게 한다.
        who = "" if is_dm else f"**{message.author.display_name}**님, "
        kwargs = {"mention_author": False}
        if board:
            board_file = await make_board_file()
            if board_file is not None:
                kwargs["file"] = board_file
        if embed is not None:
            await message.reply(content=(who.strip() or None), embed=embed, **kwargs)
        else:
            await message.reply(who + result, **kwargs)
    except discord.Forbidden:
        pass
    except Exception as e:
        print(f"[on_message Error] {e}")
        try:
            await message.reply("⚠️ 처리 중 문제가 발생했습니다. 잠시 후 다시 시도해 주세요.", mention_author=False)
        except Exception:
            pass


@bot.event
async def on_ready():
    load_alarms()
    load_settings()
    if assistant_channels:
        print(f"[Settings] 대화 채널 {len(assistant_channels)}개 등록됨")
    print(f"🤖 [Discord Bot] {bot.user.name}#{bot.user.discriminator} (ID: {bot.user.id}) 로그인 성공!")

    # 어느 서버에 들어가 있는지 분명히 남긴다.
    # 0개면 초대가 안 된 것이다 (DM 은 이전 대화방이 남아 있어 계속 동작할 수 있다).
    if bot.guilds:
        print(f"🏠 [Guilds] {len(bot.guilds)}개 서버: " + ", ".join(g.name for g in bot.guilds))
    else:
        print("=" * 60)
        print("⚠️ [Guilds] 봇이 들어가 있는 서버가 없습니다!")
        print("   OAuth2 초대 링크로 서버에 추가해야 합니다.")
        print("   scope 에 bot 과 applications.commands 가 모두 있어야 슬래시 명령어가 보입니다.")
        print("=" * 60)
    
    # 1) 봇이 속한 모든 서버에 1초 만에 즉시 슬래시 명령어 복사 및 동기화 (0초 딜레이)
    for guild in bot.guilds:
        try:
            bot.tree.copy_global_to(guild=guild)
            await bot.tree.sync(guild=guild)
            print(f"✅ [Instant Sync] '{guild.name}' 서버에 슬래시 커맨드(/알림) 즉시 등록 완료!")
        except Exception as e:
            print(f"⚠️ [Guild Sync] {guild.name}: {e}")

    # 2) 글로벌 동기화도 실행
    try:
        synced = await bot.tree.sync()
        print(f"✅ [Slash Commands] {len(synced)}개 글로벌 슬래시 명령어 동기화 완료! (/알림)")
    except Exception as e:
        print(f"❌ [Command Sync Error] {e}")

    if not check_laundry_alarms.is_running():
        check_laundry_alarms.start()
        print("⏰ [Alarm Daemon] 10초 주기 실시간 세탁실 센서 감시 루프 가동 시작!")

async def start_bot_with_backoff():
    delay = 15
    while True:
        try:
            print("🤖 [Discord Bot] Discord Gateway 연결 시도 중...")
            await bot.start(DISCORD_BOT_TOKEN)

        except discord.errors.PrivilegedIntentsRequired:
            # 개발자 포털에서 MESSAGE CONTENT INTENT 를 켜지 않은 채
            # ENABLE_MESSAGE_CONTENT=1 을 준 경우다.
            # 이대로 두면 15초마다 영원히 재시작만 반복하므로,
            # 그 기능을 끄고 스스로 다시 켜서 멘션/DM 만이라도 살린다.
            print("=" * 60)
            print("⚠️ [인텐트 오류] MESSAGE CONTENT INTENT 가 꺼져 있습니다.")
            print("   Discord 개발자 포털 > Bot > MESSAGE CONTENT INTENT 를 켜야")
            print("   멘션 없이 채널에서 대화하는 기능을 쓸 수 있습니다.")
            print("   지금은 그 기능 없이 다시 시작합니다. (멘션과 DM 은 정상 동작)")
            print("=" * 60)
            os.environ["ENABLE_MESSAGE_CONTENT"] = "0"
            await bot.close()
            os.execv(sys.executable, [sys.executable] + sys.argv)

        except discord.errors.LoginFailure:
            print("=" * 60)
            print("❌ [토큰 오류] 봇 토큰이 올바르지 않습니다. 재시도하지 않고 종료합니다.")
            print("   DISCORD_BOT_TOKEN 환경변수를 확인해 주세요.")
            print("=" * 60)
            return

        except discord.errors.HTTPException as e:
            if e.status == 429:
                print(f"⚠️ [Discord Rate Limit] 디스코드 API 글로벌 요청 제한(429) 감지. {delay}초 후 자동 재시도합니다...")
                await asyncio.sleep(delay)
                delay = min(delay * 2, 120)
            else:
                print(f"❌ [Discord HTTP Error] {e} ({delay}초 후 재시도)")
                await asyncio.sleep(delay)
        except Exception as e:
            print(f"❌ [Discord Error] {e} (15초 후 재시도)")
            await asyncio.sleep(15)

if __name__ == "__main__":
    if not DISCORD_BOT_TOKEN:
        print("=" * 60)
        print("❌ [오류] DISCORD_BOT_TOKEN 환경 변수가 설정되지 않았습니다.")
        print("👉 Discord Developer Portal에서 봇 토큰을 발급받아 환경 변수로 설정해 주세요.")
        print("   실행 예: $env:DISCORD_BOT_TOKEN='YOUR_TOKEN_HERE'; python discord_bot.py")
        print("=" * 60)
    else:
        asyncio.run(start_bot_with_backoff())
