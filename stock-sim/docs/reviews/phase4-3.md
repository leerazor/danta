# Phase 4 리뷰 3회차: 대시보드 자동 갱신 (커밋 ade5f0e)

- 대상: `templates/dashboard.html.j2`, `scripts/register_schedule.ps1`(신규), `tests/test_render.py`, `docs/architecture.md` 9절
- 브랜치: `worktree-auto-refresh-dashboard`
- 기준: CLAUDE.md 2절·7절·8절, architecture.md 9절, `config.py::resolve_period`, `cli.py` run 흐름

## 판정: **PASS**

High 0 · Med 0 · Low 5. blocking finding은 없다. Low는 기록만 하고 non-blocking 제안으로 남긴다.

## 테스트 실행 원문

`stock-sim/`에서 `uv run pytest`:

```
collected 155 items / 2 deselected / 153 selected
... (test_render.py 16건 포함, 전부 통과)
====================== 153 passed, 2 deselected in 2.52s ======================
```

2 deselected는 `-m network` 마커 테스트다(기본 제외). 테스트는 네트워크 없이 돈다.

## findings

| 심각도 | 파일:줄 | 문제 | 근거 | 수정 제안 |
|---|---|---|---|---|
| Low | `scripts/register_schedule.ps1:24` | Windows PowerShell 5.1에서 `*>>` 리다이렉트는 로그를 UTF-16LE로 쓰고, Python `logging`이 쓰는 stderr 줄을 `NativeCommandError` 레코드로 감싼다(첫 줄에 `python.exe : …`, `CategoryInfo` 같은 줄이 붙는다). 동작에는 문제가 없고 로그를 읽기가 불편할 뿐이다. | PS 5.1의 Out-File 기본 인코딩은 Unicode이고, 네이티브 stderr를 리다이렉트할 때 ErrorRecord로 변환하는 것은 5.1의 알려진 동작이다. 리다이렉트는 `$cmd` 문자열 안에 있다(`*>> '$log'`). | 필요하면 `cmd.exe /c "... >> log 2>&1"`로 실행하거나 파이썬 쪽에 로그 파일 핸들러를 둔다. |
| Low | `scripts/register_schedule.ps1:24` | 경로를 작은따옴표로 감싸므로 공백과 한글은 안전하다. 다만 경로에 `'`가 있으면 명령이 깨진다. 현재 경로에는 `'`가 없다. | `$cmd = "Set-Location -LiteralPath '$root'; & '$uv' … *>> '$log'"`. 바깥은 `` `"$cmd`" ``이고 `$cmd`에는 큰따옴표가 없어서 `-Command` 인자가 하나로 넘어간다. | `$root.Replace("'", "''")` 식 이스케이프(선택). |
| Low | `scripts/register_schedule.ps1:11-15` | 작업이 없을 때 `-Unregister`를 실행하면 `Unregister-ScheduledTask` 오류가 그대로 나온다. | 존재 여부를 확인하지 않고 바로 호출한다. | `Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue`로 먼저 확인한다(선택). |
| Low | `cli.py:39-45`, `config.py:165-166` (이번 변경의 결과) | `end: auto`와 매일 실행이 합쳐져 캐시 키(`<코드>_<fetch_start>_<end>.csv`)가 매일 바뀐다. 그래서 실행마다 11개 계열(10종목 + 지수)을 새로 받고, 이전 CSV는 `data/cache/`에 계속 쌓인다(약 11파일/일). 새 일봉을 반영하려면 필요한 재수집이라 결함은 아니다. 평일 공휴일 다음 날에는 같은 데이터를 한 번 더 받는다. | `resolve_period`: `end = today - 1일`이고 `fetch_start = end - months - warmup_days`라서 두 날짜가 모두 매일 이동한다. `_all_cached`는 정확한 키로만 판정한다. 화~토 스케줄은 일·월 실행(end=토·일)을 빼므로 주말에 새 데이터 없이 재수집하는 일은 없다. 이 부분은 맞다. | 오래된 캐시 정리는 별도 과제로 둔다(범위 밖). |
| Low | `src/stock_sim/render.py:125-127` | `dashboard.html`을 바로 덮어쓴다(원자적 교체가 아님). 5분 주기 meta refresh가 쓰기 도중과 겹치면 잘린 HTML이 한 번 보일 수 있다. 다음 새로고침에서 바로 복구된다. | `with out_path.open("w", …) as f: f.write(html)` | 임시 파일에 쓴 뒤 `os.replace`로 교체한다(선택, dashboard-builder 소유). |

## 중점 확인 결과

