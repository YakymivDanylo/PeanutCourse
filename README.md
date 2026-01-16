# Trading Bot (Lab - 1)

## Project Structure

- src/: Source code (application logic).
- tests/: Unit and negative tests.
- scripts/: Utility scripts.
- configs/: Configuration files.
- docs/: Documentation.
- Makefile: Entry point for build, test, and run commands.

## Prerequisites

- Python 3.10+
- GNU Make
- Git
 
## Installation & Setup

1. Clone the repository:
   - git clone <repository_url>
   - cd trading-bot

2. Create and activate a virtual environment:
   - python3 -m venv .venv
   - source .venv/bin/activate

3. Install dependencies:
   - make install

4. Install pre-commit hooks (required for development):
   - pre-commit install

## Configuration (Secrets Management)

1. Create a local environment file based on the template:
   - cp .env.example .env

2. Open .env and populate the variables:
   - ENV_TYPE=local
   - API_KEY=<your_private_key>

Note: The .env file must never be committed to the repository.
 
## Usage

### Running the Application
To run the bot in the configured environment:
- make run
 
### Testing
To run the test suite (pytest):
- make test

This includes:
- Unit tests for invariant checking.
- Negative tests for error handling.

### Development Standards

Code Quality

The project uses the following tools to enforce code quality:
- Formatter: Black
- Linter: Flake8

To run formatters and linters manually:
make format
make lint

### Pre-commit Hooks

Pre-commit hooks are configured to automatically check code style and formatting before every commit. 
If a hook fails, the commit is blocked until the issues are resolved.

### Final Verification

Before submitting or pushing changes, run the full check suite:
make check

This command executes formatting, linting, and testing in sequence.
