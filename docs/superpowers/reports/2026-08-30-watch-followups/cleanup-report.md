# Cleanup Report

## Commit
`880e668` fix: 탭 인덱스 동적 조회·테스트 워킹디렉토리 고정

## Fix 1: `_render_alert.py` wrong tab index
- **Issue**: `setCurrentIndex(2)` targeted 에뮬레이터 tab, not 매물 감시 tab after tab layout changed
- **Solution**: Look up "매물 감시" tab by title instead of hardcoding index; fallback to index 1 if not found
- **Changed**: Lines 10–20 to dynamically find and set tab

## Fix 2: Test working directory issue  
- **Issue**: `main.py` opens `"./OUT.json"` at construction; tests failed when run from repo root (123→44 regression, simulating real failure)
- **Solution**: Both `unified_tab_wiring_test.py` and `article_watch_wiring_test.py` now `os.chdir()` to their own directory before importing main
- **Changed**: Lines 8–10 in both files to compute app_dir, insert to sys.path, and chdir

## Test Results
From `manual_gui/`:
- `unified_tab_wiring_test.py`: `===== 123/123 PASS =====`
- `article_watch_wiring_test.py`: `===== 27/27 PASS =====`
- `article_watch_test.py`: `===== 177/177 PASS =====`

From repo root:
- `unified_tab_wiring_test.py`: `===== 123/123 PASS =====` (✓ no regression)
- `article_watch_wiring_test.py`: `===== 27/27 PASS =====` (✓ consistent)

## Verification
Both test files now report identical totals regardless of invocation directory; OUT.json is found in all cases.
