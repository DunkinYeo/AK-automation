============================================================
  S-Patch AccurKardia 자동화 도구  —  macOS 사용 가이드
============================================================

이 도구는 S-Patch AccurKardia 앱의 Regression 테스트와
장기 증상 주입(Log Symptoms)을 자동으로 수행합니다.
개발 지식 없이 누구나 사용할 수 있습니다.

테스트 실행 중에는 Mac이 절전 모드로 전환되지 않도록
자동으로 방지합니다. (caffeinate 사용, AC 전원 연결 권장)


------------------------------------------------------------
  시작 전 확인 — 실행 권한 설정
------------------------------------------------------------

macOS에서 .command 파일을 처음 실행할 때
"개발자를 확인할 수 없습니다" 메시지가 나타날 수 있습니다.

해결 방법:
  방법 1) 파일을 마우스 오른쪽 버튼으로 클릭 → [열기] 선택
  방법 2) 터미널에서 아래 명령어 실행:
            chmod +x install.command run.command STOP.command
  방법 3) 파일을 Finder에서 선택 후 아래 명령어 실행:
            xattr -d com.apple.quarantine install.command run.command STOP.command


------------------------------------------------------------
  1. 최초 1회 설치
------------------------------------------------------------

  1) Android 스마트폰을 USB 케이블로 Mac에 연결합니다.

  2) 스마트폰에서 USB 디버깅을 활성화합니다.
       설정 → 휴대전화 정보 → 소프트웨어 정보
       → [빌드 번호]를 7번 빠르게 탭
       설정 → 개발자 옵션 → USB 디버깅 ON

  3) 스마트폰에 "USB 디버깅을 허용하시겠습니까?" 팝업이 뜨면
     [허용]을 탭합니다.

  4) Finder에서 install.command 를 더블클릭합니다.
     Homebrew, Python, Node.js, ADB, Appium, Python 패키지가
     자동으로 설치됩니다.

  ※ 처음 설치 시 5~10분 정도 걸릴 수 있습니다.
  ※ 설치 중 비밀번호 입력을 요구하면 Mac 로그인 비밀번호를 입력하세요.
     (입력해도 화면에 표시되지 않는 것이 정상입니다)


------------------------------------------------------------
  2. 테스트 실행
------------------------------------------------------------

  1) AccurKardia 앱이 검사 진행 중 상태인지 확인합니다.
     ("My Study Progress" 화면이 표시되어야 합니다)

  2) Android 기기를 USB로 Mac에 연결합니다.

  3) Finder에서 run.command 를 더블클릭합니다.
     잠시 후 브라우저가 자동으로 열립니다.
     열리지 않으면 직접 접속하세요:  http://127.0.0.1:5003

  4) 브라우저에서 아래 항목을 설정합니다:
     - Device              : 연결된 기기를 선택합니다
     - S-Patch Serial No.  : S-Patch 시리얼 번호를 입력합니다 (필수)
     - Test Name           : 테스트 이름을 입력합니다
     - Test Duration       : 테스트 총 시간을 설정합니다
     - Injection Interval  : 증상 주입 간격을 설정합니다
     - Skip Regression     : 이미 검사가 진행 중인 경우 체크 (아래 참고)
     - Slack Webhook URL   : Slack 알림이 필요하면 입력합니다 (선택)

  5) [Start Test] 버튼을 클릭합니다.

  ─ 일반 모드 (Skip Regression 미체크):
       1. Regression 테스트 (main → diary → menu-study 순서)
       2. 증상 주입 스케줄 시작

  ─ Skip Regression 모드 (이미 검사 중인 경우):
       Regression을 건너뛰고 바로 증상 주입만 시작합니다.

  6) 테스트가 끝날 때까지 터미널 창을 닫지 마세요.


------------------------------------------------------------
  3. 테스트 중지
------------------------------------------------------------

  STOP.command 를 더블클릭하거나
  run.command 창에서 Ctrl+C 를 누르세요.


------------------------------------------------------------
  4. 자주 발생하는 문제
------------------------------------------------------------

  기기가 인식되지 않는 경우:
    - USB 케이블을 뽑았다가 다시 꽂아보세요.
    - USB 디버깅이 켜져 있는지 확인하세요.
    - 스마트폰 화면에 "허용" 팝업이 있으면 탭하세요.

  .command 파일이 실행되지 않는 경우:
    - 파일을 오른쪽 클릭 → [열기] 를 선택하세요.
    - 또는 터미널에서:
        chmod +x install.command run.command STOP.command

  macOS 보안으로 차단된 경우:
    - 터미널에서:
        xattr -d com.apple.quarantine install.command run.command STOP.command

  브라우저가 열리지 않는 경우:
    - http://127.0.0.1:5003 을 직접 입력하세요.

  설치 중 비밀번호 요청:
    - Homebrew 설치에 관리자 비밀번호가 필요합니다.
    - Mac 로그인 비밀번호를 입력하세요 (입력해도 화면에 표시되지 않습니다).

  절전 방지가 작동하지 않는 경우:
    - Mac을 AC 전원(충전기)에 연결하세요.


------------------------------------------------------------
  5. 전체 TC 목록 (검사 진행 중 상태 필요)
------------------------------------------------------------

  [Main Screen — 5개]
  TC-MAIN-001   My Study Progress / Device Status 탭 표시
  TC-MAIN-002   Network / Bluetooth / Battery 카드 표시
  TC-MAIN-003   Log Symptoms 버튼 표시 및 활성화
  TC-MAIN-004   Real-time ECG 탭 전환 → Live ECG Signal 표시
  TC-MAIN-005   뒤로가기 → 메인 화면 유지

  [Log Symptoms / Diary — 5개]
  TC-DIARY-001   Log Symptoms 탭 → 시트 열림 및 Symptom 섹션 표시
  TC-DIARY-002   증상 목록 전체 표시
  TC-DIARY-003   랜덤 증상 선택 → Save 제출 → 메인 화면 복귀
  TC-DIARY-004   X 버튼 탭 → 시트 닫힘, 메인 화면 복귀
  TC-DIARY-005   증상 미선택 → Save 버튼 활성화/비활성화 상태 확인

  [Menu Study — 5개]
  TC-MENU-STUDY-001   검사 중 메뉴 → Device Information 표시
  TC-MENU-STUDY-002   검사 중 메뉴 → Study Information 항목 표시
  TC-MENU-STUDY-003   검사 중 메뉴 섹션 항목 정상 표시
  TC-MENU-STUDY-004   Study Information 탭 → 스터디 정보 화면 진입
  TC-MENU-STUDY-005   Device Information 탭 → 기기 정보 화면 진입

============================================================
