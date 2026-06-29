# Changelog — S-Patch AccurKardia Automation

## [v1.0.5] — 2026-06-30

### Fixed
- **Symptom injection 미실행 버그**: `symptom_add_text` 설정값이 `"Add Diary"`로 되어 있어 UI health check가 항상 실패 → scheduler가 injection/BT disconnect/airplane mode 테스트를 전혀 시작하지 못하는 문제 수정 (`config/accurkardia.yaml`)
- **`check_connectivity` 오탐**: `on_main_screen` 판단을 `"Add Diary"` 하드코딩에서 config 기반 `symptom_add_text`로 변경 (`src/driver.py`)
- **`_try_add_diary_wifi_off` / `_try_add_diary_bt_off`**: 하드코딩된 `"Add Diary"` 제거, activity 섹션 제거 (AK 앱에 없음), submit 버튼을 config `log_symptoms_submit_text` ("Save") 로 변경 (`src/driver.py`)
- **`open_menu` 기기 호환성**: content-desc 탐색 대상 확장 ("Settings", "More options" 등), top-right 영역에서 `clickable=true` View/ImageView/ImageButton 탐색으로 좌표 의존도 감소 (`src/regression/helpers.py`)
- **`_is_menu_open` 인디케이터**: "Terms and Information", "Live Streaming", "Privacy", "About" 추가 (`src/regression/helpers.py`)
- **`open_menu` 진단**: 탭 직후 스크린샷(`open_menu_after_tap_N`) 추가 — 실패 원인 즉시 파악 가능

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
