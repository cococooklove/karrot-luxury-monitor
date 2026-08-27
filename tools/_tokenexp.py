#!/usr/bin/env python3
# stdin: karrot_token.ds 원시바이트 → access/refresh exp 출력.
import sys, json, base64, time, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__)))
from extract_tokens import parse_token_ds
d = parse_token_ds(sys.stdin.buffer.read())
now = int(time.time())
for k in ("access", "refresh"):
    t = d.get(k, "")
    parts = t.split(".")
    if len(parts) < 2:
        print(f"{k}: 없음"); continue
    p = parts[1]; p += "=" * (-len(p) % 4)
    try:
        j = json.loads(base64.urlsafe_b64decode(p))
        exp = j.get("exp", 0); rem = int(exp - now)
        print(f"{k}: exp={exp} ({rem}s, {rem//60}m 남음) jti={j.get('jti','')[:8]} dev={str(j.get('device_id',''))[:8]}")
    except Exception as e:
        print(f"{k}: parse err {e}")
