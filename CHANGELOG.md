# Changelog — S-Patch AccurKardia Automation

## [v1.0.6] — 2026-07-08 (updated 2026-07-09)

### Fixed
- **Windows에서 테스트 시작 즉시 크래시 ("Test failed — No time zone found with key America/Chicago")**: Windows에는 시스템 타임존 DB가 없어 APScheduler의 로컬 타임존 조회가 실패 → 런 전체 중단되던 문제 (테스터 리포트)
  - `requirements.txt`에 `tzdata` 추가 — 근본 수정 (`requirements.txt`)
  - 타임존 조회 실패 시에도 크래시 대신 UTC 폴백으로 스케줄러 계속 실행 (`src/scheduler.py`)
- **예기치 못한 인앱 오류 팝업으로 자동화 정지**: "Test failed" / "No time zone" 등 알 수 없는 오류 팝업 감지 시 증거 스크린샷 저장 후 자동 해제하고 진행 (`src/workflows/popup_handler.py`)
- **[iOS] 야간 시스템 알림으로 장기 실행 정지**: 'iOS 업데이트 설치되지 않음' 시스템 모달이 02~08시 모든 탭을 차단 → 주입/BT/airplane 6시간 연속 실패하던 문제. `autoDismissAlerts` capability + 팝업 핸들러의 시스템 알림 자동 해제 (`src/driver_ios.py`)
- **[iOS] 웹 실행 세션에서 BT 차단 사이클 스킵**: `App-Prefs:Bluetooth` 딥링크가 웹 생성 Appium 세션에서 동작하지 않아 BT 사이클이 통째로 건너뛰어지던 문제 — Settings 재실행 + Bluetooth 행 직접 탭 폴백, 실패 시 진단 스크린샷 저장 (`src/workflows/connectivity_ios.py`). 실기기 풀 사이클(BT 10분 + airplane 5분) 검증 완료
- **웹 기기 라벨 "Android" 하드코딩**: iOS run에서 대시보드/test report 기기명이 "iPhone14,4 Android"처럼 표시되던 문제 — iOS/Android 자동 구분 (`web/app.py`)
- **iOS 이벤트 대시보드 미표시**: iOS run이 emit하는 `*_ios` 이벤트를 정규화해 suite 카드·로그·진행률이 양 플랫폼에서 렌더되도록 수정 (`web/app.py`)

### Added
- **[Beta] iOS 자동화 (Android 동등 기능)**: serial/menu/main/diary/menu-study regression 36 TC, go_to_main(BLE 연결·Study 시작), 시간별 symptom 주입, BT 차단(설정 앱 스위치 — 제어 센터 타일은 BLE 유지되어 부적합)·에어플레인 모드 테스트 (`src/*_ios.py`, `src/workflows/connectivity_ios.py`)
  - ⚠️ 검증 환경: iPhone 13 mini (iOS 18.6.2) 1대, 개발 Mac 한정. WDA 기기별 서명·설치 필요 — 테스터 배포 체계(사전 서명 WDA.ipa) 준비 중
- **웹 UI 플랫폼 선택**: Android/iOS 선택 → iOS 기기 목록(idevice_id) 표시, iOS run은 `main_ios.py`로 실행 (`web/app.py`, `web/templates/index.html`) — iOS는 상기 Beta 제약 동일
- **iOS 테스터 배포 파이프라인**: Mac 배포 ZIP에 iOS 지원 통합 — 사전 서명 WDA.ipa 자동 설치(등록 UDID 전용), `iproxy` 없으면 `pymobiledevice3` 폴백(brew 불필요), Developer Mode 안내. 관리자용 WDA.ipa 빌드 스크립트 포함 (`scripts/build_dist_bundle_mac.py`, `scripts/build_wda_ipa.sh`)
- **웹 UI run 중 설정 잠금**: 테스트 실행 중에는 설정 폼을 잠그고 안내 배너 표시 — 시작 시점에 확정되는 값을 mid-run에 바꿔도 반영되는 것처럼 보이던 혼동 방지. Stop / Inject Now / interval 변경은 계속 사용 가능 (`web/templates/index.html`)
- **iOS 앱 버그 리포트**: BT 상태 카드 UI 미갱신 (재현 조건·증적 포함, `docs/bug_reports/ios_bt_ui_sync_bug.txt`)
- **RN testID 요청 문서**: 좌표 기반 → element 기반 전환용 (`docs/testid_request_ios.txt`)
- **README 전면 개편 (영문)**: 플랫폼별 현황, 실행 흐름, regression 스위트 표, iOS Beta 상세, 배포 ZIP 가이드, 트러블슈팅

## [v1.0.5] — 2026-06-30

