PYTHON := $(shell [ -f .venv/bin/python ] && echo .venv/bin/python || echo python3)
CONFIG ?= config/accurkardia.yaml
OUT    ?= ~/Desktop

.PHONY: install run stop web dry-run regression \
        reg-serial reg-menu reg-signal reg-study reg-main reg-diary reg-menu-study \
        dist dist-mac dist-windows help \
        run-ios stop-ios dry-run-ios

help:
	@echo ""
	@echo "  S-Patch Accurkardia Automation"
	@echo ""
	@echo "  make install        — first time: create venv + install packages"
	@echo "  make run            — long-run test (symptom injection)"
	@echo "  make web            — web UI (port 5003)  /team → team dashboard"
	@echo "  make dry-run        — validate config only (no device)"
	@echo ""
	@echo "  Regression suites (no device needed):"
	@echo "  make reg-serial     — TC-SN: serial input screen"
	@echo "  make reg-menu       — TC-MENU: settings menu"
	@echo ""
	@echo "  Regression suites (BLE connected, no study registered):"
	@echo "  make reg-signal     — TC-SIG: Check Incoming Signal"
	@echo "  make reg-study      — TC-STUDY: Review Study Setting"
	@echo ""
	@echo "  Regression suites (study active):"
	@echo "  make reg-main       — TC-MAIN: measurement main screen"
	@echo "  make reg-diary      — TC-DIARY: Log Symptoms"
	@echo "  make reg-menu-study — TC-MENU-STUDY: menu during study"
	@echo ""
	@echo "  make regression     — run all suites"
	@echo ""
	@echo "  Distribution ZIPs:"
	@echo "  make dist           — Mac + Windows → ~/Desktop"
	@echo "  make dist-mac       — Mac ZIP only"
	@echo "  make dist-windows   — Windows ZIP only"
	@echo "  make dist OUT=/tmp  — custom output path"
	@echo ""

install:
	python3 -m venv .venv
	$(PYTHON) -m pip install --upgrade pip -q
	$(PYTHON) -m pip install -r requirements.txt -q
	@echo ""
	@echo "  Done. Run 'make run' or 'make web' to start."
	@echo ""

run:
	PYTHONPATH=. $(PYTHON) src/main.py --config $(CONFIG)

stop:
	@pkill -f "src/main.py" 2>/dev/null && echo "Stopped." || echo "Not running."

web:
	PYTHONPATH=. $(PYTHON) web/app.py

dry-run:
	PYTHONPATH=. $(PYTHON) src/main.py --config $(CONFIG) --dry-run

regression:
	PYTHONPATH=. $(PYTHON) src/run_regression.py --config $(CONFIG) --suite all

reg-serial:
	PYTHONPATH=. $(PYTHON) src/run_regression.py --config $(CONFIG) --suite serial

reg-menu:
	PYTHONPATH=. $(PYTHON) src/run_regression.py --config $(CONFIG) --suite menu

reg-signal:
	PYTHONPATH=. $(PYTHON) src/run_regression.py --config $(CONFIG) --suite signal

reg-study:
	PYTHONPATH=. $(PYTHON) src/run_regression.py --config $(CONFIG) --suite study

reg-main:
	PYTHONPATH=. $(PYTHON) src/run_regression.py --config $(CONFIG) --suite main

reg-diary:
	PYTHONPATH=. $(PYTHON) src/run_regression.py --config $(CONFIG) --suite diary

reg-menu-study:
	PYTHONPATH=. $(PYTHON) src/run_regression.py --config $(CONFIG) --suite menu-study

# ── iOS targets (new — Android targets above are unchanged) ─────────────────
IOS_CONFIG ?= config/accurkardia_ios.yaml

run-ios:
	PYTHONPATH=. $(PYTHON) src/main_ios.py --config $(IOS_CONFIG)

stop-ios:
	@pkill -f "src/main_ios.py" 2>/dev/null && echo "Stopped." || echo "Not running."

dry-run-ios:
	PYTHONPATH=. $(PYTHON) src/main_ios.py --config $(IOS_CONFIG) --dry-run

# ── Distribution ──────────────────────────────────────────────────────────────
dist:
	$(PYTHON) scripts/build_dist.py --out $(OUT) --platform both

dist-mac:
	$(PYTHON) scripts/build_dist.py --out $(OUT) --platform mac

dist-windows:
	$(PYTHON) scripts/build_dist.py --out $(OUT) --platform windows
