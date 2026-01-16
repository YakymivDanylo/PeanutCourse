import os
from dotenv import load_dotenv

load_dotenv()


def get_status() -> dict:
    """Getting bot`s status"""
    return {"status": "running", "env": os.getenv("ENV_TYPE", "unknown")}


def safe_divide(a: float, b: float) -> float:
    """Safe division for a negative tests"""
    if b == 0:
        raise ValueError("Cannot divide by zero")
    return a / b


if __name__ == "__main__":
    print(f"Bot started. Config: {get_status()}")
