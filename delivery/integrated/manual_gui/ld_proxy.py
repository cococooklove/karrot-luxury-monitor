"""LDPlayer 인스턴스(게스트)의 앱 트래픽을 계정별 프록시로 내보낸다.

## 왜 필요한가

토큰을 만드는 건 게스트 안의 당근 앱이다. 그 앱이 어디서 접속하는지가 곧 그
계정이 어디서 로그인했는지다. 지금 운영 서버는 **미국 IP** 라, 검색·폴링만 KR
프록시로 돌려도 정작 계정이 붙는 곳은 미국이다. 계정 위험의 근원이 거기다.

## 되는 방법 (2026-09-01 실측)

당근 앱은 **안드로이드 전역 프록시를 존중한다.** 서버에서 로깅 프록시를 띄우고
`settings put global http_proxy 172.16.1.2:8899` 를 건 뒤 앱을 콜드스타트하니
`api.kr.karrotmarket.com`(토큰 갱신 호스트) · `event.kr.karrotmarket.com` ·
`img.kr.gcp-karroter.net` 이 전부 그 프록시를 지나갔다.

게스트에서 호스트는 VirtualBox NAT 게이트웨이 주소다. 실측 서버 기준
게스트 `172.16.1.95/24`, 기본 게이트웨이 `172.16.1.2` — 이 값은 인스턴스마다
다를 수 있으므로 **지어내지 않고 게스트에게 물어본다**(`host_addr_for`).

## 인증

상용 KR 프록시는 대개 `아이디:비번@호스트:포트` 인데 안드로이드 전역 프록시에는
자격증명 필드가 없다(`host:port` 뿐). 그래서 호스트에서 인증 없는 로컬 리스너를
열고 업스트림에 인증을 붙여 넘기는 릴레이(`daangn_ext/proxy_relay.py`)를 쓴다.
프록시가 IP 화이트리스트라 자격증명이 없으면 릴레이 없이 바로 꽂아도 된다.

## 이 모듈이 하지 않는 것

인스턴스를 켜거나 끄지 않는다. 프록시를 바꿔도 **앱을 강제로 재시작하지 않는다** —
그건 수확기(nudge)의 몫이고, 여기서 겹쳐 부르면 같은 인스턴스에 force-stop 이
두 번 간다. 다만 전역 프록시는 앱이 새로 소켓을 열 때부터 적용되므로, 즉시
반영하고 싶으면 호출자가 수확을 한 번 돌리면 된다.
"""
from __future__ import annotations

import subprocess

from ld_autoharvest import (PKG, find_ldconsole, fleet_indexes, parse_token_ds,
                            _jwt_sub)

# 게스트에서 '프록시 없음'을 뜻하는 값. 안드로이드는 빈 문자열 대신 이걸 쓴다 —
# `settings put global http_proxy ""` 는 값이 안 지워지는 판이 있다.
NONE_PROXY = ":0"
CMD_TIMEOUT = 15


