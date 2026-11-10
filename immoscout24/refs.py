"""Reference resolvers, the property-type vocabulary and link grammars for
/immoscout24/* (ImmoScout24 Germany + Austria).

ONE param per input (tripadvisor QueryOrIdField convention, never a sibling
`url` / `id` pair):

    listing   a German expose id (164121861), an Austrian expose id (24 hex
              chars, 6221daade5cacea45c023057) OR any immobilienscout24.de /
              .at expose link — the id's shape names the country
    project   a German new-build project id (143514) OR a link carrying it
    query     a place name ("Berlin Mitte", "Graz", a postcode), a geocode id
              from locations/search (1276003001, P276-10115-BERLIN, AT region
              009001) OR a pasted search link of either site (its place, type
              and filters are kept; the request's own filters win)

Two markets (2026-11-07): Germany is served by the ImmoScout app's own JSON
API (api.mobile.immobilienscout24.de, www is an AWS WAF challenge to every
curl identity), Austria by www.immobilienscout24.at's GraphQL gateway and
expose pages. Switzerland (immoscout24.ch) is DataDome-walled for curl and a
browser alike and is not offered.

The property-type vocabulary below is the union of both sites' catalogues,
written as <kind>_<deal>. The mobile API's `realestatetype` tokens and the
.at `estateType / transferType / useType` triples were verified on
2026-11-07 (research note + the /search/total probes of this session).
"""
import re
from urllib.parse import parse_qs, urlparse

SITES = {
    "de": "https://www.immobilienscout24.de",
    "at": "https://www.immobilienscout24.at",
}
DE_API = "https://api.mobile.immobilienscout24.de"
COUNTRIES = ("de", "at")
DEFAULT_COUNTRY = "de"

# the .at list pages are fixed at 25 rows and 100 pages (seite-101 answers
# an empty page); the mobile API takes any pagesize up to 100 (200 -> 412)
AT_PAGE_SIZE = 25
AT_MAX_PAGE = 100
DE_PAGE_SIZE_MAX = 100
DE_PAGE_SIZE_DEFAULT = 20

# ---- property types ----------------------------------------------------------------

# public type -> (mobile API realestatetype, pricetype or None). Commercial
# listings share one realestatetype per kind; the deal is split with
# `pricetype` (rentpermonth / buy), which the API refuses on investment /
# compulsory-auction / care types (buy-only or mixed by nature). Gastronomy
# is leased, not rented: its tokens are lease / buy (rentpermonth -> 412);
# commercial plots take rent / lease / buy and a comma list applies only its
# first value, so rent (898 of 979 rentable plots, 2026-11-10) it is.
DE_TYPES = {
    "apartment_rent": ("apartmentrent", None),
    "apartment_buy": ("apartmentbuy", None),
    "house_rent": ("houserent", None),
    "house_buy": ("housebuy", None),
    "plot_rent": ("livingrentsite", None),
    "plot_buy": ("livingbuysite", None),
    "garage_rent": ("garagerent", None),
    "garage_buy": ("garagebuy", None),
    "room_rent": ("flatshareroom", None),
    "short_term_rent": ("shortTermAccommodation", None),
    "office_rent": ("office", "rentpermonth"),
    "office_buy": ("office", "buy"),
    "retail_rent": ("store", "rentpermonth"),
    "retail_buy": ("store", "buy"),
    "industry_rent": ("industry", "rentpermonth"),
    "industry_buy": ("industry", "buy"),
    "gastronomy_rent": ("gastronomy", "lease"),
    "gastronomy_buy": ("gastronomy", "buy"),
    "special_purpose_rent": ("specialpurpose", "rentpermonth"),
    "special_purpose_buy": ("specialpurpose", "buy"),
    "commercial_plot_rent": ("tradesite", "rent"),
    "commercial_plot_buy": ("tradesite", "buy"),
    "investment_buy": ("investment", None),
    "compulsory_auction": ("compulsoryauction", None),
    "senior_care": ("seniorcare", None),
    "assisted_living": ("assistedliving", None),
    "prefab_house": ("houseType", None),
}

