"""ImmoScout24 transport: plain curl_cffi with browser-impersonated TLS. No
browser, no cookies, no tokens. Egress: the pod's own IP (config
immoscout24_proxy(), knob IMMOSCOUT24_EXIT) — every surface below answered
200 to the pod's Google Cloud address, to 2/2 datacenter ports and to 2/2
DE / AT residential ports (pod probe 2026-11-07, table in config.py). A
retryable failure drops the thread's session, so the retry rides a fresh
exit whenever the knob names one.

Germany — the ImmoScout iOS app's own JSON API (api.mobile.immobilienscout24.de;
www.immobilienscout24.de is an AWS WAF challenge to every curl identity):

  * SEARCH   POST /search/list?<params>  body {"supportedResultListType":[],"userData":{}}
             -> {totalResults, numberOfPages, resultListItems[]}; up to 100
             rows per page, a page past the end is an empty 200.
  * TOTAL    GET  /search/total?<params> -> {totalResults, comingSoonTotalResults}
  * GEO      GET  /geo/autocomplete?i=<text> -> {results[{id, type, lat, lon, …}]}
  * EXPOSE   GET  /expose/<id> -> the app's section list (photos, costs,
             attributes, texts, agent + phone, price bar); unknown id = 404
             ERROR_RESOURCE_NOT_FOUND
  * PROJECT  GET  /project/<id> -> a new-build project; unpublished = 410
  A bad parameter answers 412 ERROR_COMMON_URL_PARAMETER_* (never retried).
  The app sends a fixed German header set (its own User-Agent, Accept-
  Language de-DE); that identity is what the host expects, so it is sent as
  is (marker `# locale: app identity`), the way shazam/fetch.py does.

Austria — www.immobilienscout24.at (server-rendered React + Apollo):

  * GRAPHQL  POST /portal/graphql — named operations read from the site's
             own bundle (vendor--portal.*.js, 2026-11-07): getDataByURL
             (a list page's 25 hits + totals for a /regional/… path),
             getURLByParams / getTotalHitsByParams (SearchParamsInput ->
             canonical path / count) and tokenize (the site's free-text
             search parser: place -> region id / postcode). Introspection is
             off; a wrong field is a 400 GRAPHQL_VALIDATION_FAILED.
  * EXPOSE   GET /expose/<24-hex id> -> HTML whose window.__APOLLO_STATE__
             carries the full Expose record; a gone listing answers 410.

Failure taxonomy (scraper_errors, mapped to HTTP by route_glue):
  Immoscout24UpstreamError  transport failure / 5xx            — retryable
  Immoscout24Blocked        401 / 403 / 429 / challenge page   — retryable
  Immoscout24BadRequest     upstream 400 / 412 (bad params)    — never retried
  Immoscout24NotFound       404 / 410 / unknown id             — never retried
"""
import json
import os
import re
import sys
import threading
import time
from urllib.parse import urlencode

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
import egress
from scraper_errors import BadRequest, Blocked, NotFound, UpstreamError
from immoscout24.refs import DE_API, SITES

IMPERSONATE = "chrome"
JSON_TIMEOUT = 25
PAGE_TIMEOUT = 40      # .at list / expose pages are 130-400 KB

AT_SITE = SITES["at"]

# The iOS app's identity, sent as is on the mobile host (see the docstring).
DE_HEADERS = {
    "user-agent": "ImmoScout_27.6_26.3_._",
    "accept": "application/json",
    "content-type": "application/json",
    "accept-language": "de-DE,de;q=0.9",   # locale: app identity (the iOS app's fixed German header, not a browser's)
}
DE_SEARCH_BODY = '{"supportedResultListType":[],"userData":{}}'

AT_GRAPHQL_HEADERS = {
    "accept": "application/json",
    "content-type": "application/json",
    "origin": AT_SITE,
    "referer": AT_SITE + "/",
}
AT_PAGE_HEADERS = {
    "accept": ("text/html,application/xhtml+xml,application/xml;q=0.9,"
               "image/avif,image/webp,*/*;q=0.8"),
    "upgrade-insecure-requests": "1",
}

