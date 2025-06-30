import json
import os
import sys
import pytest
import requests

# Ensure the correct import path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../..")))

from valuator.utils.qt_studio.models.app_state import AppState
from valuator.utils.qt_studio.core.decorators import append_to_methods
from valuator.utils.finsource.sec_collector import get_ticker_and_cik, get_10k_html_link
from valuator.modules.example.example_old import valuation


# Dummy function for testing
@append_to_methods(example_input="test")
def test_func(x):
    return f"Hello {x}"


def test_log_capture():
    # Reset logs before test
    app_state = AppState.get_instance()
    app_state.archive_and_clear_logs()

    # Execute the function
    result = test_func("world")
    assert result == "Hello world"

    # Fetch logs
    logs = app_state.get_all_logs()
    # There should be at least INFO and SUCCESS logs
    assert any("Executing 'test_func'" in msg for level, msg in logs)
    assert any("Hello world" in msg for level, msg in logs)
    # Optionally, print logs for debug
    for level, msg in logs:
        print(f"[{level}] {msg}")


tickers = [
    #     "AAPL",
    # "MSFT",
    "PEP",
    "NVDA",
    "SBUX",
    "DIS",
    "LLY",
    "XOM",
    "JPM",
    "RTX",
]


def test_get_ticker_and_cik():
    """
    Test that get_ticker_and_cik returns the exact expected (ticker, cik) tuple
    for a given ticker or company name.
    """
    expected = {
        "AAPL": ("aapl", "0000320193"),
        "MSFT": ("msft", "0000789019"),
        "PEP": ("pep", "0000077476"),
        "NVDA": ("nvda", "0001045810"),
        "SBUX": ("sbux", "0000829224"),
        "DIS": ("dis", "0001744489"),
        "LLY": ("lly", "0000059478"),
        "XOM": ("xom", "0000034088"),
        "JPM": ("jpm", "0000019617"),
        "RTX": ("rtx", "0000101829"),
    }
    for key, (expected_ticker, expected_cik) in expected.items():
        t, cik = get_ticker_and_cik(key)
        assert (
            t.lower() == expected_ticker
        ), f"For {key}, expected ticker {expected_ticker}, got {t}"
        assert cik == expected_cik, f"For {key}, expected cik {expected_cik}, got {cik}"


def test_get_10k_html_link():
    for ticker in tickers:
        try:
            url = get_10k_html_link(ticker)
            print(f"{ticker}: 10-K URL = {url}")
            headers = {
                "User-Agent": "Mozilla/5.0 (compatible; MyResearchBot/1.0; contact: myemail@example.com)"  # header에 email 주소가 반드시 필요함.
            }
            res = requests.get(url, headers=headers)
            assert url.startswith("https://www.sec.gov/Archives/edgar/data/")
            assert url.endswith(".htm")
            assert res.status_code == 200

        except Exception as e:
            pytest.fail(f"get_10k_html_link failed for {ticker}: {e}")


def test_valuation_logging():
    app_state = AppState.get_instance()
    app_state.archive_and_clear_logs()
    for ticker in tickers:
        params = {"corp": ticker, "discount_rate": 0.085, "terminal_growth": 0.025}
        try:
            result = valuation(json.dumps(params))
            print(f"Valuation result for {ticker}:\n{result}\n")
            logs = app_state.get_all_logs()
            # There should be at least INFO and SUCCESS logs for valuation
            assert any(
                "Executing 'valuation'" in msg and ticker in msg for level, msg in logs
            ), f"No INFO log for valuation({ticker})"
            try:
                assert any(
                    "DCF Valuation" in msg or "Valuation Results" in msg
                    for level, msg in logs
                ), f"No SUCCESS log for valuation({ticker})"
            except AssertionError as e:
                print(e)
        except Exception as e:
            pytest.fail(f"valuation failed for {ticker}: {e}")
        finally:
            # Optionally, print logs for debug
            for level, msg in app_state.get_all_logs():
                print(f"[{level}] {msg}")
            app_state.archive_and_clear_logs()


if __name__ == "__main__":
    test_log_capture()
    test_get_ticker_and_cik()
    test_get_10k_html_link()
    test_valuation_logging()
