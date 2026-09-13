#!/usr/bin/env python3

from pathlib import Path

from garminconnect import Garmin

TOKEN_DIR = Path(__file__).resolve().parent / "cn_tokens"

g = Garmin(is_cn=True)

g.login(str(TOKEN_DIR))

profile = g.get_full_name()

print("Garmin CN session OK")
print("User:", profile)
