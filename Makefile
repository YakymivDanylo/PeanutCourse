PYTHON = python3
PIP = pip

install:
	$(PIP) install -r requirements.txt

format:
	black src tests

lint:
	flake8 src tests

test:
	pytest tests

run:
	$(PYTHON) scripts/integration_test.py
run_fork:
	./scripts/start_fork.sh

check: format lint test