_CHALLENGE_MARKERS = ("ich bin kein roboter", "awswaf", "challenge.js", "datadome", "captcha-delivery",
                      "just a moment", "cf-chl")


class Immoscout24UpstreamError(UpstreamError):
    """Transport failure or 5xx — retryable."""


class Immoscout24Blocked(Immoscout24UpstreamError, Blocked):
    """401 / 403 / 429 or a challenge page where JSON / HTML was expected — retryable."""


class Immoscout24BadRequest(BadRequest):
    """Upstream rejected the parameters (400 / 412) — never retried."""


class Immoscout24NotFound(NotFound):
    """Expose / project / place does not exist — never retried."""


# ---- sessions ------------------------------------------------------------------------
# One session per cheroot worker thread (a curl handle must not be shared
# across threads), keep-alive, dropped on every retryable failure.

_local = threading.local()


def _session():
    sess = getattr(_local, "session", None)
    if sess is None:
        from curl_cffi import requests as curl_requests
        sess = curl_requests.Session(impersonate=IMPERSONATE)
        proxy = config.immoscout24_proxy()
        if proxy:
            sess.proxies = {"http": proxy, "https": proxy}
        # the .at pages announce the exit's language; the German app identity
        # overrides this per call with its own fixed header
        sess.headers["accept-language"] = egress.accept_language(proxy)
        _local.session = sess
    return sess


def _drop_session():
    sess = getattr(_local, "session", None)
    _local.session = None
    if sess is not None:
        try:
            sess.close()
        except Exception:
            pass


def _retrying(fn):
    """Run fn() under the shared retry policy (Immoscout24UpstreamError only;
    NotFound / BadRequest surface immediately)."""
    last = None
    for attempt in range(1, config.MAX_RETRIES + 1):
        try:
            return fn()
        except Immoscout24UpstreamError as e:
            last = e
            _drop_session()
            if attempt < config.MAX_RETRIES:
                time.sleep(config.RETRY_BACKOFF * attempt)
    raise last


def _looks_challenged(text):
    head = (text or "")[:4000].lower()
    return any(marker in head for marker in _CHALLENGE_MARKERS)


def _request(method, url, headers, label, timeout, data=None):
    try:
        resp = _session().request(method, url, headers=headers, data=data, timeout=timeout)
    except Exception as e:
        raise Immoscout24UpstreamError(f"request failed for {label}: {type(e).__name__}: {e}")
    if resp.status_code in (401, 403, 429):
        raise Immoscout24Blocked(f"HTTP {resp.status_code} for {label}")
    if resp.status_code >= 500:
        raise Immoscout24UpstreamError(f"HTTP {resp.status_code} for {label}")
    return resp


# ---- Germany: the mobile API --------------------------------------------------------

_DE_MESSAGE_RE = re.compile(r'"message"\s*:\s*"([^"]{1,300})"')


def _de_error_message(text):
    """The human message out of the API's error envelope (the outer "error"
    string wraps the inner common.messages JSON, escaped)."""
    matches = _DE_MESSAGE_RE.findall((text or "").replace('\\"', '"'))
    return matches[-1] if matches else (text or "")[:200]


def _de_call(method, path, label, data=None):
    url = DE_API + path

    def once():
        resp = _request(method, url, DE_HEADERS, label, JSON_TIMEOUT, data=data)
        if resp.status_code in (404, 410):
            raise Immoscout24NotFound(f"{label} not found")
        if resp.status_code in (400, 412):
            raise Immoscout24BadRequest(_de_error_message(resp.text))
        if resp.status_code != 200:
            raise Immoscout24UpstreamError(f"HTTP {resp.status_code} for {label}")
        try:
            return resp.json()
        except Exception:
            if _looks_challenged(resp.text):
                raise Immoscout24Blocked(f"challenge page instead of JSON for {label}")
            raise Immoscout24UpstreamError(f"non-JSON response for {label}: {resp.text[:120]!r}")
    return _retrying(once)


