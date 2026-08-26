"""
응답 JSON → 매물 레코드 정규화.

당근 응답 스키마는 캡처 후 확정. 실제 필드 경로를 아래 MAP 에 한 번만 맞추면
collect/monitor 전부 동작. 지금은 흔한 키를 heuristic 으로 탐색(느슨).
"""
import json

# 캡처 응답 확인 후 실제 경로로 교체 (점표기 지원: "data.articles")
MAP = {
    "list_path": "",          # 목록 배열이 있는 키 경로. 빈값이면 자동탐색
    "id": "id",
    "title": "title",
    "price": "price",
    "area": "area",
    "region": "region_name",
    "lat": "lat",
    "lng": "lng",
    "created_at": "created_at",
    "image": "image_url",
}


def _dig(obj, dotted):
    cur = obj
    for part in dotted.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            return None
    return cur


def _find_list(obj):
    """목록 배열 자동탐색: dict 원소를 담은 최장 list."""
    best = []
    def walk(o):
        nonlocal best
        if isinstance(o, list):
            if o and isinstance(o[0], dict) and len(o) > len(best):
                best = o
            for x in o:
                walk(x)
        elif isinstance(o, dict):
            for v in o.values():
                walk(v)
    walk(obj)
    return best


def extract(resp_json):
    if isinstance(resp_json, str):
        resp_json = json.loads(resp_json)
    items = _dig(resp_json, MAP["list_path"]) if MAP["list_path"] else None
    if not isinstance(items, list):
        items = _find_list(resp_json)
    out = []
    for it in items:
        if not isinstance(it, dict):
            continue
        out.append({
            "id": it.get(MAP["id"]),
            "title": it.get(MAP["title"]),
            "price": it.get(MAP["price"]),
            "area": it.get(MAP["area"]),
            "region": it.get(MAP["region"]),
            "lat": it.get(MAP["lat"]),
            "lng": it.get(MAP["lng"]),
            "created_at": it.get(MAP["created_at"]),
            "image": it.get(MAP["image"]),
            "_raw": it,
        })
    return [r for r in out if r["id"] is not None]
