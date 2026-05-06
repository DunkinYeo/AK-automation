"""
공통 헬퍼 함수
"""
import time
import logging
from selenium.webdriver.common.by import By

log = logging.getLogger(__name__)

# Coordinates for 1080x2400 (Pixel 7) — update if device changes
# AK app uses a gear icon (top-right) instead of hamburger menu (top-left)
MENU_BTN_X = 985  # center of gear icon bounds [954,199][1017,262]
MENU_BTN_Y = 230
STUDY_POPUP_X_BTN = (252, 358)   # X dismiss button on No Study Information popup
DIARY_X_BTN = (1004, 258)        # X close button on Add Diary sheet


def reset_to_step1(drv, hard: bool = True):
    """
    Step 1(Connect Your S-Patch) 화면으로 이동.
    hard=True  : 앱 강제 종료 후 재시작 (BLE 끊김 주의)
    hard=False : 뒤로가기 반복으로 Step 1 복귀 (BLE 유지)
    """
    pkg = drv.cfg.get("app_package")

    if hard:
        log.info("[setup] 앱 재시작 → Step 1")
        try:
            drv.drv.terminate_app(pkg)
        except Exception:
            pass
        time.sleep(1)
        try:
            drv.drv.activate_app(pkg)
        except Exception:
            act = drv.cfg.get("app_activity")
            if act:
                drv.drv.start_activity(pkg, act)
        time.sleep(2)
    else:
        log.info("[setup] 뒤로가기 → Step 1 (BLE 유지)")
        for _ in range(5):
            if drv.is_visible_text("Connect Your S-Patch", timeout=2):
                break
            drv.drv.press_keycode(4)
            time.sleep(0.8)
        time.sleep(0.5)


def go_to_step2(drv, wait_ble: int = 45):
    """Step 1에서 시리얼 입력 후 Step 2 진입. wait_ble: BLE 연결 대기 시간(초)

    주의: 웹에 검사가 등록된 상태면 Step 2를 빠르게 지나쳐
    Step 3(Review Study Setting) 또는 메인 화면으로 자동 진입할 수 있음.
    TC-SIG/STUDY 테스트는 검사 미등록 상태에서 실행 권장.
    """
    if not drv.is_visible_text("Connect Your S-Patch", timeout=5):
        raise Exception("Step 1 화면이 아님 — reset_to_step1() 먼저 호출 필요")

    serial = drv.cfg.get("test_serial_number", "680150")
    el = drv.drv.find_element(By.CLASS_NAME, "android.widget.EditText")
    el.clear()
    el.send_keys(serial)
    time.sleep(0.5)
    drv.tap_text("Connect", timeout=5, contains=False)

    # BLE 연결 + Step 2 로딩 대기
    deadline = time.monotonic() + wait_ble
    while time.monotonic() < deadline:
        if drv.is_visible_text("Check Incoming Signal", timeout=2):
            return
        # 웹에 검사 등록된 경우 Step 2를 빠르게 지나침 → 경고 후 실패
        if drv.is_visible_text("Review Study Setting", timeout=1):
            raise Exception("Step 2 스킵됨 — 웹에 검사가 등록된 상태. 검사 미등록 후 재시도 필요")
        if drv.is_visible_text("Study Information", timeout=1):
            raise Exception("Step 2 스킵됨 — 이미 검사 진행 중. 검사 종료 후 재시도 필요")
        time.sleep(1)

    raise Exception(f"Step 2 진입 실패 ({wait_ble}s 대기 후 'Check Incoming Signal' 미표시)")


def go_to_main(drv, wait_ble: int = 25):
    """Step 1 → Connect → Step 2 → Continue → Step 3 → Continue → 측정 메인 화면"""
    go_to_step2(drv, wait_ble=wait_ble)
    drv.tap_text("Continue", timeout=5, contains=False)

    # Step 3 (Review Study Setting) 대기
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        if drv.is_visible_text("Review Study Setting", timeout=2):
            break
        time.sleep(1)

    drv.tap_text("Continue", timeout=5, contains=False)

    # 측정 메인 화면 대기
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        if drv.is_visible_text("Study Information", timeout=2):
            return
        time.sleep(1)

    raise Exception("측정 메인 화면 진입 실패 (15s 대기 후 'Study Information' 미표시)")


def open_menu(drv, wait: float = 2.0):
    for attempt in range(3):
        drv.drv.tap([(MENU_BTN_X, MENU_BTN_Y)])
        time.sleep(wait)
        if drv.is_visible_text("Setting", timeout=2):
            return
        log.warning("[open_menu] 메뉴 미열림, 재시도 %d/3", attempt + 1)
        time.sleep(0.5)
    raise Exception("open_menu: 3회 시도 후 메뉴 열기 실패")


def close_menu(drv):
    drv.drv.press_keycode(4)
    time.sleep(0.5)
