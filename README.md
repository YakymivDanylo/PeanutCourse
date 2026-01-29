# Week 1: Arbit

This project serves as the foundation for an arbitrage trading system. It includes core modules for secure wallet management, robust blockchain interaction, transaction construction, and analysis.

## Project Structure


- **`core/`**: Base logic and types.
    - `wallet.py`: Secure private key management and signing.
    - `types.py`: Strongly typed `Address` and `TokenAmount` with validation.
    - `serializer.py`: Deterministic JSON serialization (canonical) for signing.
- **`chain/`**: Blockchain interaction.
    - `client.py`: RPC client with automatic retries, exponential backoff, and provider switching.
    - `builder.py`: Fluent API for constructing and signing transactions.
    - `analyzer.py`: Tool for dissecting and decoding transaction data.
- **`scripts/`**: Utility scripts (e.g., integration tests).
- **`tests/`**: Unit tests ensuring correctness of core components.
- **`src/`**: Source code (application logic).
- **`configs/`**: Configuration files.
- **`docs/`**: Documentation.
- **`Makefile`**: Entry point for build, test, and run commands.

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
   - PRIVATE_KEY=<your_private_key>
   - ALCHEMY_RPC_URL=https://eth-sepolia.g.alchemy.com/v2/ВАШ_КЛЮЧ_ALCHEMY

Note: The .env file must never be committed to the repository.
 
## Usage

### Running the Application
To verify the system works on a real network (Sepolia Testnet), run the integration script. This script checks balances, builds a self-transfer transaction, signs it, and sends it to the network:
- make run

### Expected Output:
Wallet: 0x74be7c8667F6E23e2845E6bE8A093EbFacEa4476  
Balance: 0.069784996739676 ETH

Building transaction...  
  To: 0x74be7c8667F6E23e2845E6bE8A093EbFacEa4476  
  Value: 0.0001 ETH  
  Gas Limit: 25200  
  Max Fee: 1.12 gwei  

Signing and Sending...  
  Signer: 0x74be7c8667F6E23e2845E6bE8A093EbFacEa4476  
  Recovered: 0x74be7c8667F6E23e2845E6bE8A093EbFacEa4476  
  Signature valid: Yes  

Sending...  
  TX Hash: 8f819485faad381a730fabf54efb75742ea7ee56a58e5d302969541b7478187d  

Waiting for confirmation...  
  Block: 10104759  
  Status: SUCCESS  
  Gas Used: 21000  
  Fee: 0.000021989821035 ETH  

Integration test PASSED

### Transaction Analyzer CLI

Analyze any transaction on the Ethereum mainnet (or other chains via RPC config). This tool decodes input data, calculates fees, and summarizes transfers:  

python -m chain.analyzer <TX_HASH> --rpc (https://ethereum-sepolia.publicnode.com - для тестнових транзакцій) (https://rpc.flashbots.net - для реальних транзакцій)

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

### Key Features & Design Decisions
- Safety First: The **`WalletManager`** ensures private keys are never exposed in **`__repr__`** or logs.
- Reliability: The **`ChainClient`** implements retry logic with exponential backoff to handle RPC instability (errors like "Too Many Requests" or "Timeout").
- Precision: **`TokenAmount`** handles decimals precisely, preventing floating-point errors common in financial software.
- Usability: The **`TransactionBuilder`** uses a Fluent Interface pattern, making transaction construction readable and less error-prone.