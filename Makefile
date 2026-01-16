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
	$(PYTHON) src/main.py

check: format lint test