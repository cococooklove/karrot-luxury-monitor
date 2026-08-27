#!/usr/bin/env python3
# stdin: karrot_token.ds → refresh JWT 의 sub(계정코드) 출력.
import sys, json, base64, os
sys.path.insert(0, os.path.dirname(__file__))
from extract_tokens import parse_token_ds
d = parse_token_ds(sys.stdin.buffer.read())
t = d.get("refresh") or d.get("access") or ""
parts = t.split(".")
if len(parts) >= 2:
    p = parts[1]; p += "=" * (-len(p) % 4)
    try:
        print(json.loads(base64.urlsafe_b64decode(p)).get("sub", ""))
    except Exception:
        pass
