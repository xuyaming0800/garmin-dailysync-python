#!/usr/bin/env python3

import os
from getpass import getpass
from pathlib import Path

from garminconnect import Garmin
from garminconnect import (
    GarminConnectAuthenticationError,
    GarminConnectConnectionError,
    GarminConnectTooManyRequestsError,
)

BASE_DIR = Path(__file__).resolve().parent
TOKEN_DIR = BASE_DIR / "cn_tokens"
TOKEN_DIR.mkdir(parents=True, exist_ok=True)


def main():
    print("")
    print("===================================")
    print(" Garmin 中国区首次 MFA 登录")
    print("===================================")
    print("")

    email = input("Garmin 中国区邮箱: ").strip()
    password = getpass("Garmin 中国区密码: ")

    garmin = Garmin(
        email=email,
        password=password,
        is_cn=True,
        prompt_mfa=lambda: input("请输入 Garmin 验证码: ").strip(),
    )

    try:
        garmin.login(str(TOKEN_DIR))

        print("")
        print("登录成功。")
        print(f"Token 已保存到: {TOKEN_DIR}")
        print("")
        print("目录内容:")
        for f in TOKEN_DIR.iterdir():
            print("  ", f.name)

    except GarminConnectTooManyRequestsError as e:
        print("")
        print("Garmin 返回 429，请不要连续重试登录。")
        print(e)
        raise SystemExit(2)

    except GarminConnectAuthenticationError as e:
        print("")
        print("账号、密码或验证码错误。")
        print(e)
        raise SystemExit(3)

    except GarminConnectConnectionError as e:
        print("")
        print("Garmin 网络连接失败。")
        print(e)
        raise SystemExit(4)


if __name__ == "__main__":
    main()