# public type -> (estateType, transferType, useType) on immobilienscout24.at
AT_TYPES = {
    "apartment_rent": ("APARTMENT", "RENT", "RESIDENTIAL"),
    "apartment_buy": ("APARTMENT", "BUY", "RESIDENTIAL"),
    "house_rent": ("HOUSE", "RENT", "RESIDENTIAL"),
    "house_buy": ("HOUSE", "BUY", "RESIDENTIAL"),
    "plot_rent": ("PROPERTY", "RENT", "RESIDENTIAL"),
    "plot_buy": ("PROPERTY", "BUY", "RESIDENTIAL"),
    "garage_rent": ("PARKING_PLACE", "RENT", "RESIDENTIAL"),
    "garage_buy": ("PARKING_PLACE", "BUY", "RESIDENTIAL"),
    "room_rent": ("ROOM", "RENT", "RESIDENTIAL"),
    "short_term_rent": ("APARTMENT", "TEMPORARY_RENT", "RESIDENTIAL"),
    "office_rent": ("OFFICE", "RENT", "COMMERCIAL"),
    "office_buy": ("OFFICE", "BUY", "COMMERCIAL"),
    "retail_rent": ("RETAIL", "RENT", "COMMERCIAL"),
    "retail_buy": ("RETAIL", "BUY", "COMMERCIAL"),
    "industry_rent": ("INDUSTRIAL", "RENT", "COMMERCIAL"),
    "industry_buy": ("INDUSTRIAL", "BUY", "COMMERCIAL"),
    "gastronomy_rent": ("GASTRONOMY", "RENT", "COMMERCIAL"),
    "gastronomy_buy": ("GASTRONOMY", "BUY", "COMMERCIAL"),
    "hotel_rent": ("HOTEL", "RENT", "COMMERCIAL"),
    "hotel_buy": ("HOTEL", "BUY", "COMMERCIAL"),
    "investment_buy": ("INVESTMENTPROPERTY", "BUY", "COMMERCIAL"),
    "agriculture_rent": ("AGRICULTURE_AND_TIMBER", "RENT", "COMMERCIAL"),
    "agriculture_buy": ("AGRICULTURE_AND_TIMBER", "BUY", "COMMERCIAL"),
    "leisure_rent": ("LEISUREFACILITY", "RENT", "COMMERCIAL"),
    "leisure_buy": ("LEISUREFACILITY", "BUY", "COMMERCIAL"),
}

# Every public type, residential first, then commercial, then the
# one-market types — a literal so the publishing tools can read it
# (test_parsers checks it equals DE_TYPES | AT_TYPES).
TYPES = (
    "apartment_rent", "apartment_buy", "house_rent", "house_buy", "plot_rent", "plot_buy",
    "garage_rent", "garage_buy", "room_rent", "short_term_rent",
    "office_rent", "office_buy", "retail_rent", "retail_buy", "industry_rent", "industry_buy",
    "gastronomy_rent", "gastronomy_buy", "investment_buy",
    # Germany only
    "special_purpose_rent", "special_purpose_buy", "commercial_plot_rent", "commercial_plot_buy",
    "compulsory_auction", "senior_care", "assisted_living", "prefab_house",
    # Austria only
    "hotel_rent", "hotel_buy", "agriculture_rent", "agriculture_buy", "leisure_rent", "leisure_buy",
)
DEFAULT_TYPE = "apartment_rent"

# mobile API realestatetype -> the public type a list row reports (commercial
# rows carry no deal, so they report the kind alone)
DE_TYPE_LABELS = {
    "apartmentrent": "apartment_rent", "apartmentbuy": "apartment_buy",
    "houserent": "house_rent", "housebuy": "house_buy",
    "livingrentsite": "plot_rent", "livingbuysite": "plot_buy",
    "garagerent": "garage_rent", "garagebuy": "garage_buy",
    "flatshareroom": "room_rent", "shortTermAccommodation": "short_term_rent",
    "office": "office", "store": "retail", "industry": "industry", "gastronomy": "gastronomy",
    "specialpurpose": "special_purpose", "tradesite": "commercial_plot",
    "investment": "investment_buy", "compulsoryauction": "compulsory_auction",
    "seniorcare": "senior_care", "assistedliving": "assisted_living", "houseType": "prefab_house",
}

