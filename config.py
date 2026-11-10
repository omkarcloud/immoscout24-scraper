"""Configuration for the Immoscout24 Scraper. Everything can be set with an
environment variable; the defaults work out of the box.

    PORT               port the API listens on (default 8000)
    IMMOSCOUT24_PROXY  proxy URL for every request, e.g. http://user:pass@host:port
                       (default: none — direct). ImmoScout24's app API (Germany)
                       and immobilienscout24.at (Austria) answered every request
                       from a plain cloud server IP in our tests, so you very
                       likely don't need this. Set it only if you start seeing
                       failures at high volume: every retry after a failure then
                       leaves through a fresh connection.

Everything else below is a plain constant with a working default — edit it
here if you need to.
"""
import os

PORT = int(os.environ.get("PORT", "8000"))

# Retry policy for transport errors and blocks (every request).
MAX_RETRIES = 3
RETRY_BACKOFF = 2          # seconds, multiplied by the attempt number

IMMOSCOUT24_PROXY = os.environ.get("IMMOSCOUT24_PROXY") or None


def immoscout24_proxy():
    """The proxy for one curl session (None = direct)."""
    return os.environ.get("IMMOSCOUT24_PROXY") or None