def de_search(params):
    """POST /search/list -> the raw result page. `params` are the API's own
    query tokens (realestatetype, searchType, geocodes / geocoordinates,
    pagenumber, pagesize, filters)."""
    return _de_call("POST", "/search/list?" + urlencode(params), "search", data=DE_SEARCH_BODY)


def de_total(params):
    """GET /search/total -> {totalResults, comingSoonTotalResults}."""
    return _de_call("GET", "/search/total?" + urlencode(params), "search total")


def de_autocomplete(text):
    """GET /geo/autocomplete -> {results: [...]} (empty list for no match)."""
    return _de_call("GET", "/geo/autocomplete?" + urlencode({"i": text}), f"location lookup {text!r}")


def de_expose(listing_id):
    """GET /expose/<id> -> the app's section list for one listing."""
    return _de_call("GET", f"/expose/{listing_id}", f"listing {listing_id}")


def de_project(project_id):
    """GET /project/<id> -> a new-build project record."""
    return _de_call("GET", f"/project/{project_id}", f"project {project_id}")


# ---- Austria: GraphQL + expose pages ----------------------------------------------------

_AT_PICTURE = "primaryPictureImageProps(aspectRatio: 1.33) { src }"
_AT_THUMBS = "thumbnailPicturesImageProps(aspectRatio: 1.33, numberOfPictures: 5) { src }"
# the site's own HitsFragment (vendor--portal bundle, 2026-11-07), picture
# props with a fixed aspect ratio instead of the page's template variables
AT_HIT_FIELDS = f"""
  displayType exposeId links {{ targetURL absoluteURL }} mainKeyFacts {{ value label }}
  appearanceSettings {{ hasChildren hasThumbnailPictures }}
  accountCwid addressString
  typedBadges {{ ... on BadgeRegular {{ type shownOn details {{ value }} }}
                ... on BadgeTransit {{ type shownOn details {{ lines stop }} }} }}
  hasRealtorLogo hasBrandBar isAddressCompleteAndVisible isEditorialProperty isPrivate isSocialHousing
  primaryPrice primaryArea numberOfRooms primaryPictureCaption showAddress headline
  location {{ ... on CircleLocation {{ type lat lon radius }} ... on PointLocation {{ type lat lon }}
              ... on ShapeLocation {{ type shapeId }} }}
  meta dateCreated
  primaryPriceKeyFact {{ value label }} pricePerSqmKeyFact {{ value label }}
  priceReductionKeyFact {{ original percent }}
  realtorLogoImageProps {{ src }}
  realtorContact {{ company name contactImageProps {{ src }} }}
  ... on RegularListing {{ editorialPropertyUrl geoHierarchy {_AT_PICTURE} }}
  ... on DeveloperLightListing {{ {_AT_PICTURE} }}
  ... on TopListing {{ {_AT_PICTURE} }}
  ... on SmartPremiumListing {{ geoHierarchy {_AT_PICTURE} {_AT_THUMBS} }}
  ... on DeveloperPremiumListing {{ {_AT_PICTURE} {_AT_THUMBS} }}
  ... on DeveloperTopListing {{ {_AT_PICTURE} {_AT_THUMBS} }}
"""

AT_GET_DATA_QUERY = """query($p: ResultURLInput!) { getDataByURL(params: $p) {
  exactMatch URL
  spots { id type label value }
  params { region zipCode estateType estateDetailType transferType useType primaryPriceFrom primaryPriceTo
           numberOfRoomsFrom numberOfRoomsTo primaryAreaFrom primaryAreaTo keywords sort }
  results { totalHits pagination { totalPages pageIndex currentURL nextURL previousURL }
            SEOMetaData { canonicalURL headline title }
            hits { %s } }
  breadcrumbs { label pathname }
} }""" % AT_HIT_FIELDS

AT_URL_AND_TOTAL_QUERY = """query($p: SearchParamsInput!) {
  getURLByParams(params: $p) { URL }
  getTotalHitsByParams(params: $p) { totalHits }
}"""

