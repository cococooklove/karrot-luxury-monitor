# 마지막 빨간 테스트 4종 — 진단 및 처리 결과

## git log --oneline -2 (작업 후)
```
fd87693 test: 마지막 빨간 테스트 4종 정리 — 삭제 2·설계변경 반영 1·SKIP관례 적용 1
f4756c1 test: 비밀파일 없으면 건너뛰게·JWT 헬퍼 나노스 충돌 제거
```

## git status --short (작업 후)
```
?? cleanup-report.md
?? headless-sweep-report.md
?? observed-cap-report.md
?? red-tests-report.md
?? residual-fixes-report.md
?? sweep-engine-report.md
```
(위 6개는 이전 세션들이 남긴, manual_gui 밖 워크트리 루트의 무관한 리포트 파일 —
이번 작업 범위 밖이라 손대지 않음. manual_gui 아래는 전부 커밋됨.)

## 파일별 진단

### `_area_test.py` — 삭제
초기 커밋(1fec84c) 이후 한 번도 수정되지 않은 스크래치 프로브. 시도>구 2단계 트리를
가정하고 리프의 `UserRole`이 `"강남구-381"`(구 이름-구ID) 형식이라고 assert한다.
실제 `main.py:_build_auto_area_tree`(2697행)는 시도>구>동 3단계 트리이고, `UserRole`은
동 단위 리프에만 `"{동이름}-{동ID}"`(예 `"역삼동-6035"`) 형식으로 붙는다 — 구 레벨
노드는 `setData` 자체가 없다. `강남구-381`은 절대 매치되지 않는 죽은 가정.
`autoAreaTree` 존재·배선은 `unified_tab_wiring_test.py`(148/148)와
`_construct_test.py`(9/9)가 이미 더 견고하게 덮는다. raw assert만 쓰고 R/ck 관례가
전혀 없어 스캐폴딩과도 맞지 않음 → 삭제.

### `_pool_test.py` — 삭제
`proxies.txt` 필수 + 라이브 당근 API 호출. R/ck/exit 규약 없이 print만 하는
일회성 프로브(`FileNotFoundError: proxies.txt`로 즉시 죽음). 같은 대상인
`adaptive.collect_region(..., proxies=[...])`의 풀분산/로테이션 동작은
`robust_test.py`(82행, 144행)가 오프라인 목으로 이미 회귀 검증 중(29/29, 유지 리스트에 포함)
→ 더 나은 커버리지로 대체됨, 삭제.

### `_proxy_ui_test.py` — 설계변경 반영(코드 수정 아님, 테스트를 현재 모양으로 갱신)
`proxyLabel`/`autoProxyLabel`(별도 QLabel)의 존재를 assert했으나 그 위젯은 설계상
없어졌다. 현재는 `_refresh_proxy_labels()`(main.py:3001)가 `proxyViewBtn`/
`autoProxyViewBtn` **버튼 자체의 문구**를 `"프록시 목록 (N)"`으로 갱신하는 방식.
버튼 존재는 `button_test.py`/`full_test.py`/`_construct_test.py`가 이미 확인하지만
문구가 실제 프록시 수를 반영하는지는 아무 데도 없었다 — R/ck 관례로 재작성해
`_refresh_proxy_labels()` 호출 후 두 버튼 문구가 `f"프록시 목록 ({n})"`인지 검증.
결과: 5/5 PASS, exit 0.

### `nationwide_test.py` — SKIP 관례 적용(코드 버그 아님, proxy_test.py 패턴 적용)
동 단위 폴백 버그(구 ID를 넘기면 조용히 대표 동 1개로 폴백 — 실측 강남구 258건이
전부 역삼동, 1,286건 누락)는 이미 이전 커밋(`7056224`)에서 `load_dong_regions()`로
수정 완료돼 있었고 이 파일도 그때 이미 그 함수를 쓰도록 고쳐져 있었다 — 이건 실제
버그가 아니라 "찾았지만 이미 고쳐진 것"이었다. 남은 문제는 두 가지: (1) `proxies.txt`
필수 구간에 SKIP 관례가 없어 파일 없으면 그냥 `FileNotFoundError`로 죽음, (2) 다른
세션의 스크래치패드(`efe67086-...`)를 가리키는 깨진 `OUT` 경로가 하드코딩돼 있었음.
`proxy_test.py`(f4756c1) 관례대로 재작성: `OUT.json` 로딩·`KeywordRule` 필터링은
네트워크 없이 항상 검증, `proxies.txt` 없으면 `[SKIP]` 찍고 exit 0. 실행 경로는
`os.chdir`로 자기 디렉터리 기준 상대경로(`"OUT.json"`, `"proxies.txt"`)로 고정.
결과: 4/4 PASS, exit 0.

