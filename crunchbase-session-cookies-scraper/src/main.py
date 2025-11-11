thonimport argparse
import json
import logging
from pathlib import Path
from typing import Any, Dict, List

from utils.cookie_validator import CookieValidator
from utils.session_manager import (
    AuthenticationError,
    SessionManager,
    SessionResult,
)

BASE_DIR = Path(__file__).resolve().parents[1]
DEFAULT_INPUT_PATH = BASE_DIR / "data" / "inputs.sample.json"
DEFAULT_OUTPUT_PATH = BASE_DIR / "data" / "output_example.json"
SESSION_CACHE_PATH = BASE_DIR / "data" / "session_cache.json"

def load_json(path: Path) -> Any:
    if not path.exists():
        raise FileNotFoundError(f"JSON file not found: {path}")
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)

def save_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=4)

def load_session_cache() -> Dict[str, Dict[str, Dict[str, str]]]:
    if not SESSION_CACHE_PATH.exists():
        return {}
    try:
        with SESSION_CACHE_PATH.open("r", encoding="utf-8") as f:
            raw = json.load(f)
        if not isinstance(raw, dict):
            logging.warning("Session cache file is malformed; starting with empty cache.")
            return {}
        return raw
    except Exception as exc:  # noqa: BLE001
        logging.warning("Failed to read session cache (%s); starting with empty cache.", exc)
        return {}

def save_session_cache(cache: Dict[str, Dict[str, Dict[str, str]]]) -> None:
    try:
        save_json(SESSION_CACHE_PATH, cache)
    except Exception as exc:  # noqa: BLE001
        logging.warning("Failed to save session cache: %s", exc)

def process_credentials(
    credentials: List[Dict[str, str]],
    login_url: str,
    protected_url: str,
    timeout: int,
) -> List[SessionResult]:
    session_manager = SessionManager(
        base_login_url=login_url,
        protected_url=protected_url,
        timeout=timeout,
    )
    validator = CookieValidator(
        protected_url=protected_url,
        timeout=timeout,
    )

    cache = load_session_cache()
    results: List[SessionResult] = []

    for cred in credentials:
        email = cred.get("email")
        password = cred.get("password")

        if not email or not password:
            logging.error("Missing email or password in credentials: %s", cred)
            raise SystemExit(1)

        logging.info("Processing credentials for email: %s", email)

        cached = cache.get(email)
        if cached:
            logging.info("Found cached session for %s; validating...", email)
            headers = cached.get("headers") or {}
            cookies = cached.get("cookies") or {}

            if validator.is_valid(cookies=cookies, headers=headers):
                logging.info("Cached session for %s is valid; reusing.", email)
                results.append(SessionResult(headers=headers, cookies=cookies))
                continue
            else:
                logging.info("Cached session for %s is invalid; renewing.", email)

        try:
            session_result = session_manager.login(email=email, password=password)
        except AuthenticationError as exc:
            logging.error("Authentication failed for %s: %s", email, exc)
            raise SystemExit(1) from exc
        except Exception as exc:  # noqa: BLE001
            logging.error("Unexpected error during login for %s: %s", email, exc)
            raise SystemExit(1) from exc

        cache[email] = {
            "headers": session_result.headers,
            "cookies": session_result.cookies,
        }
        results.append(session_result)

    save_session_cache(cache)
    return results

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Crunchbase Session Cookies Scraper\n\n"
            "This script reads Crunchbase credentials from a JSON file, validates any "
            "cached sessions, renews them when necessary, and outputs standardized "
            "session headers + cookies."
        )
    )
    parser.add_argument(
        "--credentials-file",
        type=str,
        default=str(DEFAULT_INPUT_PATH),
        help=(
            "Path to the input JSON file containing a list of credential objects, "
            'each with "email" and "password" fields. '
            f"Default: {DEFAULT_INPUT_PATH}"
        ),
    )
    parser.add_argument(
        "--output-file",
        type=str,
        default=str(DEFAULT_OUTPUT_PATH),
        help=f"Path where the resulting session objects will be written. Default: {DEFAULT_OUTPUT_PATH}",
    )
    parser.add_argument(
        "--login-url",
        type=str,
        default="https://www.crunchbase.com/login",
        help="Crunchbase login endpoint URL.",
    )
    parser.add_argument(
        "--protected-url",
        type=str,
        default="https://www.crunchbase.com/account",
        help="A Crunchbase endpoint that requires authentication; used for cookie validation.",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=15,
        help="Network timeout in seconds for HTTP requests. Default: 15",
    )
    parser.add_argument(
        "--log-level",
        type=str,
        default="INFO",
        help="Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL). Default: INFO",
    )
    return parser.parse_args()

def configure_logging(level: str) -> None:
    numeric_level = getattr(logging, level.upper(), logging.INFO)
    logging.basicConfig(
        level=numeric_level,
        format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    )

def main() -> None:
    args = parse_args()
    configure_logging(args.log_level)

    credentials_path = Path(args.credentials_file)
    output_path = Path(args.output_file)

    logging.info("Loading credentials from %s", credentials_path)
    raw_creds = load_json(credentials_path)

    if not isinstance(raw_creds, list):
        logging.error("Credentials file must contain a JSON list of objects.")
        raise SystemExit(1)

    credentials: List[Dict[str, str]] = []
    for idx, item in enumerate(raw_creds):
        if not isinstance(item, dict):
            logging.error("Invalid credential entry at index %d; expected object.", idx)
            raise SystemExit(1)
        credentials.append(item)

    if not credentials:
        logging.error("No credentials found in %s", credentials_path)
        raise SystemExit(1)

    logging.info("Processing %d credential set(s)...", len(credentials))
    session_results = process_credentials(
        credentials=credentials,
        login_url=args.login_url,
        protected_url=args.protected_url,
        timeout=args.timeout,
    )

    serializable = [
        {
            "headers": result.headers,
            "cookies": result.cookies,
        }
        for result in session_results
    ]

    logging.info("Writing %d session object(s) to %s", len(serializable), output_path)
    save_json(output_path, serializable)
    logging.info("Done.")

if __name__ == "__main__":
    main()