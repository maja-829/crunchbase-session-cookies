thonimport json
import logging
from dataclasses import dataclass
from typing import Dict

import requests

logger = logging.getLogger(__name__)

class AuthenticationError(Exception):
    """Raised when Crunchbase authentication fails."""

@dataclass
class SessionResult:
    headers: Dict[str, str]
    cookies: Dict[str, str]

class SessionManager:
    """
    Handles Crunchbase login and session creation.

    This component is responsible for:
      * Performing a login with email + password.
      * Constructing appropriate headers for subsequent authenticated calls.
      * Returning a serializable representation of the headers and cookies.

    NOTE:
        The actual login behavior of Crunchbase may involve more complex
        flows (e.g., CSRF tokens, JavaScript flows, multi-factor auth).
        This implementation assumes a conventional JSON-based login endpoint
        and is intentionally written so it can be adjusted easily.
    """

    def __init__(self, base_login_url: str, protected_url: str, timeout: int = 10) -> None:
        self.base_login_url = base_login_url
        self.protected_url = protected_url
        self.timeout = timeout

    def _build_base_headers(self) -> Dict[str, str]:
        # A realistic browser-like user agent and generic headers.
        return {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "en-US,en;q=0.9",
            "Origin": "https://www.crunchbase.com",
            "Referer": "https://www.crunchbase.com/login",
        }

    def _extract_token_from_response(self, response: requests.Response) -> str:
        """
        Attempt to extract an authorization token from the login response.

        The exact structure of the response is not documented here, so we try a
        few reasonable patterns and fail gracefully with AuthenticationError.
        """
        try:
            payload = response.json()
        except json.JSONDecodeError as exc:  # noqa: BLE001
            logger.debug("Login response is not JSON: %s", exc)
            raise AuthenticationError("Login response is not JSON; cannot extract token.")

        # Common patterns: {"token": "..."} or {"access_token": "..."}
        token = payload.get("token") or payload.get("access_token")
        if not token:
            # If no token, we still might rely solely on cookies; that's fine.
            logger.info("No explicit auth token found in login response; using cookies only.")
            return ""

        return str(token)

    def login(self, email: str, password: str) -> SessionResult:
        """
        Perform login using the provided credentials and return a SessionResult.

        Parameters
        ----------
        email:
            Crunchbase account email.
        password:
            Crunchbase account password.

        Returns
        -------
        SessionResult
            Object containing headers and cookies suitable for authenticated use.

        Raises
        ------
        AuthenticationError
            If login fails for any reason (invalid credentials, unexpected response).
        """
        session = requests.Session()
        headers = self._build_base_headers()

        payload = {
            "email": email,
            "password": password,
        }

        logger.info("Attempting login for %s", email)
        try:
            response = session.post(
                self.base_login_url,
                headers=headers,
                json=payload,
                timeout=self.timeout,
            )
        except requests.RequestException as exc:
            logger.error("Network error while logging in: %s", exc)
            raise AuthenticationError("Network error while logging in.") from exc

        if response.status_code not in (200, 201):
            logger.error(
                "Login failed for %s with status %s", email, response.status_code
            )
            raise AuthenticationError(
                f"Login failed with status code {response.status_code}."
            )

        # Try to extract token if available.
        token = ""
        try:
            token = self._extract_token_from_response(response)
        except AuthenticationError as exc:
            # If no token is present but cookies exist, we can still proceed.
            logger.warning("Token extraction issue: %s", exc)

        # Merge base headers and auth header (if token exists).
        auth_headers = dict(headers)
        if token:
            auth_headers["Authorization"] = f"Bearer {token}"

        # Grab cookies after login.
        cookies_dict = session.cookies.get_dict()
        if not cookies_dict:
            logger.warning(
                "Login response did not yield any cookies; this may indicate a failed login."
            )

        # Optionally validate login by calling a protected resource.
        if not self._verify_authenticated(session=session, headers=auth_headers):
            raise AuthenticationError("Authenticated check failed after login.")

        logger.info("Login and session verification succeeded for %s", email)
        return SessionResult(headers=auth_headers, cookies=cookies_dict)

    def _verify_authenticated(
        self,
        session: requests.Session,
        headers: Dict[str, str],
    ) -> bool:
        """
        Perform a lightweight check to confirm the session is authenticated.

        Returns
        -------
        bool
            True if the check succeeded, False otherwise.
        """
        try:
            logger.debug(
                "Verifying authenticated session by requesting %s", self.protected_url
            )
            response = session.get(
                self.protected_url,
                headers=headers,
                timeout=self.timeout,
                allow_redirects=False,
            )
        except requests.RequestException as exc:
            logger.error("Network error while verifying authenticated session: %s", exc)
            return False

        if 200 <= response.status_code < 300:
            logger.debug("Authenticated verification returned status %s", response.status_code)
            return True

        logger.warning(
            "Authenticated verification failed with status %s",
            response.status_code,
        )
        return False