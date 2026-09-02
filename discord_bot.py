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

# 가동 중인 상태 목록
RUNNING_STATES = ('RUNNING', 'WASHING', 'RINSING', 'SPINNING', 'DRYING', 'COOLING')

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
# 현실 세탁실 고화질 카드 뷰 이미지 렌더러 (Web UI와 100% 동일)
# =========================================================
def render_floorplan_image(status_data):
    W, H = 1200, 680
    img = Image.new("RGB", (W, H), color=(11, 15, 25))
    draw = ImageDraw.Draw(img)

    f_title = get_font(18, bold=True)
    f_sub = get_font(13, bold=False)
    f_sec_title = get_font(15, bold=True)
    f_card_num = get_font(16, bold=True)
    f_card_tag = get_font(11, bold=True)
    f_unit_title = get_font(12, bold=False)
    f_unit_state = get_font(13, bold=True)
    f_unit_time = get_font(16, bold=True)
    f_badge = get_font(11, bold=True)

    # 1. Header Bar
    draw.rounded_rectangle([(20, 15), (W - 20, 58)], radius=8, fill=(17, 24, 39))
    draw.text((35, 24), "🧺 크래프톤 정글 스마트 세탁실 현실 배치도", fill=(255, 255, 255), font=f_title)
    
    # Legend
    draw.ellipse([(W - 460, 31), (W - 450, 41)], fill=(107, 114, 128))
    draw.text((W - 445, 28), "대기 중", fill=(156, 163, 175), font=f_sub)

    draw.ellipse([(W - 370, 31), (W - 360, 41)], fill=(16, 185, 129))
    draw.text((W - 355, 28), "작동 중", fill=(156, 163, 175), font=f_sub)

    draw.ellipse([(W - 280, 31), (W - 270, 41)], fill=(245, 158, 11))
    draw.text((W - 265, 28), "건조 중", fill=(156, 163, 175), font=f_sub)

    draw.ellipse([(W - 190, 31), (W - 180, 41)], fill=(239, 68, 68))
    draw.text((W - 175, 28), "점검 필요", fill=(156, 163, 175), font=f_sub)

    card_w = 220
    card_h = 245
    gap = 15

    def draw_card(t, x, y):
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
            border_col = (239, 68, 68)
            status_text = "점검 필요"
            status_bg = (127, 29, 29)
        elif d_min > 0 and w_min > 0:
            border_col = (16, 185, 129)
            status_text = "전체 가동 중"
            status_bg = (6, 95, 70)
        elif d_min > 0:
            border_col = (245, 158, 11)
            status_text = "건조 가동 중"
            status_bg = (120, 53, 15)
        elif w_min > 0:
            border_col = (59, 130, 246)
            status_text = "세탁 가동 중"
            status_bg = (30, 58, 138)
        else:
            border_col = (55, 65, 81)
            status_text = "전체 대기 중"
            status_bg = (31, 41, 55)

        draw.rounded_rectangle([(x, y), (x + card_w, y + card_h)], radius=10, fill=(17, 24, 39), outline=border_col, width=2)
        draw.text((x + 12, y + 10), t["label"], fill=(255, 255, 255), font=f_card_num)
        
        z_col = (59, 130, 246) if "남성" in t["zoneName"] else ((168, 85, 247) if "공용" in t["zoneName"] else (236, 72, 153))
        draw.rounded_rectangle([(x + 58, y + 11), (x + 112, y + 27)], radius=4, fill=(z_col[0]//4, z_col[1]//4, z_col[2]//4), outline=z_col, width=1)
        draw.text((x + 63, y + 13), t["zoneName"], fill=z_col, font=f_card_tag)

        badge_w = 72
        draw.rounded_rectangle([(x + card_w - badge_w - 10, y + 9), (x + card_w - 10, y + 27)], radius=4, fill=status_bg)
        draw.text((x + card_w - badge_w - 2, y + 12), status_text, fill=(255, 255, 255), font=f_badge)

        draw.line([(x + 8, y + 36), (x + card_w - 8, y + 36)], fill=(31, 41, 55), width=1)

        # 건조기
        d_y = y + 44
        if d_err:
            draw.ellipse([(x + 12, d_y + 4), (x + 32, d_y + 24)], fill=(239, 68, 68), outline=(254, 202, 202), width=1)
            draw.text((x + 40, d_y + 2), "건조기", fill=(156, 163, 175), font=f_unit_title)
            draw.text((x + 40, d_y + 17), "기기 점검/에러", fill=(239, 68, 68), font=f_unit_state)
            time_txt = format_timer(d.get("timer", {}).get("remainHour", 0), d.get("timer", {}).get("remainMinute", 0))
            bbox = draw.textbbox((0, 0), time_txt, font=f_unit_time)
            tw = bbox[2] - bbox[0]
            draw.text((x + card_w - tw - 14, d_y + 10), time_txt, fill=(239, 68, 68), font=f_unit_time)
            draw.rounded_rectangle([(x + 12, d_y + 42), (x + card_w - 12, d_y + 60)], radius=4, fill=(127, 29, 29), outline=(239, 68, 68), width=1)
            draw.text((x + 20, d_y + 44), "🚫 건조기 배수관 점검", fill=(254, 202, 202), font=f_badge)
        elif d_min > 0:
            draw.ellipse([(x + 12, d_y + 4), (x + 32, d_y + 24)], fill=(245, 158, 11), outline=(253, 230, 138), width=1)
            draw.text((x + 40, d_y + 2), "건조기", fill=(156, 163, 175), font=f_unit_title)
            draw.text((x + 40, d_y + 17), "작동 중", fill=(245, 158, 11), font=f_unit_state)
            time_txt = format_timer(d.get("timer", {}).get("remainHour", 0), d.get("timer", {}).get("remainMinute", 0))
            bbox = draw.textbbox((0, 0), time_txt, font=f_unit_time)
            tw = bbox[2] - bbox[0]
            draw.text((x + card_w - tw - 14, d_y + 10), time_txt, fill=(255, 255, 255), font=f_unit_time)
            draw.rounded_rectangle([(x + 40, d_y + 40), (x + 115, d_y + 56)], radius=4, fill=(31, 41, 55), outline=(75, 85, 99), width=1)
            draw.text((x + 46, d_y + 42), "🌀 표준 건조", fill=(209, 213, 219), font=f_badge)
        else:
            draw.ellipse([(x + 12, d_y + 4), (x + 32, d_y + 24)], fill=(55, 65, 81))
            draw.text((x + 40, d_y + 2), "건조기", fill=(156, 163, 175), font=f_unit_title)
            draw.text((x + 40, d_y + 17), "대기 중 (사용 가능)", fill=(107, 114, 128), font=f_unit_state)
            draw.text((x + card_w - 60, d_y + 10), "대기 중", fill=(107, 114, 128), font=f_unit_state)

        draw.line([(x + 8, y + 142), (x + card_w - 8, y + 142)], fill=(31, 41, 55), width=1)

        # 세탁기
        w_y = y + 150
        if w_err:
            draw.ellipse([(x + 12, w_y + 4), (x + 32, w_y + 24)], fill=(239, 68, 68), outline=(254, 202, 202), width=1)
            draw.text((x + 40, w_y + 2), "세탁기", fill=(156, 163, 175), font=f_unit_title)
            draw.text((x + 40, w_y + 17), "기기 점검/에러", fill=(239, 68, 68), font=f_unit_state)
            time_txt = format_timer(w.get("timer", {}).get("remainHour", 0), w.get("timer", {}).get("remainMinute", 0))
            bbox = draw.textbbox((0, 0), time_txt, font=f_unit_time)
            tw = bbox[2] - bbox[0]
            draw.text((x + card_w - tw - 14, w_y + 10), time_txt, fill=(239, 68, 68), font=f_unit_time)
        elif w_min > 0:
            draw.ellipse([(x + 12, w_y + 4), (x + 32, w_y + 24)], fill=(59, 130, 246), outline=(191, 219, 254), width=1)
            draw.text((x + 40, w_y + 2), "세탁기", fill=(156, 163, 175), font=f_unit_title)
            draw.text((x + 40, w_y + 17), "작동 중", fill=(96, 165, 250), font=f_unit_state)
            time_txt = format_timer(w.get("timer", {}).get("remainHour", 0), w.get("timer", {}).get("remainMinute", 0))
            bbox = draw.textbbox((0, 0), time_txt, font=f_unit_time)
            tw = bbox[2] - bbox[0]
            draw.text((x + card_w - tw - 14, w_y + 10), time_txt, fill=(255, 255, 255), font=f_unit_time)
            draw.rounded_rectangle([(x + 40, w_y + 40), (x + 115, w_y + 56)], radius=4, fill=(31, 41, 55), outline=(75, 85, 99), width=1)
            draw.text((x + 46, w_y + 42), "🫧 표준 세탁", fill=(209, 213, 219), font=f_badge)
        else:
            draw.ellipse([(x + 12, w_y + 4), (x + 32, w_y + 24)], fill=(55, 65, 81))
            draw.text((x + 40, w_y + 2), "세탁기", fill=(156, 163, 175), font=f_unit_title)
            draw.text((x + 40, w_y + 17), "대기 중 (사용 가능)", fill=(107, 114, 128), font=f_unit_state)
            draw.text((x + card_w - 60, w_y + 10), "대기 중", fill=(107, 114, 128), font=f_unit_state)

    # 남성 구역 (No.1 ~ No.5)
    draw.rounded_rectangle([(25, 68), (220, 92)], radius=5, fill=(30, 58, 138))
    draw.text((35, 72), "🟦 남성 구역 (No.1 ~ No.5)", fill=(191, 219, 254), font=f_sec_title)
    
    for idx, t in enumerate(TOWERS[:5]):
        cx = 25 + idx * (card_w + gap)
        draw_card(t, cx, 100)

    # 공용 & 여성 구역 (No.6 ~ No.9)
    draw.rounded_rectangle([(25, 363), (395, 387)], radius=5, fill=(88, 28, 135))
    draw.text((35, 367), "🟪 공용 (No.6~7) & 🟥 여성 구역 (No.8~9)", fill=(233, 213, 255), font=f_sec_title)

    for idx, t in enumerate(TOWERS[5:]):
        cx = 25 + idx * (card_w + gap)
        draw_card(t, cx, 395)

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return buf

# =========================================================
# 가동 중인 기기 선택 드롭다운 (Select Menu View)
# =========================================================
# 알림 등록 / 해제 공통 헬퍼
# =========================================================
async def register_or_toggle_alarm(interaction: discord.Interaction, tower_id, unit_type, remain_min, device_name):
    user_id = interaction.user.id
    key = f"{user_id}_{tower_id}_{unit_type}"

    existing = next((a for a in active_alarms if a.get("key") == key), None)
    if existing:
        active_alarms.remove(existing)
        save_alarms()
        await interaction.response.send_message(
            f"🔕 **[{device_name}]** 알림 등록이 해제되었습니다.",
            ephemeral=True
        )
        return

    target_ms = int(datetime.now().timestamp() * 1000) + (remain_min * 60 * 1000)
    alarm_item = {
        "key": key,
        "userId": user_id,
        "towerId": tower_id,
        "unitType": unit_type,
        "deviceName": device_name,
        "targetMs": target_ms,
        "remainMinutes": remain_min,
        "notified5Min": False,
        "notified0Min": False,
        "registeredAt": int(datetime.now().timestamp() * 1000)
    }
    active_alarms.append(alarm_item)
    save_alarms()

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
# 단일 기기 세탁/건조 선택 팝업 뷰 (둘 다 가동 중일 때)
# =========================================================
class MachineUnitChoiceView(discord.ui.View):
    def __init__(self, tower, dryer_info, washer_info):
        super().__init__(timeout=60)
        t_id = tower["id"]
        t_label = tower["label"]

        if dryer_info and dryer_info.get("running"):
            d_min = dryer_info["min"]
            d_time = dryer_info["time_str"]
            btn_d = discord.ui.Button(
                label=f"💨 건조기 선택 ({d_time} 남음)",
                style=discord.ButtonStyle.primary,
                emoji="💨"
            )
            async def cb_d(interaction: discord.Interaction):
                await register_or_toggle_alarm(interaction, t_id, "dryer", d_min, f"{t_label} 건조기")
            btn_d.callback = cb_d
            self.add_item(btn_d)

        if washer_info and washer_info.get("running"):
            w_min = washer_info["min"]
            w_time = washer_info["time_str"]
            btn_w = discord.ui.Button(
                label=f"🫧 세탁기 선택 ({w_time} 남음)",
                style=discord.ButtonStyle.success,
                emoji="🫧"
            )
            async def cb_w(interaction: discord.Interaction):
                await register_or_toggle_alarm(interaction, t_id, "washer", w_min, f"{t_label} 세탁기")
            btn_w.callback = cb_w
            self.add_item(btn_w)

# =========================================================
# 현실 배치도 버튼 그리드 뷰 (1열: 남성 1~5 / 2열: 공용 6~7 & 여성 8~9)
# =========================================================
class LaundryFloorplanButtonsView(discord.ui.View):
    def __init__(self, status_data):
        super().__init__(timeout=300)

        # 1행: 남성 1~5호기 버튼
        for t in TOWERS[:5]:
            self.add_tower_button(t, status_data, row=0)

        # 2행: 공용 6~7호기 & 여성 8~9호기 버튼
        for t in TOWERS[5:]:
            self.add_tower_button(t, status_data, row=1)

    def add_tower_button(self, t, status_data, row):
        data = status_data.get(t["name"], {})
        d = data.get("dryer", {})
        w = data.get("washer", {})

        d_state = d.get("runState", {}).get("currentState", "POWER_OFF")
        w_state = w.get("runState", {}).get("currentState", "POWER_OFF")
        d_min = (d.get("timer", {}).get("remainHour", 0) * 60) + d.get("timer", {}).get("remainMinute", 0)
        w_min = (w.get("timer", {}).get("remainHour", 0) * 60) + w.get("timer", {}).get("remainMinute", 0)
        d_err = d.get("error") or (d_state == "ERROR")
        w_err = w.get("error") or (w_state == "ERROR")

        d_running = not d_err and is_unit_running(d_state, d_min)
        w_running = not w_err and is_unit_running(w_state, w_min)

        d_time = format_timer(d.get("timer", {}).get("remainHour", 0), d.get("timer", {}).get("remainMinute", 0))
        w_time = format_timer(w.get("timer", {}).get("remainHour", 0), w.get("timer", {}).get("remainMinute", 0))

        # 버튼 라벨 및 상태 지정
        if d_err or w_err:
            btn_label = f"{t['label']} ⚠️점검"
            btn_style = discord.ButtonStyle.danger
            is_disabled = True
        elif d_running and w_running:
            btn_label = f"{t['label']} (💨{d_time} 🫧{w_time})"
            btn_style = discord.ButtonStyle.success
            is_disabled = False
        elif d_running:
            btn_label = f"{t['label']} 💨{d_time}"
            btn_style = discord.ButtonStyle.primary
            is_disabled = False
        elif w_running:
            btn_label = f"{t['label']} 🫧{w_time}"
            btn_style = discord.ButtonStyle.primary
            is_disabled = False
        else:
            btn_label = f"{t['label']} 대기"
            btn_style = discord.ButtonStyle.secondary
            is_disabled = True

        btn = discord.ui.Button(
            label=btn_label,
            style=btn_style,
            disabled=is_disabled,
            row=row
        )

        if not is_disabled:
            async def btn_callback(interaction: discord.Interaction):
                # 1) 건조기와 세탁기 둘 다 돌 때: 팝업 버튼 선택
                if d_running and w_running:
                    view = MachineUnitChoiceView(
                        t,
                        {"running": True, "min": d_min, "time_str": d_time},
                        {"running": True, "min": w_min, "time_str": w_time}
                    )
                    await interaction.response.send_message(
                        f"🧺 **[{t['label']}]** 건조기와 세탁기가 모두 가동 중입니다. 알림을 받을 기기를 선택하세요:",
                        view=view,
                        ephemeral=True
                    )
                # 2) 건조기만 돌 때: 즉시 건조기 알림 등록
                elif d_running:
                    await register_or_toggle_alarm(interaction, t["id"], "dryer", d_min, f"{t['label']} 건조기")
                # 3) 세탁기만 돌 때: 즉시 세탁기 알림 등록
                elif w_running:
                    await register_or_toggle_alarm(interaction, t["id"], "washer", w_min, f"{t['label']} 세탁기")

            btn.callback = btn_callback

        self.add_item(btn)

def build_floorplan_embed():
    embed = discord.Embed(
        title="🧺 크래프톤 정글 스마트 세탁실 현황 & 알림",
        description=(
            "아래 **현실 배치도 카드 뷰**를 확인하고, **원하는 호기 번호 버튼을 직접 클릭**하여 5분 전 DM 알림을 등록하세요!\n"
            "*(대기 중이거나 점검 중인 기기는 자동으로 비활성화됩니다)*"
        ),
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
# 슬래시 명령어 (/알림) & 접두사 명령어 (!알림) 동시 지원
# =========================================================
@bot.tree.command(name="알림", description="실시간 세탁실 현실 배치도를 확인하고 원하는 기기 버튼을 눌러 5분 전 DM 알림을 등록합니다.")
async def cmd_alarm_slash(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=False)
    status_data = fetch_live_status()

    img_buf = render_floorplan_image(status_data)
    discord_file = discord.File(img_buf, filename="floorplan.png")
    embed = build_floorplan_embed()
    view = LaundryFloorplanButtonsView(status_data)

    await interaction.followup.send(file=discord_file, embed=embed, view=view)

@bot.command(name="알림", aliases=["세탁", "세탁실", "laundry"])
async def cmd_alarm_prefix(ctx):
    """디스코드 채팅창에 !알림 또는 !세탁실 입력 시에도 동작"""
    status_data = fetch_live_status()

    img_buf = render_floorplan_image(status_data)
    discord_file = discord.File(img_buf, filename="floorplan.png")
    embed = build_floorplan_embed()
    view = LaundryFloorplanButtonsView(status_data)

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

    for item in list(active_alarms):
        tower = next((t for t in TOWERS if t["id"] == item["towerId"]), None)
        if not tower:
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
        if (remain_min == 0 or run_state in ('COMPLETE', 'POWER_OFF', 'WRINKLE_CARE')) and item.get("notified5Min") and not item.get("notified0Min"):
            item["notified0Min"] = True
            changed = True
            to_remove.append(item)
            if user:
                try:
                    await user.send(
                        f"🏁 **[세탁 완료] {item['deviceName']}** 가동이 모두 끝났습니다!\n"
                        f"👉 다음 정글러를 위해 세탁실에서 빨래를 즉시 수거해 주세요! 🫧"
                    )
                except Exception as e:
                    print(f"[DM Send Error] {e}")

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