AT_ESTATE_LABELS = {
    "APARTMENT": "apartment", "HOUSE": "house", "PROPERTY": "plot", "PARKING_PLACE": "garage",
    "ROOM": "room", "OFFICE": "office", "RETAIL": "retail", "INDUSTRIAL": "industry",
    "GASTRONOMY": "gastronomy", "HOTEL": "hotel", "INVESTMENTPROPERTY": "investment",
    "AGRICULTURE_AND_TIMBER": "agriculture", "LEISUREFACILITY": "leisure", "MISCELLANEOUS": "other",
}
AT_TRANSFER_LABELS = {"RENT": "rent", "BUY": "buy", "TEMPORARY_RENT": "short_term_rent",
                      "LEASE": "lease", "LEASEHOLD": "leasehold"}


def at_type_label(estate_type, transfer_type):
    """("APARTMENT", "TEMPORARY_RENT") -> "short_term_rent"; ("HOUSE", "BUY") -> "house_buy"."""
    if not estate_type:
        return None
    kind = AT_ESTATE_LABELS.get(estate_type, str(estate_type).lower())
    deal = AT_TRANSFER_LABELS.get(transfer_type)
    if deal == "short_term_rent" and kind == "apartment":
        return "short_term_rent"
    return f"{kind}_{deal}" if deal else kind


# ---- sort orders ---------------------------------------------------------------------

# `area` and `rooms` sort biggest first on both markets: the mobile API's bare
# `livingspace` / `rooms` tokens sort ascending (1 m² junk rows first, checked
# 2026-11-10), `-livingspace` / `-rooms` descending like .at's AREA_DESC.
DE_SORTS = {
    "default": "standard", "price_asc": "price", "price_desc": "-price", "rooms": "-rooms",
    "area": "-livingspace", "newest": "-firstactivation", "oldest": "firstactivation",
}
AT_SORTS = {
    "default": None, "price_asc": "PRICE_ASC", "price_desc": "PRICE_DESC", "rooms": None,
    "area": "AREA_DESC", "newest": "CREATED_DESC", "oldest": None,
}
SORTS = ("default", "price_asc", "price_desc", "rooms", "area", "newest", "oldest")   # = DE_SORTS keys (tested)

# ---- filter vocabularies -----------------------------------------------------------

# public feature -> (mobile API `equipment` token, .at SearchParamsInput field + value)
FEATURES = {
    "balcony": ("balcony", ("outdoorSpaces", "BALCONY")),
    "garden": ("garden", ("outdoorSpaces", "GARDEN")),
    "terrace": (None, ("outdoorSpaces", "TERRACE")),
    "loggia": (None, ("outdoorSpaces", "LOGGIA")),
    "kitchen": ("builtinkitchen", None),
    "lift": ("lift", ("lift", "true")),
    "cellar": ("cellar", None),
    "parking": ("parking", None),
    "guest_toilet": ("guesttoilet", None),
    "barrier_free": ("handicappedaccessible", None),
    # Austria only: the mobile API accepts equipment=furnished but ignores it
    # (Berlin rentals 5,022 with and without, 2026-11-10)
    "furnished": (None, ("furnishing", "FURNISHED_FULL")),
}

ENERGY_CLASSES = {"a_plus": "a_plus", "a": "a", "b": "b", "c": "c", "d": "d", "e": "e", "f": "f",
                  "g": "g", "h": "h"}

APARTMENT_TYPES = {
    "apartment": "apartment", "roof_storey": "roofstorey", "loft": "loft", "maisonette": "maisonette",
    "penthouse": "penthouse", "terraced_flat": "terracedflat", "ground_floor": "groundfloor",
    "raised_ground_floor": "raisedgroundfloor", "half_basement": "halfbasement", "other": "other",
}

HOUSE_TYPES = {
    "single_family": "singlefamilyhouse", "mid_terrace": "midterracehouse", "end_terrace": "endterracehouse",
    "semi_detached": "semidetachedhouse", "multi_family": "multifamilyhouse", "bungalow": "bungalow",
    "farmhouse": "farmhouse", "villa": "villa", "castle": "castlemanorhouse", "special": "specialrealestate",
}

# ---- identifiers ----------------------------------------------------------------

