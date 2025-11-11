thonimport logging
from typing import Dict, Optional

import requests

logger = logging.getLogger(__name__)

class CookieValidator:
    """
    Validates whether a given set of cookies and optional headers still represent
    a valid authenticated Crunchbase session.

    The validator performs a GET request to a protected endpoint and considers the
    session valid if it receives a 200-level response.
    """

    def __init__(self, protected_url: str, timeout: int = 10) -> None:
        self.protected_url = protected_url
        self.timeout = timeout

    def is_valid(
        self,
        cookies: Dict[str, str],
        headers: Optional[Dict[str, str]] = None,
    ) -> bool:
        """
        Return True if the cookies represent a valid authenticated session.

        Parameters
        ----------
        cookies:
            A mapping of cookie name to value.
        headers:
            Optional HTTP headers to send along with the request.

        Returns
        -------
        bool
            True if the cookies are considered valid, False otherwise.
        """
        if not cookies:
            logger.debug("CookieValidator: No cookies provided; invalid by definition.")
            return False

        session = requests.Session()
        session.cookies.update(cookies)

        try:
            logger.debug(
                "CookieValidator: Sending validation request to %s", self.protected_url
            )
            response = session.get(
                self.protected_url,
                headers=headers or {},
                timeout=self.timeout,
                allow_redirects=False,
            )
        except requests.RequestException as exc:
            logger.warning("Cookie validation failed due to network error: %s", exc)
            return False

        # Many authenticated pages redirect on missing or invalid auth (302/401/403).
        # We treat 200..299 as valid.
        if 200 <= response.status_code < 300:
            logger.debug(
                "CookieValidator: Validation succeeded with status code %s",
                response.status_code,
            )
            return True

        logger.info(
            "CookieValidator: Validation failed with status code %s",
            response.status_code,
        )
        return False