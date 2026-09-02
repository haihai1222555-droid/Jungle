import os
import sys
import json
import asyncio
import urllib.request
import urllib.error
from datetime import datetime
import discord
from discord import app_commands
from discord.ext import commands, tasks

# 콘솔 출력 버퍼링 해제
try:
    sys.stdout.reconfigure(encoding='utf-8', line_buffering=True)
    sys.stderr.reconfigure(encoding='utf-8', line_buffering=True)
except Exception:
    pass

# =========================================================
# 설정 및 환경 변수
# =========================================================
DISCORD_BOT_TOKEN = os.environ.get("DISCORD_BOT_TOKEN") or ""
STATUS_API_URL = os.environ.get("STATUS_API_URL") or "https://jungle-wash.onrender.com/api/status"
BOT_DATA_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "discord_alarms.json")

# 워시타워 9대 메타데이터
TOWERS = [
    {"id": 1, "name": "워시타워_1", "zone": "men",    "label": "1호기", "zoneName": "남성 전용"},
    {"id": 2, "name": "워시타워_2", "zone": "men",    "label": "2호기", "zoneName": "남성 전용"},
    {"id": 3, "name": "워시타워_3", "zone": "men",    "label": "3호기", "zoneName": "남성 전용"},
    {"id": 4, "name": "워시타워_4", "zone": "men",    "label": "4호기", "zoneName": "남성 전용"},
    {"id": 5, "name": "워시타워_5", "zone": "men",    "label": "5호기", "zoneName": "남성 전용"},
    {"id": 6, "name": "워시타워_6", "zone": "common", "label": "6호기", "zoneName": "공용"},
    {"id": 7, "name": "워시타워_7", "zone": "common", "label": "7호기", "zoneName": "공용"},
    {"id": 8, "name": "워시타워_8", "zone": "women",  "label": "8호기", "zoneName": "여성 전용"},
    {"id": 9, "name": "워시타워_9", "zone": "women",  "label": "9호기", "zoneName": "여성 전용"},
]

# 가동 중인 상태 목록
RUNNING_STATES = ('RUNNING', 'WASHING', 'RINSING', 'SPINNING', 'DRYING', 'COOLING')