## 유지 리스트 회귀 검증 (literal tail)
```
article_watch_test.py         ===== 191/191 PASS =====   EXIT:0
unified_tab_wiring_test.py    ===== 148/148 PASS =====   EXIT:0
watch_listing_test.py         ===== 47/47 PASS =====     EXIT:0
article_watch_wiring_test.py  ===== 27/27 PASS =====     EXIT:0
keyword_router_test.py        ===== 104/104 PASS =====   EXIT:0
sweep_queue_test.py           ===== 29/29 PASS =====     EXIT:0
supervisor_test.py            ===== 20/20 PASS =====     EXIT:0
backfill_test.py              ===== 26/26 PASS =====     EXIT:0
sweep_engine_test.py          ===== 57/57 PASS =====     EXIT:0
headless_sweep_test.py        ===== 101/101 PASS =====   EXIT:0
notify_test.py                54/54 PASS                 EXIT:0
robust_test.py                29/29 PASS                 EXIT:0
_construct_test.py            ===== 9/9 PASS =====       EXIT:0
button_test.py                ===== 30/30 PASS =====     EXIT:0
full_test.py                  ===== 17/17 PASS =====     EXIT:0
proxy_test.py                 ===== 6/6 PASS =====       EXIT:0
e2e_chain_test.py             10/10 PASS                 EXIT:0
```
전부 목표 카운트와 정확히 일치, 회귀 없음.

## 디렉터리 전체 `*_test.py` 전수 실행 (26개, 알파벳순)
```
_auto_test.py EXIT:0 :: PASS (신규 매물 알림 시뮬레이션)
_construct_test.py EXIT:0 :: ===== 9/9 PASS =====
_proxy_ui_test.py EXIT:0 :: ===== 5/5 PASS =====
_ux_test.py EXIT:0 :: PASS: 지역검색+전체선택/해제 동작
app_api_test.py EXIT:0 :: 44/44 PASS
article_watch_test.py EXIT:0 :: ===== 191/191 PASS =====
article_watch_wiring_test.py EXIT:0 :: ===== 27/27 PASS =====
backfill_test.py EXIT:0 :: ===== 26/26 PASS =====
button_test.py EXIT:0 :: ===== 30/30 PASS =====
e2e_chain_test.py EXIT:0 :: 10/10 PASS
full_test.py EXIT:0 :: ===== 17/17 PASS =====
headless_sweep_test.py EXIT:0 :: ===== 101/101 PASS =====
keyword_router_test.py EXIT:0 :: ===== 104/104 PASS =====
ldwin_sim_test.py EXIT:0 :: ok (unittest)
ldwin_test.py EXIT:0 :: ok (unittest)
nationwide_test.py EXIT:0 :: ===== 4/4 PASS =====
notify_test.py EXIT:0 :: 54/54 PASS
proxy_test.py EXIT:0 :: ===== 6/6 PASS =====
robust_test.py EXIT:0 :: 29/29 PASS
supervisor_test.py EXIT:0 :: ===== 20/20 PASS =====
sweep_engine_test.py EXIT:0 :: ===== 57/57 PASS =====
sweep_queue_test.py EXIT:0 :: ===== 29/29 PASS =====
throttle_test.py EXIT:0 :: ===== 22/22 PASS =====
unified_tab_wiring_test.py EXIT:0 :: ===== 148/148 PASS =====
variance_test.py EXIT:0 :: ✅ 편차 0.4% — 동일 조건 반복 결과 안정
watch_listing_test.py EXIT:0 :: ===== 47/47 PASS =====
[exited with code 0]
```
전부 exit 0. 빨간 테스트 없음.