DE_ID_RE = re.compile(r"^[0-9]{5,12}$")
AT_ID_RE = re.compile(r"^[0-9a-f]{24}$", re.I)
PROJECT_ID_RE = re.compile(r"^[0-9]{1,10}$")
_LINK_DE_EXPOSE_RE = re.compile(r"/expose/([0-9]{5,12})(?:[/?#]|$)")
_LINK_AT_EXPOSE_RE = re.compile(r"/expose/([0-9a-f]{24})(?:[/?#]|$)", re.I)
_LINK_PROJECT_RE = re.compile(r"(?:/project/|/projekt/|projectId=|project_id=)([0-9]{1,10})")

DE_GEOCODE_RE = re.compile(r"^1276[0-9]{0,12}$")          # 1276 = Germany, then state/city/quarter digits
DE_POSTCODE_GEOCODE_RE = re.compile(r"^P276-[0-9]{5}-", re.I)   # postcode entity from locations/search
DE_POSTCODE_RE = re.compile(r"^[0-9]{5}$")
AT_REGION_RE = re.compile(r"^(?:[0-9]{3}){1,3}$")           # 005 state, 009001 city, 009001002 district
AT_POSTCODE_RE = re.compile(r"^[0-9]{4}$")


def _site_country(host):
    host = (host or "").lower()
    if host == "immobilienscout24.de" or host.endswith(".immobilienscout24.de"):
        return "de"
    if host == "immobilienscout24.at" or host.endswith(".immobilienscout24.at"):
        return "at"
    if host == "immoscout24.ch" or host.endswith(".immoscout24.ch"):
        raise ValueError("immoscout24.ch (Switzerland) is not supported; use an immobilienscout24.de "
                         "or immobilienscout24.at link.")
    return None


def _as_url(value):
    if value.startswith("//"):
        return "https:" + value
    return value


def _is_link(value):
    return value.startswith(("http://", "https://", "//"))


def resolve_listing(value):
    """Bare expose id (German digits / Austrian 24-hex) or an expose link of
    either site -> {"country": "de"|"at", "id": ...}."""
    value = (value or "").strip()
    if DE_ID_RE.match(value):
        return {"country": "de", "id": value}
    if AT_ID_RE.match(value):
        return {"country": "at", "id": value.lower()}
    if _is_link(value):
        url = _as_url(value)
        country = _site_country(urlparse(url).hostname)
        if country is None:
            raise ValueError("Must be an immobilienscout24.de or immobilienscout24.at link.")
        match = _LINK_DE_EXPOSE_RE.search(url) if country == "de" else _LINK_AT_EXPOSE_RE.search(url)
        if match:
            return {"country": country, "id": match.group(1).lower()}
        raise ValueError("Must be an expose link (https://www.immobilienscout24.de/expose/<id> or "
                         "https://www.immobilienscout24.at/expose/<id>).")
    raise ValueError("Must be an expose id (164121861 for Germany, a 24-character id for Austria) "
                     "or an immobilienscout24.de / .at expose link.")


def resolve_project(value):
    """Bare German project id or a link carrying one -> the id."""
    value = (value or "").strip()
    if PROJECT_ID_RE.match(value):
        return value
    if _is_link(value) or value.startswith("is24://"):
        match = _LINK_PROJECT_RE.search(value)
        if match:
            return match.group(1)
        raise ValueError("Must be a link that carries a project id (…/project/<id> or ?projectId=<id>).")
    raise ValueError("Must be a German new-build project id (143514, from listings/details "
                     "`project.id`) or a link that carries one.")


def listing_link(country, listing_id):
    return f"{SITES[country]}/expose/{listing_id}"


# ---- search-link grammars ------------------------------------------------------------