### Fixed
- **Symptom injection 미실행 버그**: `symptom_add_text` 설정값이 `"Add Diary"`로 되어 있어 UI health check가 항상 실패 → scheduler가 injection/BT disconnect/airplane mode 테스트를 전혀 시작하지 못하는 문제 수정 (`config/accurkardia.yaml`)
- **`check_connectivity` 오탐**: `on_main_screen` 판단을 `"Add Diary"` 하드코딩에서 config 기반 `symptom_add_text`로 변경 (`src/driver.py`)
- **`_try_add_diary_wifi_off` / `_try_add_diary_bt_off`**: 하드코딩된 `"Add Diary"` 제거, activity 섹션 제거 (AK 앱에 없음), submit 버튼을 config `log_symptoms_submit_text` ("Save") 로 변경 (`src/driver.py`)
- **`open_menu` 기기 호환성**: content-desc 탐색 대상 확장 ("Settings", "More options" 등), top-right 영역에서 `clickable=true` View/ImageView/ImageButton 탐색으로 좌표 의존도 감소 (`src/regression/helpers.py`)
- **`_is_menu_open` 인디케이터**: "Terms and Information", "Live Streaming", "Privacy", "About" 추가 (`src/regression/helpers.py`)
- **`open_menu` 진단**: 탭 직후 스크린샷(`open_menu_after_tap_N`) 추가 — 실패 원인 즉시 파악 가능
- **`go_to_main` 느린 디바이스 timeout 오탐**: BLE 연결이 120s를 약간 초과하는 느린 디바이스(예: SM-A325N)에서 실제로는 main screen에 도달했음에도 "Main screen not reached after 120s" 예외가 발생하던 문제 수정
  - 타임아웃 직후 screen을 재확인해 이미 main screen이면 성공으로 처리
  - loading overlay가 "Log Symptoms"를 가리는 동안에도 "My Study Progress" / "Device Status" 텍스트로 main screen 감지
  - `go_to_main` 진입 시 초기 체크도 3개 텍스트 모두 확인 (`src/regression/helpers.py`)

## [v1.0.0] — 2026-05-28

### Added
- **Battery card**: `battery_status` event 처리 추가 — 앱 화면에서 "Good"/"Low"/"Critical" 텍스트 감지 시 배터리 카드 실시간 업데이트 (`web/templates/index.html`, `src/driver.py`)
- **Field persistence**: serial number, Slack webhook을 localStorage에 저장 — 테스트 실행 중 새로고침해도 값 유지, 테스트 종료 시 자동 초기화 (`web/templates/index.html`)
- **Slack**: `slack_daily_report`, `slack_bug_report` 함수 추가 (`src/slack.py`)
- **symptom_inject**: `ACTIVITIES = []` export 추가 — run.py import 오류 수정 (`src/workflows/symptom_inject.py`)

### Fixed
- **Connectivity cards**: `bt_disconnect_done` 이벤트 발생 시 BT Signal / BT Diary / BT Reconnect / ECG Check 카드 모두 pass로 추론 표시
- **Connectivity cards**: `airplane_mode_done` 이벤트 발생 시 WiFi / WiFi Diary / WiFi Restore 카드 모두 pass로 추론 표시
- **Airplane mode**: Android 12+ (Pixel 7 등)에서 `settings put global airplane_mode_on` 명령이 권한 문제로 무시되던 버그 수정 → `adb shell cmd connectivity airplane-mode disable` 으로 교체 (`src/workflows/airplane_mode.py`)
- **WiFi ADB radio button ID conflict**: HTML form의 `id="conn-wifi"` 가 connectivity 카드 `id="conn-wifi"` 와 충돌하여 WiFi 카드가 업데이트 안 되던 버그 수정 → radio button ID를 `adb-usb` / `adb-wifi` 로 변경
- **go_to_main() Step 2/3 Continue tap**: `tap_text(contains=False)` + `@retry(tries=3)` 조합으로 ~37s 낭비 후 120s timeout 발생하던 문제 → `contains=True` 로 변경, pre-tap sleep 추가

## 2026-05-27 (earlier)

### Added
- **Real-time connectivity grid**: 웹 UI에 9개 connectivity 카드 추가 (Connection / BT Signal / BT Diary / BT Reconnect / ECG Check / WiFi / WiFi Diary / WiFi Restore / Battery)
- **HTML report**: Slack-style card layout으로 리디자인

### Fixed
- **BT disconnect workflow**: `check_connectivity()` 호출 추가 — BT 끊김/재연결 이벤트 감지 보강
- **Host sleep recovery**: injection chain 끊김 방지, web runner에 KeepAwake 추가

## 2026-05-22

### Fixed
- AK 앱 이미 측정 중일 때 BT reconnect spinner 상태에서도 측정 중 감지
- study 이미 활성화 상태로 재시작 시 serial/menu/signal regression 스킵
- AK main screen 감지 로직 수정, Connect 탭 보호
- Step 1에서 기기가 이미 등록된 경우 EditText 없는 케이스 처리
- BT disconnect / airplane mode 테스트 진행 중 symptom 주입 블락

## 2026-05-21

### Added
- **BT disconnect 주기 테스트**: 설정된 간격으로 BT를 끊고 재연결하는 주기 테스트
- **Airplane mode 주기 테스트**: 설정된 간격으로 airplane mode 활성화/비활성화 주기 테스트
- **Connectivity regression suite**: BT / WiFi 연결 상태 검증 테스트 스위트

### Fixed
- BT/airplane 주기 루프 순차 실행 보장, airplane mode 중 connectivity monitor 일시 중지

## 2026-05-15

### Fixed
- skip-regression 모드에서 connectivity 테스트 먼저 실행되도록 수정
- ADB WiFi keepalive 추가, stay_awake 옵션, scheduler misfire grace time 설정
- 웹 서버 포트 5002→5003 수정
- Python 설치 경로 자동 탐색 로직 보강

## 2026-05-13

### Fixed
- 주입 전 main screen 이동 네비게이션 보강
- 950 popup dismiss 로직 개선 (`Ok`/`OK` 목록 처리)
- WiFi ADB 연결 시 WiFi-off TC 스킵
