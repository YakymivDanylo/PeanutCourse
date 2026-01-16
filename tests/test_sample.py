import pytest
from src.main import get_status, safe_divide


def test_status_structure():
    result = get_status()
    assert "status" in result
    assert result["status"] == "running"


def test_divide_zero():
    with pytest.raises(ValueError, match="Cannot divide by zero"):
        safe_divide(10, 0)