# www.immobilienscout24.de/Suche/de/<land>/<stadt>[/<ortsteil>]/<typ> type slugs
DE_SLUG_TYPES = {
    "wohnung-mieten": "apartment_rent", "wohnung-kaufen": "apartment_buy",
    "neubauwohnung-kaufen": "apartment_buy", "neubauwohnung-mieten": "apartment_rent",
    "haus-mieten": "house_rent", "haus-kaufen": "house_buy", "neubau-haus-kaufen": "house_buy",
    "grundstueck-kaufen": "plot_buy", "grundstueck-mieten": "plot_rent", "grundstueck-pachten": "plot_rent",
    "garage-mieten": "garage_rent", "garage-kaufen": "garage_buy",
    "wg-zimmer": "room_rent", "wohnen-auf-zeit": "short_term_rent",
    "buero-praxis-mieten": "office_rent", "buero-praxis-kaufen": "office_buy",
    "einzelhandel-mieten": "retail_rent", "einzelhandel-kaufen": "retail_buy",
    "hallen-produktion-mieten": "industry_rent", "hallen-produktion-kaufen": "industry_buy",
    "gastronomie-hotel-mieten": "gastronomy_rent", "gastronomie-hotel-kaufen": "gastronomy_buy",
    "spezialgewerbe-mieten": "special_purpose_rent", "spezialgewerbe-kaufen": "special_purpose_buy",
    "gewerbegrundstueck-mieten": "commercial_plot_rent", "gewerbegrundstueck-kaufen": "commercial_plot_buy",
    "anlageimmobilien": "investment_buy", "zwangsversteigerung": "compulsory_auction",
    "seniorenwohnung-mieten": "senior_care", "betreutes-wohnen": "assisted_living",
    "haus-bauen": "prefab_house",
}
_NEW_BUILD_SLUGS = {"neubauwohnung-kaufen", "neubauwohnung-mieten", "neubau-haus-kaufen"}

# www.immobilienscout24.at/regional/<bundesland>/<stadt>/<typ> type slugs (the
# site builds them from the params; getURLByParams is the source of truth, this
# table only reads pasted links)
AT_SLUG_TYPES = {
    "wohnung-mieten": "apartment_rent", "wohnung-kaufen": "apartment_buy",
    "haus-mieten": "house_rent", "haus-kaufen": "house_buy",
    "grundstueck-kaufen": "plot_buy", "grundstueck-mieten": "plot_rent", "grundstueck-pachten": "plot_rent",
    "garage-mieten": "garage_rent", "garage-kaufen": "garage_buy", "wg-zimmer-mieten": "room_rent",
    "buero-mieten": "office_rent", "buero-kaufen": "office_buy",
    "geschaeft-mieten": "retail_rent", "geschaeft-kaufen": "retail_buy",
    "lagerhalle-mieten": "industry_rent", "lagerhalle-kaufen": "industry_buy",
    "gastronomie-mieten": "gastronomy_rent", "gastronomie-kaufen": "gastronomy_buy",
    "hotel-mieten": "hotel_rent", "hotel-kaufen": "hotel_buy",
    "anlageobjekt-kaufen": "investment_buy",
}

_RANGE_RE = re.compile(r"^(-?[0-9]*\.?[0-9]*)-(-?[0-9]*\.?[0-9]*)$")


def _range(value):
    """"500-900" -> (500.0, 900.0); "-900" -> (None, 900.0); "2.0-" -> (2.0, None)."""
    match = _RANGE_RE.match(value or "")
    if not match:
        return None, None

    def num(text):
        try:
            return float(text) if text not in ("", "-") else None
        except ValueError:
            return None
    return num(match.group(1)), num(match.group(2))


