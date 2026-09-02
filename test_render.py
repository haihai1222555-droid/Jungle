import os
import io
import json
import urllib.request
from datetime import datetime
from PIL import Image, ImageDraw, ImageFont

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

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

def format_timer(hour, minute):
    if not hour and not minute:
        return "대기 중"
    if hour > 0:
        return f"{hour}시간 {minute}분"
    return f"{minute}분"

def is_unit_running(state, remain_min):
    return state in ('RUNNING', 'WASHING', 'RINSING', 'SPINNING', 'DRYING', 'COOLING') or (remain_min > 0 and state != 'ERROR' and state != 'POWER_OFF')

def render_floorplan_image(status_data):
    # 2배율 초고화질 2000 x 1150 캔버스 (디스코드 화면 꽉 채움)
    W, H = 2000, 1150
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

    # 1. Header Bar (대형)
    draw.rounded_rectangle([(30, 25), (W - 30, 95)], radius=12, fill=(17, 24, 39))
    draw.text((60, 42), "🧺 크래프톤 정글 스마트 세탁실 현실 배치도", fill=(255, 255, 255), font=f_header)
    
    # Legend
    draw.ellipse([(W - 750, 52), (W - 732, 70)], fill=(107, 114, 128))
    draw.text((W - 720, 47), "대기 중", fill=(156, 163, 175), font=f_sub)

    draw.ellipse([(W - 610, 52), (W - 592, 70)], fill=(16, 185, 129))
    draw.text((W - 580, 47), "작동 중", fill=(156, 163, 175), font=f_sub)

    draw.ellipse([(W - 460, 52), (W - 442, 70)], fill=(245, 158, 11))
    draw.text((W - 430, 47), "건조 중", fill=(156, 163, 175), font=f_sub)

    draw.ellipse([(W - 310, 52), (W - 292, 70)], fill=(239, 68, 68))
    draw.text((W - 280, 47), "점검 필요", fill=(156, 163, 175), font=f_sub)

    # 2. Card Dimensions
    card_w = 365
    card_h = 420
    gap = 25

    towers_men = [
        {"id": 1, "name": "워시타워_1", "label": "No.1", "zoneName": "남성 전용"},
        {"id": 2, "name": "워시타워_2", "label": "No.2", "zoneName": "남성 전용"},
        {"id": 3, "name": "워시타워_3", "label": "No.3", "zoneName": "남성 전용"},
        {"id": 4, "name": "워시타워_4", "label": "No.4", "zoneName": "남성 전용"},
        {"id": 5, "name": "워시타워_5", "label": "No.5", "zoneName": "남성 전용"},
    ]

    towers_cw = [
        {"id": 6, "name": "워시타워_6", "label": "No.6", "zoneName": "공용"},
        {"id": 7, "name": "워시타워_7", "label": "No.7", "zoneName": "공용"},
        {"id": 8, "name": "워시타워_8", "label": "No.8", "zoneName": "여성 전용"},
        {"id": 9, "name": "워시타워_9", "label": "No.9", "zoneName": "여성 전용"},
    ]

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

        # Card Body
        draw.rounded_rectangle([(x, y), (x + card_w, y + card_h)], radius=16, fill=(17, 24, 39), outline=border_col, width=3)
        
        # Header
        draw.text((x + 20, y + 16), t["label"], fill=(255, 255, 255), font=f_card_num)
        
        # Zone Tag Pill
        z_col = (59, 130, 246) if "남성" in t["zoneName"] else ((168, 85, 247) if "공용" in t["zoneName"] else (236, 72, 153))
        draw.rounded_rectangle([(x + 90, y + 18), (x + 180, y + 46)], radius=6, fill=(z_col[0]//4, z_col[1]//4, z_col[2]//4), outline=z_col, width=2)
        draw.text((x + 100, y + 21), t["zoneName"], fill=z_col, font=f_card_tag)

        # Status Badge (Right)
        badge_w = 115
        draw.rounded_rectangle([(x + card_w - badge_w - 18, y + 16), (x + card_w - 18, y + 46)], radius=6, fill=status_bg)
        draw.text((x + card_w - badge_w - 4, y + 21), status_text, fill=(255, 255, 255), font=f_badge)

        # Divider 1
        draw.line([(x + 14, y + 62), (x + card_w - 14, y + 62)], fill=(31, 41, 55), width=2)

        # ── UPPER: 건조기 (Dryer) ──
        d_y = y + 78
        if d_err:
            draw.ellipse([(x + 20, d_y + 8), (x + 52, d_y + 40)], fill=(239, 68, 68), outline=(254, 202, 202), width=2)
            draw.text((x + 65, d_y + 4), "건조기", fill=(156, 163, 175), font=f_unit_title)
            draw.text((x + 65, d_y + 28), "기기 점검/에러", fill=(239, 68, 68), font=f_unit_state)
            time_txt = format_timer(d.get("timer", {}).get("remainHour", 0), d.get("timer", {}).get("remainMinute", 0))
            bbox = draw.textbbox((0, 0), time_txt, font=f_unit_time)
            tw = bbox[2] - bbox[0]
            draw.text((x + card_w - tw - 22, d_y + 16), time_txt, fill=(239, 68, 68), font=f_unit_time)
            # Error banner
            draw.rounded_rectangle([(x + 20, d_y + 70), (x + card_w - 20, d_y + 100)], radius=6, fill=(127, 29, 29), outline=(239, 68, 68), width=1)
            draw.text((x + 35, d_y + 74), "🚫 건조기 배수관 점검 필요", fill=(254, 202, 202), font=f_badge)
        elif d_min > 0:
            draw.ellipse([(x + 20, d_y + 8), (x + 52, d_y + 40)], fill=(245, 158, 11), outline=(253, 230, 138), width=2)
            draw.text((x + 65, d_y + 4), "건조기", fill=(156, 163, 175), font=f_unit_title)
            draw.text((x + 65, d_y + 28), "작동 중", fill=(245, 158, 11), font=f_unit_state)
            time_txt = format_timer(d.get("timer", {}).get("remainHour", 0), d.get("timer", {}).get("remainMinute", 0))
            bbox = draw.textbbox((0, 0), time_txt, font=f_unit_time)
            tw = bbox[2] - bbox[0]
            draw.text((x + card_w - tw - 22, d_y + 16), time_txt, fill=(255, 255, 255), font=f_unit_time)
            # Course tag
            draw.rounded_rectangle([(x + 65, d_y + 66), (x + 185, d_y + 96)], radius=6, fill=(31, 41, 55), outline=(75, 85, 99), width=1)
            draw.text((x + 75, d_y + 70), "🌀 표준 건조", fill=(209, 213, 219), font=f_badge)
        else:
            draw.ellipse([(x + 20, d_y + 8), (x + 52, d_y + 40)], fill=(55, 65, 81))
            draw.text((x + 65, d_y + 4), "건조기", fill=(156, 163, 175), font=f_unit_title)
            draw.text((x + 65, d_y + 28), "대기 중 (사용 가능)", fill=(107, 114, 128), font=f_unit_state)
            draw.text((x + card_w - 95, d_y + 16), "대기 중", fill=(107, 114, 128), font=f_unit_state)

        # Divider 2
        draw.line([(x + 14, y + 240), (x + card_w - 14, y + 240)], fill=(31, 41, 55), width=2)

        # ── LOWER: 세탁기 (Washer) ──
        w_y = y + 255
        if w_err:
            draw.ellipse([(x + 20, w_y + 8), (x + 52, w_y + 40)], fill=(239, 68, 68), outline=(254, 202, 202), width=2)
            draw.text((x + 65, w_y + 4), "세탁기", fill=(156, 163, 175), font=f_unit_title)
            draw.text((x + 65, w_y + 28), "기기 점검/에러", fill=(239, 68, 68), font=f_unit_state)
            time_txt = format_timer(w.get("timer", {}).get("remainHour", 0), w.get("timer", {}).get("remainMinute", 0))
            bbox = draw.textbbox((0, 0), time_txt, font=f_unit_time)
            tw = bbox[2] - bbox[0]
            draw.text((x + card_w - tw - 22, w_y + 16), time_txt, fill=(239, 68, 68), font=f_unit_time)
        elif w_min > 0:
            draw.ellipse([(x + 20, w_y + 8), (x + 52, w_y + 40)], fill=(59, 130, 246), outline=(191, 219, 254), width=2)
            draw.text((x + 65, w_y + 4), "세탁기", fill=(156, 163, 175), font=f_unit_title)
            draw.text((x + 65, w_y + 28), "작동 중", fill=(96, 165, 250), font=f_unit_state)
            time_txt = format_timer(w.get("timer", {}).get("remainHour", 0), w.get("timer", {}).get("remainMinute", 0))
            bbox = draw.textbbox((0, 0), time_txt, font=f_unit_time)
            tw = bbox[2] - bbox[0]
            draw.text((x + card_w - tw - 22, w_y + 16), time_txt, fill=(255, 255, 255), font=f_unit_time)
            # Course tag
            draw.rounded_rectangle([(x + 65, w_y + 66), (x + 185, w_y + 96)], radius=6, fill=(31, 41, 55), outline=(75, 85, 99), width=1)
            draw.text((x + 75, w_y + 70), "🫧 표준 세탁", fill=(209, 213, 219), font=f_badge)
        else:
            draw.ellipse([(x + 20, w_y + 8), (x + 52, w_y + 40)], fill=(55, 65, 81))
            draw.text((x + 65, w_y + 4), "세탁기", fill=(156, 163, 175), font=f_unit_title)
            draw.text((x + 65, w_y + 28), "대기 중 (사용 가능)", fill=(107, 114, 128), font=f_unit_state)
            draw.text((x + card_w - 95, w_y + 16), "대기 중", fill=(107, 114, 128), font=f_unit_state)

    # ── Section 1: Men 1~5 ──
    draw.rounded_rectangle([(35, 115), (340, 155)], radius=8, fill=(30, 58, 138))
    draw.text((50, 121), "🟦 남성 구역 (No.1 ~ No.5)", fill=(191, 219, 254), font=f_sec_title)

    for idx, t in enumerate(towers_men):
        cx = 35 + idx * (card_w + gap)
        draw_card(t, cx, 168)

    # ── Section 2: Common 6~7 & Women 8~9 ──
    draw.rounded_rectangle([(35, 620), (590, 660)], radius=8, fill=(88, 28, 135))
    draw.text((50, 626), "🟪 공용 (No.6~7) & 🟥 여성 구역 (No.8~9)", fill=(233, 213, 255), font=f_sec_title)

    for idx, t in enumerate(towers_cw):
        cx = 35 + idx * (card_w + gap)
        draw_card(t, cx, 675)

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return buf

if __name__ == "__main__":
    req = urllib.request.Request("https://jungle-wash.onrender.com/api/status", headers={'User-Agent': 'Mozilla/5.0'})
    with urllib.request.urlopen(req, timeout=5) as res:
        status_data = json.loads(res.read().decode('utf-8'))
    
    buf = render_floorplan_image(status_data)
    with open("floorplan_preview.png", "wb") as f:
        f.write(buf.read())
    print("Full-size High-Res floorplan image rendered successfully!")