AT_TOKENIZE_QUERY = """query($query: String!, $cursor: Int!) { tokenize(query: $query, cursor: $cursor) {
  entities { fieldName focused meta { id label type } status value }
  leftoverTokens { text }
  parsedParams { countryCode estateType estateDetailType transferType useType region zipCode keywords
                 numberOfRoomsFrom numberOfRoomsTo primaryPriceFrom primaryPriceTo primaryAreaFrom
                 primaryAreaTo outdoorSpaces conditionAge sort }
  suggestions { key label matchedBy source type text sources { fieldName value } }
} }"""

_AT_BAD_INPUT_CODES = ("GRAPHQL_VALIDATION_FAILED", "BAD_USER_INPUT", "GRAPHQL_PARSE_FAILED")


def at_graphql(query, variables, label):
    """POST /portal/graphql -> the `data` object. Schema / input errors are
    BadRequest (never retried), anything else upstream."""
    body = json.dumps({"query": query, "variables": variables})

    def once():
        resp = _request("POST", AT_SITE + "/portal/graphql", AT_GRAPHQL_HEADERS, label, JSON_TIMEOUT, data=body)
        try:
            payload = resp.json()
        except Exception:
            if _looks_challenged(resp.text):
                raise Immoscout24Blocked(f"challenge page instead of JSON for {label}")
            raise Immoscout24UpstreamError(f"non-JSON GraphQL response for {label} (HTTP {resp.status_code})")
        errors = payload.get("errors") if isinstance(payload, dict) else None
        if errors:
            first = errors[0] if isinstance(errors[0], dict) else {}
            code = ((first.get("extensions") or {}).get("code") or "")
            message = first.get("message") or "GraphQL error"
            if code in _AT_BAD_INPUT_CODES or resp.status_code == 400:
                raise Immoscout24BadRequest(message[:300])
            raise Immoscout24UpstreamError(f"GraphQL error for {label}: {message[:200]}")
        if resp.status_code != 200 or not isinstance(payload, dict) or "data" not in payload:
            raise Immoscout24UpstreamError(f"HTTP {resp.status_code} for {label}")
        return payload["data"]
    return _retrying(once)


def at_search(path):
    """getDataByURL for a /regional/… path (with /seite-N and ?filters) ->
    the DataByURLResponse."""
    data = at_graphql(AT_GET_DATA_QUERY, {"p": {"URL": path}}, f"search {path}")
    return (data or {}).get("getDataByURL") or {}


def at_url_and_total(params):
    """getURLByParams + getTotalHitsByParams for a SearchParamsInput (string
    values) -> (canonical path, total hits)."""
    data = at_graphql(AT_URL_AND_TOTAL_QUERY, {"p": params}, "search url") or {}
    url = ((data.get("getURLByParams") or {}).get("URL"))
    total = ((data.get("getTotalHitsByParams") or {}).get("totalHits"))
    return url, total


def at_tokenize(text):
    """The site's free-text parser: "Graz 3 Zimmer" -> entities (locations
    with region id / postcode, filters) + suggestions."""
    data = at_graphql(AT_TOKENIZE_QUERY, {"query": text, "cursor": len(text)}, f"location lookup {text!r}") or {}
    return data.get("tokenize") or {}


def at_expose_page(listing_id):
    """GET /expose/<id> -> the page HTML (its __APOLLO_STATE__ holds the record)."""
    url = f"{AT_SITE}/expose/{listing_id}"
    label = f"listing {listing_id}"

    def once():
        resp = _request("GET", url, AT_PAGE_HEADERS, label, PAGE_TIMEOUT)
        if resp.status_code in (404, 410):
            raise Immoscout24NotFound(f"{label} not found")
        if resp.status_code != 200:
            raise Immoscout24UpstreamError(f"HTTP {resp.status_code} for {label}")
        text = resp.text
        if "__APOLLO_STATE__" not in text:
            if _looks_challenged(text):
                raise Immoscout24Blocked(f"challenge page for {label}")
            raise Immoscout24UpstreamError(f"no Apollo state on the page for {label}")
        return text
    return _retrying(once)
