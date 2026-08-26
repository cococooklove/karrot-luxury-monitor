# 통합 완료 — daangn_ext 를 클라 프로젝트에 붙인 상태

manual/auto 각 프로젝트에 `daangn_ext/` 드롭인 + `daangn/api.py` 교체 = 통합 끝.
클라의 기존 코드(model.Product, UI, DB, 텔레그램, 프록시설정)는 그대로 유지.

## manual (검증 완료 · 실행 가능)

```
integrated/manual/
  daangn/        ← 클라 원본(model/data/errors) + api.py(교체됨: robust+토큰+필터+적응형)
  daangn_ext/    ← 신규 모듈 일체
  runner.py      ← 헤드리스 실행 증명(PyQt 없이 데이터층 구동)
```

**실행 증명** (실제 당근 수집):
```
python runner.py --keyword 구찌 --gu "강남구-381" --exclude 레플 미러
→ 776건 수집 (구단위+가격분할 적응형, 상한 290 돌파)
  클라 Product.get_price_str() 정상(₩ 포맷)·가격정렬·끌올·제외필터 동작
```
동 단위(기존 호환): `--dong "역삼동-6035"` / 계정+프록시: `--accounts accounts.json` / 저장: `--csv out.csv`

### GUI(PyQt) 배선 — 클라 프로그램 버튼/입력 연결
`daangn/api.py` 는 이미 교체됨. 남은 건 UI 이벤트 → api 호출부만:
- 검색 시작 핸들러: `api.get_products_adaptive(...)` (구단위) 또는 `api.get_products(...)` (동단위) 호출.
  둘 다 `access_token`·`rule` 인자 지원(옵션). `controller.py` 의 워커가 이 함수를 부르게 인자만 추가.
- 계정+프록시 추가 다이얼로그: `AccountStore.add_pair(refresh, proxy, label)`.
- 키워드/추가키워드/제외 입력: `KeywordRule(required, extra, extra_mode, exclude)` 생성해 전달.
- 검색 전: `TokenManager.refresh_all()` 1회.

## auto (동일 패턴 드롭인)

```
integrated/auto/
  daangn/api.py  ← 교체본(aiohttp: robust async + 토큰 + 필터)
  daangn_ext/    ← 동일 모듈 (async 적응형 collect_region_async 포함)
```
클라 auto 프로젝트에 `daangn_ext/` 복사 + `daangn/api.py` 교체.
24시간 루프 배선(예제 `daangn_ext/integration_examples.py`):
- 매 사이클 `tm.refresh_all()` → 지역별 `get_products(...)`(또는 구단위 `collect_region_async`)
- 사이클 끝 `await asleep_between(min, max)` (휴식 랜덤)
- 기존 DB중복방지·가격변동·텔레그램·시트 로직은 그대로.

## 요구기능 → 통합 위치 (전부 반영)

| 요구 | 통합 위치 |
|---|---|
| 검색 전 토큰 갱신(30분) | `TokenManager.refresh_all/ensure` (api 호출 전) |
| 계정+프록시 추가 | `AccountStore.add_pair` |
| 키워드+추가키워드 포함필터 | `KeywordRule` → api `rule=` |
| 휴식 n~n초 랜덤(auto) | `rest_scheduler.asleep_between` |
| 빈응답 재시도(막힘 해결) | `daangn/api.py`(robust) 자동 |
| 전국 고속(구단위+가격분할) | `api.get_products_adaptive` / `collect_region(_async)` |
| 정렬·엑셀·DB·텔레·프록시 | 클라 기존 코드 유지 |

## 검증 요약

- `delivery/smoke.py` 7/7 (로직)
- `delivery/feature_test.py` (동단위 실수집·필터·정렬)
- `integrated/manual/runner.py` **776건 실수집**(구단위 적응형, 클라 Product 통합)
