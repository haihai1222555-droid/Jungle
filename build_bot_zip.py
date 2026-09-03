# -*- coding: utf-8 -*-
"""Discloud 업로드용 봇 zip 을 만든다.

    python build_bot_zip.py

`.env` 파일이 있으면 함께 담는다. 없으면 그냥 건너뛴다.
(Discloud 대시보드에 환경변수를 직접 넣었다면 .env 는 없어도 된다)
"""
import os
import sys
import zipfile

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(BASE_DIR, "jungle_bot_discloud.zip")

# zip 안에서는 이름을 바꿔 담는 파일 (원본 -> zip 안 이름)
RENAMED = {"requirements-bot.txt": "requirements.txt"}

REQUIRED = [
    "discloud.config",
    "discord_bot.py",
    "jungle_kb.py",
    "requirements-bot.txt",
    "NanumGothic-Bold.ttf",
    "NanumGothic-Regular.ttf",
]
OPTIONAL = [".env"]
# assets 폴더 안의 안내 사진들도 함께 담는다 (README 는 제외)
ASSETS = "assets"


def main():
    missing = [f for f in REQUIRED if not os.path.exists(os.path.join(BASE_DIR, f))]
    if missing:
        print("빠진 파일:", ", ".join(missing))
        return 1

    included = []
    with zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED) as z:
        for name in REQUIRED + OPTIONAL:
            path = os.path.join(BASE_DIR, name)
            if os.path.exists(path):
                arcname = RENAMED.get(name, name)
                z.write(path, arcname)
                included.append(arcname if arcname == name else f"{name} -> {arcname}")

        assets_dir = os.path.join(BASE_DIR, ASSETS)
        if os.path.isdir(assets_dir):
            pics = 0
            for fn in sorted(os.listdir(assets_dir)):
                if fn.lower().endswith((".png", ".jpg", ".jpeg", ".webp")):
                    z.write(os.path.join(assets_dir, fn), f"{ASSETS}/{fn}")
                    pics += 1
            if pics:
                included.append(f"{ASSETS}/ (사진 {pics}장)")
            else:
                print("assets 폴더에 사진이 없습니다. assets/README.md 를 참고해 넣어주세요.")

    print("만들었습니다: %s (%d KB)" % (os.path.basename(OUT), os.path.getsize(OUT) // 1024))
    for name in included:
        print("  -", name)
    if ".env" not in included:
        print("\n.env 가 없어 담지 않았습니다.")
        print("환경변수를 파일로 넣으려면 .env.example 을 복사해 .env 로 만드세요.")
    else:
        print("\n.env 를 함께 담았습니다. 이 zip 은 토큰이 들어있을 수 있으니 공유하지 마세요.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
