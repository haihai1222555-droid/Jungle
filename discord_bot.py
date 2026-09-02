import os
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
bot = commands.Bot(command_prefix="!", intents=intents)

# =========================================================
# 현실 세탁실 초고화질 카드 뷰 이미지 렌더러 (Web UI 100% 동일)
# =========================================================
def render_floorplan_image(status_data):
    MARGIN, GAP = 35, 25
    W = 2000
    CARD_H = 330
    ROW1_Y, ROW2_Y = 168, 573
    H = ROW2_Y + CARD_H + MARGIN

    usable = W - MARGIN * 2
    CARD_W5 = (usable - GAP * 4) // 5   # 1열: 5장
    CARD_W4 = (usable - GAP * 3) // 4   # 2열: 4장 (폭을 꽉 채운다)

    img = Image.new("RGB", (W, H), color=(11, 15, 25))
    draw = ImageDraw.Draw(img)

    f_header = get_font(32, bold=True)
    f_sub = get_font(22, bold=False)
    f_sec_title = get_font(26, bold=True)
    f_card_num = get_font(28, bold=True)
    f_card_tag = get_font(18, bold=True)
    f_unit_title = get_font(20, bold=False)
    f_unit_state = get_font(22, bold=True)
    f_unit_time = get_font(26, bold=True)
    f_badge = get_font(18, bold=True)

    def text_w(txt, font):
        b = draw.textbbox((0, 0), txt, font=font)
        return b[2] - b[0]

    # ── 헤더 ──
    draw.rounded_rectangle([(MARGIN, 25), (W - MARGIN, 95)], radius=12, fill=(17, 24, 39))
    draw.text((MARGIN + 25, 42), "크래프톤 정글 스마트 세탁실 현실 배치도", fill=(255, 255, 255), font=f_header)

    # 범례 (오른쪽 정렬로 계산해 겹치지 않게)
    legend = [((107, 114, 128), "대기 중"), ((16, 185, 129), "작동 중"),
              ((245, 158, 11), "건조 중"), ((239, 68, 68), "점검 필요")]
    lx = W - MARGIN - 25
    for col, label in reversed(legend):
        lw = text_w(label, f_sub)
        draw.text((lx - lw, 47), label, fill=(156, 163, 175), font=f_sub)
        draw.ellipse([(lx - lw - 30, 52), (lx - lw - 12, 70)], fill=col)
        lx -= lw + 30 + 32

    def draw_card(t, x, y, cw):
        data = status_data.get(t["name"], {})
        d = data.get("dryer", {})
        w = data.get("washer", {})

        d_state = d.get("runState", {}).get("currentState", "POWER_OFF")
        w_state = w.get("runState", {}).get("currentState", "POWER_OFF")
        d_min = (d.get("timer", {}).get("remainHour", 0) * 60) + d.get("timer", {}).get("remainMinute", 0)
        w_min = (w.get("timer", {}).get("remainHour", 0) * 60) + w.get("timer", {}).get("remainMinute", 0)
        d_err = d.get("error") or (d_state == "ERROR")
        w_err = w.get("error") or (w_state == "ERROR")

        if d_err or w_err:
            border_col, status_text, status_bg = (239, 68, 68), "점검 필요", (127, 29, 29)
        elif d_min > 0 and w_min > 0:
            border_col, status_text, status_bg = (16, 185, 129), "전체 가동 중", (6, 95, 70)
        elif d_min > 0:
            border_col, status_text, status_bg = (245, 158, 11), "건조 가동 중", (120, 53, 15)
        elif w_min > 0:
            border_col, status_text, status_bg = (59, 130, 246), "세탁 가동 중", (30, 58, 138)
        else:
            border_col, status_text, status_bg = (55, 65, 81), "전체 대기 중", (31, 41, 55)

        draw.rounded_rectangle([(x, y), (x + cw, y + CARD_H)], radius=16,
                               fill=(17, 24, 39), outline=border_col, width=3)

        draw.text((x + 20, y + 16), t["label"], fill=(255, 255, 255), font=f_card_num)

        z_col = (59, 130, 246) if "남성" in t["zoneName"] else ((168, 85, 247) if "공용" in t["zoneName"] else (236, 72, 153))
        zw = text_w(t["zoneName"], f_card_tag)
        draw.rounded_rectangle([(x + 90, y + 18), (x + 90 + zw + 20, y + 46)], radius=6,
                               fill=(z_col[0] // 4, z_col[1] // 4, z_col[2] // 4), outline=z_col, width=2)
        draw.text((x + 100, y + 21), t["zoneName"], fill=z_col, font=f_card_tag)

        sw = text_w(status_text, f_badge)
        draw.rounded_rectangle([(x + cw - sw - 38, y + 16), (x + cw - 18, y + 46)], radius=6, fill=status_bg)
        draw.text((x + cw - sw - 28, y + 21), status_text, fill=(255, 255, 255), font=f_badge)

        draw.line([(x + 14, y + 62), (x + cw - 14, y + 62)], fill=(31, 41, 55), width=2)

        def draw_unit(uy, name, unit, state, minutes, err, is_dryer):
            """기기 한 칸. 1행 [이름 ... 남은시간] / 2행 [상태] [코스] 로 나눠 겹침을 없앤다."""
            if err:
                dot, state_col, state_txt = (239, 68, 68), (239, 68, 68), "기기 점검/에러"
            elif minutes > 0:
                dot = (245, 158, 11) if is_dryer else (59, 130, 246)
                state_col = (245, 158, 11) if is_dryer else (96, 165, 250)
                state_txt = "작동 중"
            else:
                dot, state_col, state_txt = (55, 65, 81), (107, 114, 128), "대기 중 (사용 가능)"

            if err or minutes > 0:
                draw.ellipse([(x + 20, uy + 8), (x + 52, uy + 40)], fill=dot,
                             outline=(254, 202, 202) if err else (255, 255, 255), width=2)
            else:
                draw.ellipse([(x + 20, uy + 8), (x + 52, uy + 40)], fill=dot)

            # 1행: 기기 이름 + 남은 시간(오른쪽)
            draw.text((x + 65, uy + 2), name, fill=(156, 163, 175), font=f_unit_title)
            if minutes > 0:
                time_txt = format_timer(unit.get("timer", {}).get("remainHour", 0),
                                        unit.get("timer", {}).get("remainMinute", 0))
                tcol = (239, 68, 68) if err else (255, 255, 255)
                draw.text((x + cw - text_w(time_txt, f_unit_time) - 22, uy - 2), time_txt, fill=tcol, font=f_unit_time)
            else:
                idle = "대기 중"
                draw.text((x + cw - text_w(idle, f_unit_state) - 22, uy + 2), idle, fill=(107, 114, 128), font=f_unit_state)

            # 2행: 상태
            draw.text((x + 65, uy + 30), state_txt, fill=state_col, font=f_unit_state)

            # 3행: 에러 안내 또는 코스 뱃지
            if err:
                msg = ("건조기" if is_dryer else "세탁기") + " 배수관 점검 필요"
                draw.rounded_rectangle([(x + 20, uy + 66), (x + cw - 20, uy + 96)], radius=6,
                                       fill=(127, 29, 29), outline=(239, 68, 68), width=1)
                draw.text((x + 35, uy + 70), msg, fill=(254, 202, 202), font=f_badge)
            elif minutes > 0:
                course = "표준 건조" if is_dryer else "표준 세탁"
                bw = text_w(course, f_badge)
                draw.rounded_rectangle([(x + 65, uy + 66), (x + 65 + bw + 24, uy + 96)], radius=6,
                                       fill=(31, 41, 55), outline=(75, 85, 99), width=1)
                draw.text((x + 77, uy + 70), course, fill=(209, 213, 219), font=f_badge)

        draw_unit(y + 78, "건조기", d, d_state, d_min, d_err, True)
        draw.line([(x + 14, y + 195), (x + cw - 14, y + 195)], fill=(31, 41, 55), width=2)
        draw_unit(y + 210, "세탁기", w, w_state, w_min, w_err, False)

    def section_title(y, box_w, fill_bg, chip_cols, text, text_col):
        draw.rounded_rectangle([(MARGIN, y), (MARGIN + box_w, y + 40)], radius=8, fill=fill_bg)
        cx = MARGIN + 15
        for c in chip_cols:   # 이모지 대신 실제로 그려지는 색 사각형을 쓴다
            draw.rounded_rectangle([(cx, y + 12), (cx + 16, y + 28)], radius=3, fill=c)
            cx += 24
        draw.text((cx, y + 6), text, fill=text_col, font=f_sec_title)

    section_title(115, 320, (30, 58, 138), [(59, 130, 246)],
                  "남성 구역 (No.1 ~ No.5)", (191, 219, 254))
    for idx, t in enumerate(TOWERS[:5]):
        draw_card(t, MARGIN + idx * (CARD_W5 + GAP), ROW1_Y, CARD_W5)

    section_title(520, 560, (88, 28, 135), [(168, 85, 247), (236, 72, 153)],
                  "공용 (No.6~7) & 여성 구역 (No.8~9)", (233, 213, 255))
    for idx, t in enumerate(TOWERS[5:]):
        draw_card(t, MARGIN + idx * (CARD_W4 + GAP), ROW2_Y, CARD_W4)

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
class AlarmToggleButton(discord.ui.Button):
    def __init__(self, user_id, option_value, row):
        tower_id, unit_type, remain_min, device_name = parse_option_value(option_value)
        on = has_alarm(user_id, tower_id, unit_type)
        super().__init__(
            label=device_name,
            emoji="🔔" if on else "🔕",
            style=discord.ButtonStyle.success if on else discord.ButtonStyle.secondary,
            row=row,
        )
        self.user_id = user_id
        self.option_value = option_value

    async def callback(self, interaction: discord.Interaction):
        tower_id, unit_type, remain_min, device_name = parse_option_value(self.option_value)
        turned_on = toggle_alarm_state(self.user_id, tower_id, unit_type, remain_min, device_name)

        if turned_on:
            try:
                await interaction.user.send(
                    f"🔔 **[정글 스마트 세탁실]** `{device_name}` 알림이 등록되었습니다!\n"
                    f"• 현재 잔여 시간: **약 {remain_min}분**\n"
                    f"• 완료 **5분 전**, **완료 시**, 그리고 오래 안 가져가면 **수거 요청**까지 DM 으로 알려드립니다. 🧺"
                )
            except Exception:
                pass

        # 버튼 아이콘이 바로 바뀌도록 패널을 그 자리에서 다시 그린다
        view = MyAlarmPanel(self.user_id, self.view.option_values)
        await interaction.response.edit_message(embed=build_my_panel_embed(self.user_id), view=view)


class MyAlarmPanel(discord.ui.View):
    def __init__(self, user_id, option_values):
        super().__init__(timeout=180)
        self.option_values = option_values
        # 디스코드 제한: 한 메시지에 버튼 25개(5행 x 5개)
        for i, val in enumerate(option_values[:25]):
            self.add_item(AlarmToggleButton(user_id, val, row=i // 5))


def build_my_panel_embed(user_id):
    mine = [a for a in active_alarms if a.get("userId") == user_id]
    if mine:
        body = "\n".join(f"🔔 **{a['deviceName']}**" for a in mine)
    else:
        body = "아직 등록한 알림이 없습니다."
    return discord.Embed(
        title="🔔 내 알림 관리",
        description=(
            f"{body}\n\n"
            "아래 버튼으로 켜고 끌 수 있습니다.\n"
            "🔔 초록 = 등록됨 · 🔕 회색 = 꺼짐\n"
            "*이 메시지는 나에게만 보입니다.*"
        ),
        color=discord.Color.from_rgb(16, 185, 129),
    )


class OpenMyAlarmButton(discord.ui.Button):
    def __init__(self, option_values):
        super().__init__(label="내 알림 관리", emoji="🔔", style=discord.ButtonStyle.primary)
        self.option_values = option_values

    async def callback(self, interaction: discord.Interaction):
        uid = interaction.user.id
        await interaction.response.send_message(
            embed=build_my_panel_embed(uid),
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
            "`/세탁기` · 세탁기 9대 현황\n"
            "`/건조기` · 건조기 9대 현황\n"
            "`/정보` · 이 안내\n"
            "*( `!알림` 처럼 `!` 로도 씁니다 )*"
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


@bot.command(name="세탁기", aliases=["washer"])
async def cmd_washer_prefix(ctx):
    await ctx.send(embed=build_unit_list_embed("washer"))


@bot.command(name="건조기", aliases=["dryer"])
async def cmd_dryer_prefix(ctx):
    await ctx.send(embed=build_unit_list_embed("dryer"))


@bot.command(name="정보", aliases=["도움말", "help2", "info"])
async def cmd_info_prefix(ctx):
    await ctx.send(embed=build_info_embed(ctx.author.id))


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

@bot.command(name="알림", aliases=["세탁", "세탁실", "laundry"])
async def cmd_alarm_prefix(ctx):
    """디스코드 채팅창에 !알림 또는 !세탁실 입력 시에도 동작"""
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
        await ctx.send(file=discord_file, embed=embed)
    else:
        view = LaundryFloorplanView(running_options[:25])
        await ctx.send(file=discord_file, embed=embed, view=view)

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
@bot.event
async def on_ready():
    load_alarms()
    print(f"🤖 [Discord Bot] {bot.user.name}#{bot.user.discriminator} (ID: {bot.user.id}) 로그인 성공!")
    
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