1. **R1 키 노출(로그 리다이렉트 포함)**: 리다이렉트는 stdout·stderr를 모두 받는다. 그래서 이 로그에 들어갈 수 있는 출력원을 확인했다.
   - `kis_client.py:65-66` `_mask`는 앞 4자리만 남긴다. `:87` 초기화 로그도 마스킹된 키만 찍는다.
   - `:95-97` `_scrub`는 key·secret·token을 응답 메시지에서 치환한다. `:211`에서 `msg_cd`·`msg1`에 적용된다.
   - 네트워크 예외는 `type(exc).__name__`만 남긴다(`:205`). 그래서 요청 헤더(appkey·appsecret)가 메시지에 들어가지 않는다.
   - `cli.py:122`은 urllib3을 WARNING으로 올린다. `:126-131` 예외는 `exc_info=args.verbose`이고, 스케줄 명령에는 `--verbose`가 없다.
   - ps1 자체는 `.env`를 읽지 않고 키를 다루지 않는다. 로그 경로 `data/logs/`는 `stock-sim/.gitignore`의 `data/`에 포함돼 커밋되지 않는다.
2. **R2**: `stock-sim/`에서 `trading/|order-cash|inquire-balance`를 검색하면 기존 리뷰 문서(체크리스트 문구)에서만 나온다. 이번 커밋 파일에서는 0건이다.
3. **R3**: ps1은 `config.yaml`을 그대로 쓴다(`env: DEV`). 환경 전환 로직은 없다.
4. **8절 규약**:
   - `<meta http-equiv="refresh" content="300">`는 HTML 표준 태그라서 외부 JS에 해당하지 않는다.
   - `generated_at[:16]|replace('T',' ')`는 문자열을 자르고 바꾸는 표시 변환일 뿐이다. 수치를 계산하지 않으므로 "템플릿은 계산하지 않는다" 규칙에 맞는다. 예시값 `2026-09-30T09:15:00+09:00`은 `2026-09-30 09:15`로 표시된다. 날짜 부분은 `YYYY-MM-DD` 표기를 유지한다.
   - 색 토큰·구조 변경은 없다.
5. **ps1 따옴표·경로·PS 5.1 호환**:
   - 파일 앞 3바이트가 `ef bb bf`(UTF-8 BOM)라서 5.1이 한글 문자열을 올바르게 읽는다.
   - `$PSScriptRoot`, `Join-Path`, `New-ScheduledTask*`, `Register-ScheduledTask -Force`는 모두 5.1에서 쓸 수 있다. `-DaysOfWeek Tuesday, …, Saturday`와 `-At "07:30"` 문자열 바인딩도 유효하다.
   - `-WorkingDirectory $root`와 `Set-Location -LiteralPath`가 이중으로 걸려 있어 cwd가 보장된다. 그래서 `--directory src`와 `../config.yaml` 상대 경로가 맞는다(architecture.md 9절과 같은 명령).
   - 주의: 이 세션의 worktree 격리 정책 때문에 `powershell.exe` 파서 검증(ParseFile)은 실행하지 못했다. 위 내용은 정적 분석 결과다. 스케줄러는 등록하지 않았다.
6. **end:auto와 화~토 조합**: 논리는 맞다. 화요일 07:30에 돌면 end는 월요일이고, 토요일에 돌면 end는 금요일이다. 즉 직전 거래일 종가까지 반영된다. 매일 재수집하는 것은 새 데이터 때문에 필요하다(위 Low 4).
7. **테스트 적정성**: `test_auto_refresh_and_generated_time`은 meta 태그가 정확한 문자열로 있는지, 생성 시각이 분 단위 `YYYY-MM-DD HH:MM`으로 보이는지 확인한다. 예시 JSON 기반이라 네트워크 없이 돈다. 변경 범위에 맞다. ps1은 테스트 대상이 아니다(OS 스케줄러 의존). 이는 타당하다.
8. **architecture.md 9절**: 명령표에 한 줄, 설명에 한 문단이 추가됐다. ps1 사용법(`-Unregister`)과 로그 경로가 스크립트와 일치한다.

## 확인한 항목

- [x] R1 시크릿 출력 코드 없음, 로그 마스킹 경로 확인
- [x] R2 이번 변경 파일에 금지 경로 문자열 0건
- [x] R3 PROD 기본값 아님, 자동 전환 없음
- [x] R4 계좌·잔고·개인정보 없음(생성 시각만 추가)
- [x] `uv run pytest` 153 passed, 네트워크 불필요
- [x] 템플릿 잔여물 위험 없음(`generated_at`은 필수 키, 문자열 슬라이스)
- [x] 외부 JS 없음, 템플릿 계산 없음, 스타일 불변
- [x] ps1 UTF-8 BOM, 5.1 cmdlet 호환, 공백·한글 경로 인용(정적 분석)
- [x] 스케줄 요일과 `end: auto` 정합
