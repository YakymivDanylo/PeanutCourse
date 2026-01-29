#!/bin/bash
# scripts/start_fork.sh

if [ -f .env ]; then
  set -a
  source <(sed 's/\r$//' .env | grep -v '^#')
  set +a
fi

if [ -n "$ALCHEMY_RPC_URL" ]; then
  TARGET_RPC=$ALCHEMY_RPC_URL
  echo "Using Alchemy RPC for forking."
else
  echo "Error: Neither ALCHEMY_RPC_URL nor SEPOLIA_RPC_URL is set in .env"
  exit 1
fi

echo "Starting Anvil Fork..."
echo "Target: Sepolia"

anvil \
    --fork-url "$TARGET_RPC" \
    --port 8545 \
    --accounts 10 \
    --balance 10000