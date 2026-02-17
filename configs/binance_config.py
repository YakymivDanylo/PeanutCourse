# configs/binance_config.py
import os
import sys
from dotenv import load_dotenv


sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from config import Config

    IS_PROD = Config.PRODUCTION
except ImportError:
    IS_PROD = os.getenv("PRODUCTION", "false").lower() == "true"

load_dotenv()

if IS_PROD:
    BINANCE_CONFIG = {
        "apiKey": os.getenv("BINANCE_API_KEY"),
        "secret": os.getenv("BINANCE_SECRET"),
        "sandbox": False,
        "options": {
            "defaultType": "spot",
        },
        "enableRateLimit": True,
        "urls": {
            "api": {
                "public": "https://api.binance.com/api/v3",
                "private": "https://api.binance.com/api/v3",
            }
        },
    }
else:
    BINANCE_CONFIG = {
        "apiKey": os.getenv("BINANCE_TESTNET_API_KEY"),
        "secret": os.getenv("BINANCE_TESTNET_SECRET"),
        "sandbox": True,
        "options": {
            "defaultType": "spot",
        },
        "enableRateLimit": True,
    }