def parse_de_search_link(url):
    """A www.immobilienscout24.de search link -> {"place": "<last location
    slug>" | None, "coordinates": (lat, lon, km) | None, "type": public
    type | None, "filters": {min_price, max_price, ...}, "page"}.
    Grammar: /Suche/de/<land>/<stadt>[/<ortsteil>]/<typ>?price=-900&…
    (region search) and /Suche/radius/<typ>?geocoordinates=lat;lon;km
    (radius search); a drawn-shape link (/Suche/shape/…) is refused."""
    parsed = urlparse(url)
    segments = [s for s in parsed.path.split("/") if s]
    if not segments or segments[0].lower() != "suche":
        raise ValueError("Must be a search link (https://www.immobilienscout24.de/Suche/de/<land>/<stadt>/<typ>…).")
    query = {k: v[-1] for k, v in parse_qs(parsed.query).items()}
    out = {"place": None, "coordinates": None, "type": None, "filters": {}, "page": None}
    mode = segments[1].lower() if len(segments) > 1 else ""
    if mode == "shape":
        raise ValueError("Drawn-area (shape) search links are not supported; search by place or coordinates.")
    type_slug = segments[-1].lower()
    if type_slug in DE_SLUG_TYPES:
        out["type"] = DE_SLUG_TYPES[type_slug]
        if type_slug in _NEW_BUILD_SLUGS:
            out["filters"]["new_build"] = True
    elif query.get("realestatetype"):
        out["type"] = DE_TYPE_LABELS.get(query["realestatetype"])
    if mode == "radius":
        coords = query.get("geocoordinates", "")
        parts = coords.split(";")
        try:
            lat, lon = float(parts[0]), float(parts[1])
            km = float(parts[2]) if len(parts) > 2 and parts[2] else 5.0
        except (ValueError, IndexError):
            raise ValueError("A radius search link needs geocoordinates=lat;lon;km.")
        out["coordinates"] = (lat, lon, km)
    else:
        # /Suche/de/<land>/<stadt>[/<ortsteil>]/<typ>: the deepest place segment
        places = segments[2:-1] if type_slug in DE_SLUG_TYPES else segments[2:]
        if not places:
            raise ValueError("The search link names no place (expected /Suche/de/<land>/<stadt>/<typ>).")
        out["place"] = " ".join(s.replace("-", " ") for s in places[-2:]) if len(places) > 1 else places[-1].replace("-", " ")
        out["place_slugs"] = places
    f = out["filters"]
    lo, hi = _range(query.get("price", ""))
    f["min_price"], f["max_price"] = lo, hi
    lo, hi = _range(query.get("numberofrooms", ""))
    f["min_rooms"], f["max_rooms"] = lo, hi
    lo, hi = _range(query.get("livingspace", "") or query.get("netfloorspace", "") or query.get("plotarea", ""))
    f["min_area"], f["max_area"] = lo, hi
    lo, _ = _range(query.get("constructionyear", ""))
    f["min_year"] = int(lo) if lo else None
    if query.get("equipment"):
        reverse = {v[0]: k for k, v in FEATURES.items() if v[0]}
        f["features"] = [reverse[t] for t in query["equipment"].split(",") if t in reverse] or None
    if query.get("petsallowedtypes"):
        f["pets"] = True
    if query.get("newbuilding") == "true":
        f["new_build"] = True
    if query.get("fulltext"):
        f["keyword"] = query["fulltext"]
    if query.get("pagenumber", "").isdigit():
        out["page"] = int(query["pagenumber"])
    out["filters"] = {k: v for k, v in f.items() if v is not None}
    return out


_AT_PAGE_RE = re.compile(r"/seite-([0-9]+)$")


def parse_at_search_link(url):
    """A www.immobilienscout24.at list link -> {"path": "/regional/…" (page
    segment removed), "query": {…}, "page", "type"}. The path goes straight
    to the site's getDataByURL, which resolves the place itself."""
    parsed = urlparse(url)
    path = parsed.path.rstrip("/")
    if not path.startswith("/regional/"):
        raise ValueError("Must be a list link (https://www.immobilienscout24.at/regional/<bundesland>/<stadt>/<typ>…).")
    page = None
    match = _AT_PAGE_RE.search(path)
    if match:
        page = int(match.group(1))
        path = path[:match.start()]
    query = {k: v[-1] for k, v in parse_qs(parsed.query).items()}
    type_slug = next((s for s in reversed(path.split("/")) if s in AT_SLUG_TYPES), None)
    return {"path": path, "query": query, "page": page, "type": AT_SLUG_TYPES.get(type_slug)}


def classify_query(value, country):
    """What a `query` value is, without network:
        {"kind": "de_link", ...parse_de_search_link}  a .de search link
        {"kind": "at_link", ...parse_at_search_link}  a .at list link
        {"kind": "geocode", "id": ...}                 a site location id
        {"kind": "text", "text": ...}                  a place name / postcode
    A link overrides `country`."""
    value = (value or "").strip()
    if _is_link(value):
        url = _as_url(value)
        site = _site_country(urlparse(url).hostname)
        if site == "de":
            return {"kind": "de_link", "country": "de", **parse_de_search_link(url)}
        if site == "at":
            return {"kind": "at_link", "country": "at", **parse_at_search_link(url)}
        raise ValueError("Must be a place name, a location id or an immobilienscout24.de / .at search link.")
    if country == "de" and (DE_GEOCODE_RE.match(value) or DE_POSTCODE_GEOCODE_RE.match(value)):
        return {"kind": "geocode", "country": "de", "id": value.upper() if value[:1].lower() == "p" else value}
    if country == "at" and AT_REGION_RE.match(value):
        return {"kind": "geocode", "country": "at", "id": value}
    return {"kind": "text", "country": country, "text": value}