def _adb(console, index, shell_cmd, timeout=CMD_TIMEOUT):
    """`ldconsole adb --index N --command "<cmd>"`. 반환 (성공, 출력).

    인덱스로 직접 말을 건다 — ldconsole 이 인덱스→serial 을 스스로 풀어주므로
    우리가 포트 산술 같은 매핑을 지어낼 필요가 없다(ld_probe 와 같은 이유).
    """
    try:
        p = subprocess.run([console, "adb", "--index", str(index),
                            "--command", shell_cmd],
                           capture_output=True, timeout=timeout,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except Exception:
        return False, ""
    out = (p.stdout or b"").decode("utf-8", "ignore")
    return p.returncode == 0, out


def get_guest_proxy(console, index):
    """게스트에 걸린 전역 프록시. 없으면 None."""
    ok, out = _adb(console, index, "shell settings get global http_proxy")
    if not ok:
        return None
    v = (out or "").strip().splitlines()
    v = v[-1].strip() if v else ""
    if not v or v in ("null", NONE_PROXY):
        return None
    return v


def set_guest_proxy(console, index, endpoint, log=None):
    """게스트 전역 프록시를 endpoint("host:port")로. None 이면 해제. 반환: 성공.

    쓰고 나서 **다시 읽어 확인한다**. `settings put` 은 값이 안 먹어도 종료코드
    0 을 주는 경우가 있어, 성공을 반환값으로만 믿으면 프록시가 안 걸린 채
    걸렸다고 착각하게 된다 — 그 착각의 대가가 미국 IP 로 붙는 계정이다.
    """
    log = log or (lambda m: None)
    want = endpoint or NONE_PROXY
    ok, _ = _adb(console, index, f"shell settings put global http_proxy {want}")
    if not ok:
        log(f"[프록시] index {index}: 설정 실패(adb 무응답)")
        return False
    got = get_guest_proxy(console, index)
    if endpoint and got != endpoint:
        log(f"[프록시] index {index}: 반영 안 됨(원함 {endpoint} · 실제 {got})")
        return False
    if not endpoint and got:
        log(f"[프록시] index {index}: 해제 안 됨(실제 {got})")
        return False
    return True


def host_addr_for(console, index):
    """이 게스트에서 호스트를 가리키는 주소. 못 알아내면 None.

    VirtualBox NAT 의 게이트웨이가 곧 호스트다. 서버마다 대역이 다를 수 있어
    상수로 박지 않고 게스트의 기본 경로에서 읽는다."""
    ok, out = _adb(console, index, "shell ip route show table all")
    if not ok:
        return None
    for line in (out or "").splitlines():
        parts = line.split()
        if len(parts) >= 3 and parts[0] == "default" and parts[1] == "via":
            return parts[2]
    return None


def index_code(console, index):
    """이 인스턴스에 로그인된 계정 code. 토큰이 없으면(로그아웃) None.

    accounts.json 의 프록시는 **계정별**인데 우리가 조작하는 단위는 인덱스다.
    그 둘을 잇는 유일한 사실은 인스턴스 안의 토큰이다 — 그래서 읽어서 맞춘다.
    (list2 에는 계정 정보가 없고, 인덱스↔serial 매핑도 코드가 보증하지 않는다.)
    """
    ok, out = _adb(console, index,
                   f"shell su -c 'base64 /data/data/{PKG}/files/datastore/karrot_token.ds'")
    b64 = ""
    if ok:
        b64 = "".join(x.strip() for x in (out or "").splitlines()
                      if x.strip() and " " not in x.strip())
    if not b64:
        return None
    try:
        import base64 as _b64
        d = parse_token_ds(_b64.b64decode(b64))
    except Exception:
        return None
    code = _jwt_sub(d.get("refresh") or "") or _jwt_sub(d.get("access") or "")
    return str(code) if code else None


def _account_proxies(accounts_fp):
    """{code: proxy} — 프록시가 지정된 계정만."""
    import json
    try:
        with open(accounts_fp, encoding="utf-8") as f:
            rows = json.load(f)
    except Exception:
        return {}
    out = {}
    for r in rows or []:
        code = str((r or {}).get("code") or "").strip()
        px = ((r or {}).get("proxy") or "").strip()
        if code and px:
            out[code] = px
    return out


def apply_account_proxies(accounts_fp="./accounts.json", console=None,
                          app_dir=".", endpoint_for=None, log=None):
    """계정에 지정된 프록시를 그 계정이 있는 인스턴스의 전역 프록시로 건다.

    `endpoint_for(proxy_url)` 는 게스트에 넣을 "host:port" 를 돌려주는 함수다.
    인증이 필요한 업스트림은 릴레이가 만든 로컬 주소를 돌려주고, 인증이 없으면
    그대로 host:port 를 돌려주면 된다. 안 넘기면 자격증명 없는 프록시만 직접
    적용하고, 자격증명이 있는 것은 **건드리지 않고 경고한다** — 자격증명을 떼고
    꽂으면 프록시가 거부해 그 인스턴스가 통째로 인터넷이 끊긴다.

    반환 {index: 적용된 endpoint 또는 None}. 실패한 인덱스는 값이 None 이다.
    """
    log = log or (lambda m: None)
    console = console or find_ldconsole()
    if not console:
        log("[프록시] ldconsole 을 못 찾아 게스트 프록시를 건드리지 않습니다")
        return {}
    want = _account_proxies(accounts_fp)
    if not want:
        log("[프록시] 계정에 지정된 프록시가 없습니다 — 게스트는 직결로 둡니다")
    out = {}
    for idx in fleet_indexes(app_dir, log=None):
        code = index_code(console, idx)
        if not code:
            log(f"[프록시] index {idx}: 로그인된 계정이 없어 건너뜁니다")
            out[idx] = None
            continue
        px = want.get(code)
        if not px:
            # 프록시를 뗀 계정은 게스트도 직결로 되돌린다. 안 되돌리면 예전
            # 프록시를 계속 타다가 그게 죽는 순간 조용히 인터넷이 끊긴다.
            if get_guest_proxy(console, idx):
                set_guest_proxy(console, idx, None, log=log)
                log(f"[프록시] index {idx}({code[:6]}): 해제 — 직결")
            out[idx] = None
            continue
        if endpoint_for is not None:
            ep = endpoint_for(px)
        elif "@" in px:
            log(f"[프록시] index {idx}({code[:6]}): 자격증명이 있는 프록시라"
                " 릴레이 없이는 못 겁니다 — 그대로 둡니다")
            out[idx] = None
            continue
        else:
            ep = px.split("//", 1)[-1]
        if not ep:
            out[idx] = None
            continue
        if get_guest_proxy(console, idx) == ep:
            out[idx] = ep          # 이미 그대로 — adb 를 더 쓰지 않는다
            continue
        out[idx] = ep if set_guest_proxy(console, idx, ep, log=log) else None
        if out[idx]:
            log(f"[프록시] index {idx}({code[:6]}) → {ep}")
    return out
