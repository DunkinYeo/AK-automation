PYTHON := $(shell [ -f .venv/bin/python ] && echo .venv/bin/python || echo python3)
CONFIG ?= config/accurkardia.yaml
OUT    ?= ~/Desktop

.PHONY: install run stop web restart-web dry-run regression \
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
	@echo "  make restart-web    — restart the web server, preserving a live run"
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

# Kills only the process actually listening on :5003 (not a blanket
# pkill -f "web/app.py" -- this repo's dev machine has been seen running
# more than one web/app.py at once on different ports, and a blanket
# kill would take down an unrelated one). Uses SIGKILL deliberately:
# SIGTERM triggers _register_exit_hooks()'s _kill_proc(), which also
# kills whatever test run this server is tracking -- SIGKILL bypasses
# that entirely, and the fresh process re-attaches to the still-alive
# run via runtime/web_run_state.json (see _load_persisted_run() in
# web/app.py). This is the exact restart sequence used by hand
# throughout 2026-08-12's session; codified here afterward.
restart-web:
	@PID=$$(lsof -tiTCP:5003 -sTCP:LISTEN 2>/dev/null); \
	if [ -n "$$PID" ]; then \
		echo "Killing web server (pid $$PID)..."; \
		kill -9 $$PID; \
	else \
		echo "No web server currently listening on :5003."; \
	fi; \
	for i in 1 2 3 4 5 6 7 8 9 10; do \
		lsof -iTCP:5003 -sTCP:LISTEN -P -n >/dev/null 2>&1 || break; \
		sleep 1; \
	done; \
	PYTHONPATH=. nohup $(PYTHON) web/app.py > /tmp/ak_web_restart.log 2>&1 & \
	sleep 3; \
	echo "--- /tmp/ak_web_restart.log ---"; \
	tail -8 /tmp/ak_web_restart.log

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
