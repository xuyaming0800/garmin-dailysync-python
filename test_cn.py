#!/usr/bin/env python3

from garminconnect import Garmin

TOKEN_DIR = "/opt/garmin-auth/cn_tokens"

g = Garmin(is_cn=True)

g.login(TOKEN_DIR)

profile = g.get_full_name()

print("Garmin CN session OK")
print("User:", profile)