# =========================================================
# 데이터 로드 / 저장 헬퍼
# =========================================================
active_alarms = []  # list of dict: { userId, towerId, unitType, deviceName, targetMs, notified5Min, notified0Min, registeredAt }

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
        return ""
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
# 현실 세탁실 배치도 임베드 생성기
# =========================================================
def build_floorplan_embed(status_data):
    embed = discord.Embed(
        title="🧺 크래프톤 정글 스마트 세탁실 현황 & 알림",
        description="현실 세탁실 2열 배치도 현황입니다. **현재 가동 중인 기기**를 아래 선택창에서 골라 5분 전 DM 알림을 등록하세요!",
        color=discord.Color.from_rgb(0, 232, 122),
        timestamp=datetime.now()
    )

    # 1) 남성 구역 (1~5호기 - 좌측 라인)
    men_lines = []
    for t in TOWERS[:5]:
        data = status_data.get(t["name"], {})
        w = data.get("washer", {})
        d = data.get("dryer", {})
        w_state = w.get("runState", {}).get("currentState", "POWER_OFF")
        d_state = d.get("runState", {}).get("currentState", "POWER_OFF")
        w_timer = format_timer(w.get("timer", {}).get("remainHour", 0), w.get("timer", {}).get("remainMinute", 0))
        d_timer = format_timer(d.get("timer", {}).get("remainHour", 0), d.get("timer", {}).get("remainMinute", 0))
        
        d_err = d.get("error") or (d_state == "ERROR")
        w_err = w.get("error") or (w_state == "ERROR")

        # 건조기 상태 문자열
        if d_err:
            d_str = "💨 건조: ⚠️ 점검필요"
        elif d_timer:
            d_str = f"💨 건조: 🌀 **{d_timer}**"
        else:
            d_str = "💨 건조: 🟢 대기"

        # 세탁기 상태 문자열
        if w_err:
            w_str = "🫧 세탁: ⚠️ 점검필요"
        elif w_timer:
            w_str = f"🫧 세탁: 🫧 **{w_timer}**"
        else:
            w_str = "🫧 세탁: 🟢 대기"

        men_lines.append(f"**[{t['label']}]** {d_str} | {w_str}")

    embed.add_field(
        name="🟦 남성 구역 (좌측 1 ~ 5호기)",
        value="\n".join(men_lines) if men_lines else "데이터 없음",
        inline=False
    )

    # 2) 공용 구역 (6~7호기 - 우측 상단)
    common_lines = []
    for t in TOWERS[5:7]:
        data = status_data.get(t["name"], {})
        w = data.get("washer", {})
        d = data.get("dryer", {})
        w_state = w.get("runState", {}).get("currentState", "POWER_OFF")
        d_state = d.get("runState", {}).get("currentState", "POWER_OFF")
        w_timer = format_timer(w.get("timer", {}).get("remainHour", 0), w.get("timer", {}).get("remainMinute", 0))
        d_timer = format_timer(d.get("timer", {}).get("remainHour", 0), d.get("timer", {}).get("remainMinute", 0))
        d_err = d.get("error") or (d_state == "ERROR")
        w_err = w.get("error") or (w_state == "ERROR")

        d_str = "💨 건조: ⚠️ 점검필요" if d_err else (f"💨 건조: 🌀 **{d_timer}**" if d_timer else "💨 건조: 🟢 대기")
        w_str = "🫧 세탁: ⚠️ 점검필요" if w_err else (f"🫧 세탁: 🫧 **{w_timer}**" if w_timer else "🫧 세탁: 🟢 대기")

        common_lines.append(f"**[{t['label']}]** {d_str} | {w_str}")

    embed.add_field(
        name="🟪 공용 구역 (우측 상단 6 ~ 7호기)",
        value="\n".join(common_lines) if common_lines else "데이터 없음",
        inline=False
    )

    # 3) 여성 구역 (8~9호기 - 우측 하단)
    women_lines = []
    for t in TOWERS[7:]:
        data = status_data.get(t["name"], {})
        w = data.get("washer", {})
        d = data.get("dryer", {})
        w_state = w.get("runState", {}).get("currentState", "POWER_OFF")
        d_state = d.get("runState", {}).get("currentState", "POWER_OFF")
        w_timer = format_timer(w.get("timer", {}).get("remainHour", 0), w.get("timer", {}).get("remainMinute", 0))
        d_timer = format_timer(d.get("timer", {}).get("remainHour", 0), d.get("timer", {}).get("remainMinute", 0))
        d_err = d.get("error") or (d_state == "ERROR")
        w_err = w.get("error") or (w_state == "ERROR")

        d_str = "💨 건조: ⚠️ 점검필요" if d_err else (f"💨 건조: 🌀 **{d_timer}**" if d_timer else "💨 건조: 🟢 대기")
        w_str = "🫧 세탁: ⚠️ 점검필요" if w_err else (f"🫧 세탁: 🫧 **{w_timer}**" if w_timer else "🫧 세탁: 🟢 대기")

        women_lines.append(f"**[{t['label']}]** {d_str} | {w_str}")

    embed.add_field(
        name="🟥 여성 구역 (우측 하단 8 ~ 9호기)",
        value="\n".join(women_lines) if women_lines else "데이터 없음",
        inline=False
    )

    embed.set_footer(text="크래프톤 정글 세탁실 · Data powered by LG ThinQ API", icon_url="https://jungle-wash.vercel.app/jungle-logo.png")
    return embed

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

        user_id = interaction.user.id
        key = f"{user_id}_{tower_id}_{unit_type}"

        # 이미 등록된 알림인지 확인
        existing = next((a for a in active_alarms if a.get("key") == key), None)
        if existing:
            # 알림 취소 옵션 제공
            active_alarms.remove(existing)
            save_alarms()
            await interaction.response.send_message(
                f"🔕 **[{device_name}]** 알림 등록이 해제되었습니다.",
                ephemeral=True
            )
            return

        # 새 알림 등록
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

        # DM 수신 테스트 및 등록 완료 안내
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

class LaundryFloorplanView(discord.ui.View):
    def __init__(self, running_options):
        super().__init__(timeout=180)
        if running_options:
            self.add_item(LaundryAlarmSelect(running_options))

# =========================================================
# 슬래시 명령어: /알림
# =========================================================
@bot.tree.command(name="알림", description="실시간 세탁실 현실 배치도를 확인하고 가동 중인 기기 5분 전 DM 알림을 등록합니다.")
async def cmd_alarm(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=False)

    status_data = fetch_live_status()
    embed = build_floorplan_embed(status_data)

    # 가동 중인 기기만 필터링하여 드롭다운 옵션 생성 (대기 중, 에러, 완료는 제외)
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

        # 상단 건조기 검증
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

    if not running_options:
        embed.add_field(
            name="💡 알림 등록 안내",
            value="현재 세탁실에 가동 중인 세탁기/건조기가 없습니다. (모든 기기가 대기 중이거나 완료 상태입니다)",
            inline=False
        )
        await interaction.followup.send(embed=embed)
    else:
        view = LaundryFloorplanView(running_options[:25])  # 디스코드 옵션 최대 25개 제한
        await interaction.followup.send(embed=embed, view=view)

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
# 봇 준비 완료 이벤트 (Slash Command 동기화)
# =========================================================
@bot.event
async def on_ready():
    load_alarms()
    print(f"🤖 [Discord Bot] {bot.user.name}#{bot.user.discriminator} (ID: {bot.user.id}) 로그인 성공!")
    
    try:
        synced = await bot.tree.sync()
        print(f"✅ [Slash Commands] {len(synced)}개 슬래시 명령어 글로벌 동기화 완료! (/알림)")
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
