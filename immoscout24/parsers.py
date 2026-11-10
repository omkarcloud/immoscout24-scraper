"""Raw JSON / HTML -> clean dicts for every /immoscout24/* endpoint. Pure
functions, no I/O.

Germany (api.mobile.immobilienscout24.de): a search page is
`resultListItems[{type, item}]` — EXPOSE_RESULT rows and, on commercial /
prefab searches, NEW_HOME_BUILDER_RESULT groups whose `groupingObjects` are
the real listings (flattened here, each tagged with its developer). An
expose is a flat `sections[]` list keyed by `type` (MEDIA, TOP_ATTRIBUTES,
TITLE, TAG_LIST, MAP, ATTRIBUTE_LIST ×3, TEXT_AREA ×n, PRICE_INFO,
FINANCE_COSTS, PROJECT_EXPOSE_LIST, AGENTS_INFO, CONTACT, OBJECT_INFO,
PREMIUM_ADDITIONAL_INFO, …) plus `adTargetingParameters`, ~60 raw
machine-readable fields (obj_baseRent, obj_livingSpace, obj_petsAllowed,
obj_street, …) that give the structured values the German labels only
paraphrase. The app's ad / upsell sections (AD, RELOCATION, TRAVELTIME,
COST_CHECK, AVAILABLE_SERVICES, FINANCE_CALCULATOR, FRAUD_REPORT) are
dropped. Plus-only statistics (views, contact requests, shortlists, online
since) arrive as null and stay null.

Austria (www.immobilienscout24.at): a list page is the getDataByURL
response (25 hits per page, each a typed Listing fragment); an expose is
the page's `window.__APOLLO_STATE__["Expose:<id>"]` record (the site's
Apollo cache, `undefined` tokens included).

Value conventions (shared with the other scraper packages):
  * money    {"amount": 1589.0, "currency": "EUR", "text": "1.589 €"}; German
             number format ("1.589,50") is parsed, the printed text is kept
  * dates    ISO where the site gives a date (.at dateCreated / updatedAt);
             the German list only says "vor 2 Monaten", kept as
             `published_ago` text since it is not a date
  * keys     snake_case; `link` not `url`; booleans as questions; null for
             anything the page does not carry

Fixtures (immoscout24/fixtures/, captured 2026-11-07): German search page 1
(Berlin rentals, newest first), a past-the-end page, a grouped commercial
page, a radius house-buy page, search totals, three geo lookups (district,
postcode, no match), four exposes (rental in a new-build project, private
rental in its 72-hour window, house for sale with purchase costs, flat for
sale) + a 404, a project + a 410; Austrian getDataByURL pages (Vienna
rentals page 2 with a price cap, postcode 1010, offices page 2, a page past
the end, an unknown place, a near-empty country-wide search), three
tokenize lookups, getURLByParams, a developer-project expose page, a
regular rental expose page and the 410 page of a gone expose.
"""
import html as html_module
import json
import re
from urllib.parse import parse_qs, unquote, urlparse

from immoscout24 import refs

# ---- helpers ------------------------------------------------------------------------

_DE_NUMBER_RE = re.compile(r"-?\d{1,3}(?:\.\d{3})+(?:,\d+)?|-?\d+(?:,\d+)?")
_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_PHONE_RE = re.compile(r"(?:\+|0)[0-9][0-9 ()/.-]{6,}[0-9]")
_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"[ \t\r\f\v]+")
_APOLLO_RE = re.compile(r"window\.__APOLLO_STATE__\s*=\s*", re.S)


def _clean(value):
    if value is None:
        return None
    if isinstance(value, (int, float, bool)):
        return value
    text = " ".join(str(value).split())
    return text or None


def parse_de_number(text):
    """German number text -> float: "1.589 €" -> 1589.0, "33,10 €/m²" ->
    33.1, "125,98 m²" -> 125.98, "4,5" -> 4.5, "ab 350 m²" -> 350.0.
    None when there is no number."""
    if text is None:
        return None
    if isinstance(text, (int, float)) and not isinstance(text, bool):
        return float(text)
    match = _DE_NUMBER_RE.search(str(text))
    if not match:
        return None
    token = match.group(0).replace(".", "").replace(",", ".")
    try:
        return float(token)
    except ValueError:
        return None


def _as_float(value):
    """A raw API number or numeric string ("125.98", 1589, "4.5") -> float."""
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value).replace(",", "."))
    except ValueError:
        return None


def _as_int(value):
    number = _as_float(value)
    return int(number) if number is not None and number == int(number) else number


def _money(text):
    """"1.589 €" -> {"amount": 1589.0, "currency": "EUR", "text": "1.589 €"}; no € -> None."""
    text = _clean(text)
    if not text or "€" not in text:
        return None
    return {"amount": parse_de_number(text), "currency": "EUR", "text": text}


def _yes_no(value):
    """The ad-targeting y / n / true / false / yes / no flags -> bool, else None."""
    if value is None:
        return None
    low = str(value).strip().lower()
    if low in ("y", "yes", "true", "1"):
        return True
    if low in ("n", "no", "false", "0"):
        return False
    return None


def _no_information(value):
    value = _clean(value)
    if value is None or value.lower() in ("no_information", "keine angabe", "none"):
        return None
    return value


def _picture(url, size="800x600"):
    """The CDN's template URL (…/resize/%WIDTH%x%HEIGHT%%3E/…) with a real size."""
    if not url:
        return None
    return url.replace("%WIDTH%x%HEIGHT%", size)


def _strip_html(text):
    if not text:
        return None
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</p>", "\n\n", text)
    text = _TAG_RE.sub("", text)
    text = html_module.unescape(text)
    lines = [_WS_RE.sub(" ", line).strip() for line in text.split("\n")]
    out = "\n".join(lines).strip()
    out = re.sub(r"\n{3,}", "\n\n", out)
    return out or None


# ---- Germany: locations --------------------------------------------------------------

def parse_de_autocomplete(payload):
    """/geo/autocomplete -> [{id, name, type, parent, latitude, longitude, search_type}]."""
    rows = []
    for item in (payload or {}).get("results") or []:
        if not isinstance(item, dict) or not item.get("id"):
            continue
        rows.append({
            "id": item.get("id"),
            "name": _clean(item.get("displayName")),
            "type": _clean(item.get("type")),
            "parent": _clean(item.get("parentName")),
            "latitude": _as_float(item.get("lat")),
            "longitude": _as_float(item.get("lon")),
            # region = searchable by id; radius = a street / address, searched
            # by its coordinates (listings/search_by_coordinates)
            "search_type": _clean(item.get("searchType")),
        })
    return rows


# ---- Germany: search pages -----------------------------------------------------------

def _key_facts(values):
    """The list row's unlabeled attribute strings ("1.589 €", "48 m²", "2 Zi.",
    "30 € /m²", "765 m² Nfl.") -> parsed price / area / rooms + the raw list."""
    texts = [_clean(v) for v in values if _clean(v)]
    out = {"price": None, "price_per_m2": None, "area_m2": None, "rooms": None, "plot_m2": None,
           "key_facts": texts}
    for text in texts:
        low = text.lower()
        if "€" in text and "/m²" in low and out["price_per_m2"] is None:
            out["price_per_m2"] = parse_de_number(text)
        elif "€" in text and out["price"] is None:
            out["price"] = _money(text)
        elif "zi." in low or "zimmer" in low:
            if out["rooms"] is None:
                out["rooms"] = parse_de_number(text)
        elif "m²" in text:
            if "grundst" in low and out["plot_m2"] is None:
                out["plot_m2"] = parse_de_number(text)
            elif out["area_m2"] is None:
                out["area_m2"] = parse_de_number(text)
    return out


def _de_tags(item):
    out = []
    for tag in item.get("tags") or []:
        name = tag.get("tag") if isinstance(tag, dict) else tag
        if name == "listOnlyOnIs24":
            name = "only_on_immoscout"
        if name and name not in out:
            out.append(name)
    return out


def _de_list_row(item, developer=None):
    address = item.get("address") or {}
    facts = _key_facts(a.get("value") for a in (item.get("attributes") or []) if isinstance(a, dict))
    title_picture = item.get("titlePicture") or {}
    photo = title_picture.get("full") or _picture((item.get("picture") or {}).get("urlScaleAndCrop"))
    if not photo:
        pictures = item.get("pictures") or []
        photo = _picture(pictures[0].get("urlScaleAndCrop")) if pictures and isinstance(pictures[0], dict) else None
    realtor = item.get("realtor") or {}
    listing_id = str(item.get("id")) if item.get("id") is not None else None
    tags = _de_tags(item)
    return {
        "id": listing_id,
        "link": refs.listing_link("de", listing_id) if listing_id else None,
        "title": _clean(item.get("title")),
        "type": refs.DE_TYPE_LABELS.get(item.get("realEstateType")) if item.get("realEstateType") else None,
        "price": facts["price"],
        "price_per_m2": facts["price_per_m2"],
        "area_m2": facts["area_m2"],
        "plot_m2": facts["plot_m2"],
        "rooms": facts["rooms"],
        "key_facts": facts["key_facts"],
        "address": {
            "text": _clean(address.get("line")),
            "postcode": _clean(address.get("postcode")),
            "latitude": _as_float(address.get("lat")),
            "longitude": _as_float(address.get("lon")),
        },
        "photo": photo,
        "energy_class": _clean(item.get("energyEfficiencyClass")),
        "published_ago": _clean(item.get("published")),
        "is_private": bool(item.get("isPrivate")) if "isPrivate" in item else None,
        "is_project": bool(item.get("isProject")) if "isProject" in item else None,
        "is_new": bool(item.get("isNewObject")) if "isNewObject" in item else None,
        "has_live_video_tour": bool(item.get("liveVideoTourAvailable")) if "liveVideoTourAvailable" in item else None,
        "is_exclusive": "only_on_immoscout" in tags,
        "has_contact_paywall": "paywall" in tags,
        "badges": tags,
        "listing_size": _clean(item.get("listingType")),
        "agency_logo": _picture(realtor.get("logoUrlScale")),
        "developer": developer,
    }


def parse_de_search(payload, page, page_size, fallback_type=None):
    """A /search/list page -> {"results": [...], "pagination": {...}}.
    NEW_HOME_BUILDER_RESULT groups (commercial / prefab searches) are
    flattened into their listings, each carrying its developer's name; a
    row without its own realEstateType reports `fallback_type` (the type
    that was searched)."""
    payload = payload or {}
    rows = []
    for entry in payload.get("resultListItems") or []:
        if not isinstance(entry, dict):
            continue
        item = entry.get("item") or {}
        kind = entry.get("type")
        if kind == "EXPOSE_RESULT":
            rows.append(_de_list_row(item))
        elif kind == "NEW_HOME_BUILDER_RESULT" or item.get("groupingObjects"):
            developer = None
            for attr in item.get("attributes") or []:
                if isinstance(attr, dict) and _clean(attr.get("value")):
                    developer = _clean(attr.get("value"))
                    break
            logo = _picture((item.get("realtor") or {}).get("logoUrlScale"))
            for unit in item.get("groupingObjects") or []:
                if not isinstance(unit, dict):
                    continue
                row = _de_list_row(unit, developer=developer)
                row["agency_logo"] = row["agency_logo"] or logo
                if row["is_new"] is None and "isNewObject" in item:
                    row["is_new"] = bool(item.get("isNewObject"))
                rows.append(row)
        elif item.get("id"):
            rows.append(_de_list_row(item))
    for row in rows:
        if row["type"] is None:
            row["type"] = fallback_type
    total = _as_int(payload.get("totalResults"))
    total_pages = _as_int(payload.get("numberOfPages"))
    return {
        "results": rows,
        "pagination": {
            "page": _as_int(payload.get("pageNumber")) or page,
            "items_per_page": page_size,
            "total_pages": total_pages if total_pages is not None else 0,
            "total_count": total if total is not None else 0,
        },
    }


def parse_de_total(payload):
    payload = payload or {}
    return {
        "total": _as_int(payload.get("totalResults")) or 0,
        "coming_soon": _as_int(payload.get("comingSoonTotalResults")) or 0,
    }


# ---- Germany: expose -----------------------------------------------------------------

_DE_TEXT_TITLES = {
    "objektbeschreibung": "text", "ausstattung": "features", "lage": "location", "sonstiges": "other",
}
_DE_ATTRIBUTE_TITLES = {
    "hauptkriterien": "main", "kosten": "costs", "bausubstanz & energieausweis": "building",
}


def _attribute_dict(attributes):
    """An ATTRIBUTE_LIST -> {label: text | True} (LINK rows are ads: dropped)."""
    out = {}
    for attr in attributes or []:
        if not isinstance(attr, dict):
            continue
        label = _clean(attr.get("label"))
        if not label:
            continue
        label = label.rstrip(":").strip()
        kind = attr.get("type")
        if kind == "CHECK":
            out[label] = True
        elif kind == "TEXT":
            out[label] = _clean(attr.get("text"))
    return out


def _find(table, *labels):
    """The first value of a label (case-insensitive, prefix match) in an attribute dict."""
    if not table:
        return None
    lowered = {k.lower(): v for k, v in table.items()}
    for label in labels:
        label = label.lower()
        if label in lowered:
            return lowered[label]
        for key, value in lowered.items():
            if key.startswith(label):
                return value
    return None


def _imprint(url):
    """is24://imprint?text=<urlencoded lines> -> {"text", "email", "phone"}."""
    if not url or "imprint" not in url:
        return None
    query = parse_qs(urlparse(url).query)
    text = unquote((query.get("text") or [""])[0]) if query.get("text") else unquote(url.split("text=", 1)[-1])
    text = html_module.unescape(text).replace("\r\n", "\n").strip()
    if not text:
        return None
    email = _EMAIL_RE.search(text)
    phone = _PHONE_RE.search(text)
    return {"text": text, "email": email.group(0) if email else None,
            "phone": _clean(phone.group(0)) if phone else None}


def _references(references):
    """A REFERENCE_LIST's references -> (links, documents, imprint, homepage)."""
    links, documents, imprint, homepage = [], [], None, None
    for ref in references or []:
        if not isinstance(ref, dict):
            continue
        url = ref.get("url")
        label = _clean(ref.get("label"))
        kind = ref.get("type")
        if not url:
            continue
        if url.startswith("is24://imprint"):
            imprint = _imprint(url)
        elif url.startswith("is24://"):
            continue
        elif kind == "PDF" or url.lower().endswith(".pdf"):
            documents.append({"title": label, "link": url})
        elif ref.get("id") in ("external_project_homepage",) or (label and "homepage" in label.lower()):
            homepage = url
        elif "immobilienscout24.de/Suche/controller" in url:
            continue   # the www price-trend page (WAF-walled)
        else:
            links.append({"title": label, "link": url})
    return links, documents, imprint, homepage


def _media(section):
    photos, videos = [], []
    for item in (section or {}).get("media") or []:
        if not isinstance(item, dict):
            continue
        kind = item.get("type")
        if kind == "VIDEO" or item.get("videoUrl"):
            videos.append({"caption": _clean(item.get("caption")),
                           "link": item.get("videoUrl") or item.get("url") or item.get("fullImageUrl"),
                           "preview": item.get("previewImageUrl")})
        else:
            photos.append({"caption": _clean(item.get("caption")),
                           "link": item.get("fullImageUrl") or _picture(item.get("imageUrlForWeb"), "1500x1000"),
                           "preview": item.get("previewImageUrl")})
    return photos, videos


def _price_bar(section):
    bar = (section or {}).get("priceBar") or {}
    if not bar:
        return None
    this_text = _clean(bar.get("actualObject"))
    unit = "€/m²" if "/m²" in (bar.get("minPrice") or "") else "€"
    return {
        "unit": unit,
        "min": parse_de_number(bar.get("minPrice")),
        "max": parse_de_number(bar.get("maxPrice")),
        "similar_min": parse_de_number(bar.get("minSimilarPrice")),
        "similar_max": parse_de_number(bar.get("maxSimilarPrice")),
        "this_listing": parse_de_number(this_text),
        "position_percent": round(_as_float(bar.get("priceIndicatorPositionInPercent")) * 100, 1)
        if _as_float(bar.get("priceIndicatorPositionInPercent")) is not None else None,
    }


def _finance_costs(section):
    if not section:
        return None

    def cost(key):
        row = section.get(key) or {}
        if not isinstance(row, dict):
            return None
        return {"amount": _as_float(row.get("value")), "percent": parse_de_number(row.get("percentage")),
                "text": _clean(row.get("amount") or row.get("text"))}
    return {
        "purchase_price": _as_float((section.get("purchasePrice") or {}).get("value")),
        "additional_costs": _as_float((section.get("additionalCosts") or {}).get("value")),
        "total": _as_float((section.get("totalCosts") or {}).get("value")),
        "broker_commission": cost("brokerCommission"),
        "land_transfer_tax": cost("landTransferTax"),
        "notary": cost("notaryCosts"),
        "land_registry": cost("landRegistryEntry"),
        "monthly_rate_text": _clean(section.get("monthlyRate")),
        "assumptions": _clean(section.get("footer")),
        "currency": "EUR",
    }


def _agent(agents_info, contact, adt):
    agents_info = agents_info or {}
    contact_data = (contact or {}).get("contactData") or {}
    agent = contact_data.get("agent") or {}
    verified = agents_info.get("verifiedBy") or agent.get("verifiedBy") or []
    links, documents, imprint, homepage = _references(agents_info.get("references"))
    address = agents_info.get("address")
    return {
        "name": _clean(agents_info.get("name") or agent.get("name")),
        "company": _clean(agents_info.get("company") or agent.get("company")),
        "id": _clean(adt.get("obj_cId")),
        "logo": _picture(agents_info.get("logoUrl") or agent.get("logo"), "400x400"),
        "portrait": _picture(agents_info.get("portraitUrl"), "400x400"),
        "profile_link": agents_info.get("agentProfileUrl") or agent.get("companyUrl"),
        "homepage": homepage,
        "address": _clean(address.replace("\n", ", ")) if isinstance(address, str) else None,
        "is_verified": bool(verified),
        "verification": [_clean(v.get("label")) for v in verified if isinstance(v, dict) and v.get("label")],
        "imprint": imprint,
    }


def _phones(contact):
    out = []
    for row in (contact or {}).get("phoneNumbers") or []:
        if isinstance(row, dict) and _clean(row.get("text")):
            out.append({"label": _clean(row.get("label")), "number": _clean(row.get("text"))})
    return out


def _project_units(section):
    units = []
    for item in (section or {}).get("items") or []:
        if not isinstance(item, dict) or not item.get("id"):
            continue
        facts = _key_facts(item.get("attributes") or [])
        units.append({
            "id": str(item["id"]),
            "link": refs.listing_link("de", item["id"]),
            "title": _clean(item.get("title")),
            "price": facts["price"],
            "area_m2": facts["area_m2"],
            "rooms": facts["rooms"],
            "key_facts": facts["key_facts"],
            "photo": _picture(item.get("imageUrl")),
            "features": _clean(item.get("equipment")),
        })
    return units


def _sections_by_type(payload):
    grouped = {}
    for section in (payload or {}).get("sections") or []:
        if isinstance(section, dict) and section.get("type"):
            grouped.setdefault(section["type"], []).append(section)
    return grouped


def parse_de_expose(payload, listing_id):
    """GET /expose/<id> -> the listing record."""
    payload = payload or {}
    header = payload.get("header") or {}
    adt = payload.get("adTargetingParameters") or {}
    by = _sections_by_type(payload)
    first = lambda kind: (by.get(kind) or [None])[0]  # noqa: E731

    attributes = {}
    for section in by.get("ATTRIBUTE_LIST") or []:
        key = _DE_ATTRIBUTE_TITLES.get((_clean(section.get("title")) or "").lower(), _clean(section.get("title")) or "other")
        attributes[key] = _attribute_dict(section.get("attributes"))
    main, costs, building = attributes.get("main") or {}, attributes.get("costs") or {}, attributes.get("building") or {}

    description = {"text": None, "features": None, "location": None, "other": None}
    for section in by.get("TEXT_AREA") or []:
        key = _DE_TEXT_TITLES.get((_clean(section.get("title")) or "").lower())
        text = (section.get("text") or "").strip() or None
        if key:
            description[key] = text
        elif text:
            description.setdefault("other", None)
            description["other"] = (description["other"] + "\n\n" + text) if description["other"] else text

    top = [{"label": _clean(a.get("label")), "value": _clean(a.get("text"))}
           for a in (first("TOP_ATTRIBUTES") or {}).get("attributes") or [] if isinstance(a, dict)]
    tags = []
    for tag in (first("TAG_LIST") or {}).get("tags") or []:
        if isinstance(tag, dict):
            name = (tag.get("id") or tag.get("tag") or "").lower()
            if name == "only_here":
                name = "only_on_immoscout"
            if name and name not in tags:
                tags.append(name)
    map_section = first("MAP") or {}
    location = map_section.get("location") or {}
    photos, videos = _media(first("MEDIA"))
    contact = first("CONTACT") or payload.get("contact") or {}
    contact_data = contact.get("contactData") or {}
    freemium = contact.get("freemiumSettings") or {}

    links, documents, imprint, homepage = [], [], None, None
    for section in by.get("REFERENCE_LIST") or []:
        more_links, more_docs, _, _ = _references(section.get("references"))
        links.extend(more_links)
        documents.extend(more_docs)

    price_label = (top[0]["label"] if top else None) or None
    price_kind = (price_label or "").split(" ")[0] if price_label else None
    base_rent = _as_float(adt.get("obj_baseRent"))
    purchase_price = _as_float(adt.get("obj_purchasePrice"))
    top_price = _money(top[0]["value"]) if top and top[0]["value"] and "€" in top[0]["value"] else None
    price_per_m2 = parse_de_number(_find(costs, "Preis/m²")) or (parse_de_number(price_label) if price_label and "/m²" in price_label else None)

    project_section = first("PROJECT_EXPOSE_LIST") or {}
    project_id = _clean(adt.get("obj_projectId") or adt.get("obj_project_id") or contact_data.get("realEstateProjectId"))
    project = None
    if project_id or project_section:
        project = {
            "id": project_id,
            "title": _clean(project_section.get("title")),
            "units": _project_units(project_section),
        }

    premium = first("PREMIUM_ADDITIONAL_INFO") or {}
    real_estate_type = header.get("realEstateType") or contact_data.get("realEstateType")
    floor = _as_int(adt.get("obj_floor"))
    return {
        "id": str(header.get("id") or listing_id),
        "link": refs.listing_link("de", header.get("id") or listing_id),
        "title": _clean((first("TITLE") or {}).get("title")),
        "type": refs.DE_TYPE_LABELS.get(real_estate_type) if real_estate_type else None,
        "publication_state": _clean(header.get("publicationState")),
        "reference_number": _clean(adt.get("obj_objectnumber")),
        "is_private": _yes_no(adt.get("obj_privateOffer")),
        "is_new_build": _yes_no(adt.get("obj_newlyConst")),
        "is_exclusive": _yes_no(adt.get("obj_ExclusiveExpose")),
        "is_high_demand": _yes_no(adt.get("obj_highDemand")),
        "is_rented": _yes_no(adt.get("obj_rented")),
        "badges": tags,
        "price": {
            "amount": (top_price or {}).get("amount") if top_price else (purchase_price or base_rent),
            "currency": "EUR",
            "label": price_kind,
            "text": (top_price or {}).get("text"),
            "per_m2": price_per_m2,
            "base_rent": base_rent,
            "service_charge": _as_float(adt.get("obj_serviceCharge")),
            "heating_costs": _as_float(adt.get("obj_heatingCosts")),
            "is_heating_in_service_charge": {"ja": True, "nein": False}.get((_find(costs, "Heizkosten in Nebenkosten") or "").lower()),
            "total_rent": _as_float(adt.get("obj_totalRent")),
            "deposit": _find(costs, "Kaution"),
            "purchase_price": purchase_price,
            "parking_price": _money(_find(costs, "Garage/Stellplatz - Kaufpreis", "Garage/Stellplatz - Miete", "Stellplatz")),
            "buyer_commission": _find(costs, "Provision für Käufer", "Provision"),
            "has_buyer_commission": {"ja": True, "nein": False}.get((_find(costs, "Provision für Käufer") or "").lower())
            if _find(costs, "Provision für Käufer") else _yes_no(adt.get("obj_courtage")),
            "costs": costs,
        },
        "key_facts": top,
        "area": {
            "living_m2": _as_float(adt.get("obj_livingSpace")) or parse_de_number(_find(main, "Wohnfläche")),
            "usable_m2": parse_de_number(_find(main, "Nutzfläche")),
            "plot_m2": _as_float(adt.get("obj_lotArea")) or parse_de_number(_find(main, "Grundstück")),
        },
        "rooms": _as_float(adt.get("obj_noRooms")) or parse_de_number(_find(main, "Zimmer")),
        "bedrooms": _as_int(_find(main, "Schlafzimmer")),
        "bathrooms": _as_int(_find(main, "Badezimmer")),
        "floor": floor,
        "floors_total": _as_int(adt.get("obj_numberOfFloors")) or _as_int(_find(main, "Etagenzahl")),
        "year_built": _as_int(adt.get("obj_yearConstructed")) or _as_int(_find(building, "Baujahr")),
        "condition": _no_information(adt.get("obj_condition")) or _find(building, "Objektzustand"),
        "interior_quality": _no_information(adt.get("obj_interiorQual")) or _find(building, "Qualität der Ausstattung"),
        "apartment_type": _no_information(adt.get("obj_typeOfFlat")) or _find(main, "Wohnungstyp"),
        "house_type": _no_information(adt.get("obj_buildingType")) or _find(main, "Haustyp"),
        "available_from": _find(main, "Bezugsfrei ab", "Verfügbar ab"),
        "pets": _no_information(adt.get("obj_petsAllowed")) or _find(main, "Haustiere"),
        "features": {
            "balcony": _yes_no(adt.get("obj_balcony")) if adt.get("obj_balcony") is not None else bool(_find(main, "Balkon")),
            "garden": _yes_no(adt.get("obj_garden")) if adt.get("obj_garden") is not None else bool(_find(main, "Garten")),
            "kitchen": _yes_no(adt.get("obj_hasKitchen")) if adt.get("obj_hasKitchen") is not None else bool(_find(main, "Einbauküche")),
            "lift": _yes_no(adt.get("obj_lift")) if adt.get("obj_lift") is not None else bool(_find(main, "Personenaufzug")),
            "cellar": _yes_no(adt.get("obj_cellar")) if adt.get("obj_cellar") is not None else bool(_find(main, "Keller")),
            "barrier_free": _yes_no(adt.get("obj_barrierFree")) if adt.get("obj_barrierFree") is not None else bool(_find(main, "Stufenloser Zugang")),
            "guest_toilet": True if _find(main, "Gäste-WC") else None,
            "parking": _no_information(adt.get("obj_parkingSpace")) or _find(main, "Garage/Stellplatz"),
            "parking_spaces": _as_int(adt.get("obj_noParkSpaces")) or _as_int(_find(main, "Anzahl Garage/Stellplatz")),
            "assisted_living": _yes_no(adt.get("obj_assistedLiving")),
        },
        "energy": {
            "class": _find(building, "Energieeffizienzklasse"),
            "certificate": _find(building, "Energieausweis", "Energieausweistyp"),
            "consumption": _find(building, "Endenergieverbrauch", "Endenergiebedarf", "Energieverbrauchskennwert"),
            "carrier": _no_information(_find(building, "Wesentliche Energieträger")),
            "heating_type": _no_information(adt.get("obj_heatingType")) or _find(building, "Heizungsart"),
            "firing": _no_information(adt.get("obj_firingTypes")),
        },
        "attributes": {"main": main, "costs": costs, "building": building},
        "description": description,
        "address": {
            "text": ", ".join(p for p in (_clean(map_section.get("addressLine1")), _clean(map_section.get("addressLine2"))) if p) or None,
            # obj_street is HTML-escaped ("Daumstra&szlig;e"), obj_streetPlain
            # underscored ("Am_Carlsgarten"); the escaped one unescapes cleanly
            "street": html_module.unescape(_clean(adt.get("obj_street")) or "")
            or (_clean(adt.get("obj_streetPlain")) or "").replace("_", " ") or None,
            "house_number": html_module.unescape(_clean(adt.get("obj_houseNumber")) or "") or None,
            "postcode": _clean(adt.get("obj_zipCode")),
            "city": _clean(adt.get("obj_regio2")),
            "district": (_clean(adt.get("obj_regio3")) or "").replace("_", " ") or None,
            "quarter": _clean(adt.get("obj_regio4")),
            "state": _clean(adt.get("obj_regio1")),
            "country": "DE",
            "latitude": _as_float(location.get("lat")),
            "longitude": _as_float(location.get("lng") or location.get("lon")),
        },
        "photos": photos,
        "photos_count": len(photos),
        "videos": videos,
        "documents": documents,
        "links": links,
        "price_comparison": _price_bar(first("PRICE_INFO")),
        "purchase_costs": _finance_costs(first("FINANCE_COSTS")),
        "project": project,
        "agent": _agent(first("AGENTS_INFO"), contact, adt),
        "phones": _phones(contact),
        "contact": {
            "login_required": bool(contact.get("loginRequiredForContact")) if "loginRequiredForContact" in contact else None,
            "plus_profile_required": str(contact.get("premiumProfileRequiredForContacting")).lower() == "true"
            if contact.get("premiumProfileRequiredForContacting") is not None else None,
            # a private landlord's first 72 h: contact through the site is
            # reserved for Plus members (phones above are still public)
            "private_offer_window_until": _clean(freemium.get("dateEnding")) if freemium.get("freemiumPeriodActive") else None,
        },
        # Plus-only; the API answers them as null without a Plus login
        "stats": {
            "views": _as_int(premium.get("visits")),
            "contact_requests": _as_int(premium.get("contactRequests")),
            "shortlisted": _as_int(premium.get("shortlistAddEvents")),
            "online_since": _clean(premium.get("onlineSince")),
        },
    }


# ---- Germany: project ----------------------------------------------------------------

def parse_de_project(payload, project_id):
    """GET /project/<id> -> the new-build project record."""
    payload = payload or {}
    header = payload.get("header") or {}
    adt = payload.get("adTargetingParameters") or {}
    by = _sections_by_type(payload)
    first = lambda kind: (by.get(kind) or [None])[0]  # noqa: E731
    photos, videos = _media(first("MEDIA"))
    overview = {}
    for attr in (first("PROJECT_OVERVIEW") or {}).get("attributes") or []:
        if isinstance(attr, dict) and attr.get("type"):
            overview[attr["type"].lower()] = _clean(attr.get("text"))
    key_facts = [{"label": _clean(a.get("label")), "value": _clean((a.get("text") or "").replace("\n", ", "))}
                 for a in (first("PROJECT_TOP_ATTRIBUTES") or {}).get("attributes") or [] if isinstance(a, dict)]
    address_text = next((f["value"] for f in key_facts if (f["label"] or "").lower() == "adresse"), None)
    texts = [s.get("text") for s in by.get("TEXT_AREA") or [] if s.get("text")]
    map_text = first("MAP_TEXT_AREA") or {}
    map_location = map_text.get("location") or {}
    links, documents, imprint, homepage = [], [], None, None
    for section in by.get("REFERENCE_LIST") or []:
        more_links, more_docs, more_imprint, more_home = _references(section.get("references"))
        links.extend(more_links)
        documents.extend(more_docs)
        imprint = imprint or more_imprint
        homepage = homepage or more_home
    groups = []
    for group in (first("DEVELOPER_PROJECT_EXPOSE_LIST") or {}).get("itemGroups") or []:
        if isinstance(group, dict):
            groups.append({"title": _clean(group.get("title")), "units": _project_units(group)})
    agents = first("AGENTS_INFO") or {}
    contact = first("CONTACT") or payload.get("contact") or {}
    agent = (contact.get("contactData") or {}).get("agent") or {}
    units_count = sum(len(g["units"]) for g in groups)
    return {
        "id": str(header.get("id") or project_id),
        "name": _clean(header.get("name") or adt.get("obj_project_name") or overview.get("title")),
        "title": overview.get("title"),
        "subtitle": overview.get("subtitle"),
        "price_text": overview.get("price"),
        "developer": _clean(header.get("company") or adt.get("obj_developer_name")),
        "project_type": _clean(header.get("type")),
        "key_facts": key_facts,
        "address": {
            "text": address_text,
            "postcode": _clean(adt.get("obj_zipCode")),
            "city": _clean(adt.get("obj_regio2")),
            "district": (_clean(adt.get("obj_regio3")) or "").replace("_", " ") or None,
            "state": _clean(adt.get("obj_regio1")),
            "country": "DE",
            "latitude": _as_float(map_location.get("lat")),
            "longitude": _as_float(map_location.get("lng") or map_location.get("lon")),
        },
        "description": "\n\n".join(t.strip() for t in texts) or None,
        "location_description": (map_text.get("text") or "").strip() or None,
        "photos": photos,
        "photos_count": len(photos),
        "videos": videos,
        "documents": documents,
        "links": links,
        "homepage": homepage,
        "unit_groups": groups,
        "units_count": units_count,
        "agent": {
            "name": _clean(agents.get("name") or agent.get("name")),
            "company": _clean(agents.get("company") or agent.get("company")),
            "logo": _picture(agents.get("logoUrl") or agent.get("logo"), "400x400"),
            "profile_link": agents.get("companyUrl") or agent.get("companyUrl"),
            "imprint": imprint,
        },
        "phones": _phones(contact),
    }


# ---- Austria: locations (tokenize) --------------------------------------------------

def parse_at_tokenize(payload):
    """tokenize -> {"locations": [...], "filters": {...}, "unmatched": [...]}.
    Locations = the parser's active location entities first, then its
    location suggestions (deduplicated on the site's own key)."""
    payload = payload or {}
    rows, seen = [], set()

    def add(place_id, name, kind, match):
        if not place_id or (kind, place_id) in seen:
            return
        seen.add((kind, place_id))
        rows.append({
            "id": place_id,
            "name": _clean(name),
            "type": _clean(kind),
            "match": match,
            # postcodes are searched as zipCode, every other type as region
            "search_type": "postcode" if kind == "postcode" else "region",
        })
    for entity in payload.get("entities") or []:
        if isinstance(entity, dict) and entity.get("fieldName") == "locations":
            meta = entity.get("meta") or {}
            add(meta.get("id") or entity.get("value"), meta.get("label"), meta.get("type"), "parsed")
    for suggestion in payload.get("suggestions") or []:
        if not isinstance(suggestion, dict) or suggestion.get("source") != "location":
            continue
        key = suggestion.get("key") or ""
        place_id = key.rsplit(":", 1)[-1] if ":" in key else None
        add(place_id, suggestion.get("label"), suggestion.get("type"), _clean(suggestion.get("matchedBy")))
    parsed = payload.get("parsedParams") or {}
    filters = {k: v for k, v in parsed.items() if v not in (None, "", [])}
    return {
        "locations": rows,
        "filters": filters,
        "unmatched": [_clean(t.get("text")) for t in payload.get("leftoverTokens") or []
                      if isinstance(t, dict) and _clean(t.get("text"))],
    }


# ---- Austria: search pages -----------------------------------------------------------

def _at_hit(hit):
    links = hit.get("links") or {}
    meta = hit.get("meta") if isinstance(hit.get("meta"), dict) else {}
    location = hit.get("location") or {}
    contact = hit.get("realtorContact") or {}
    badges, transit = [], []
    for badge in hit.get("typedBadges") or []:
        if not isinstance(badge, dict):
            continue
        details = badge.get("details") or {}
        if badge.get("type") == "TRANSIT":
            lines = details.get("lines")
            if isinstance(lines, list):
                lines = ", ".join(str(l) for l in lines if l)
            transit.append({"lines": _clean(lines), "stop": _clean(details.get("stop"))})
        elif details.get("value"):
            badges.append(str(details["value"]).lower())
    price_fact = hit.get("primaryPriceKeyFact") or {}
    sqm_fact = hit.get("pricePerSqmKeyFact") or {}
    reduction = hit.get("priceReductionKeyFact") or {}
    listing_id = hit.get("exposeId")
    link = links.get("absoluteURL") or (refs.listing_link("at", listing_id) if listing_id else None)
    thumbs = [t.get("src") for t in hit.get("thumbnailPicturesImageProps") or [] if isinstance(t, dict) and t.get("src")]
    amount = _as_float(hit.get("primaryPrice"))
    return {
        "id": listing_id,
        "link": link,
        "title": _clean(hit.get("headline")),
        "type": refs.at_type_label(meta.get("estateType"), meta.get("transferType")),
        "price": {
            "amount": amount if amount else None,
            "currency": "EUR",
            "label": _clean(price_fact.get("label")),
            "text": _clean(price_fact.get("value")),
            "per_m2": parse_de_number(sqm_fact.get("value")),
            "reduction": {"original": _as_float(reduction.get("original")), "percent": _as_float(reduction.get("percent"))}
            if reduction and (reduction.get("original") or reduction.get("percent")) else None,
        },
        "area_m2": _as_float(hit.get("primaryArea")),
        "rooms": _as_float(hit.get("numberOfRooms")),
        "key_facts": [" ".join(p for p in (_clean(f.get("value")), _clean(f.get("label"))) if p)
                      for f in hit.get("mainKeyFacts") or [] if isinstance(f, dict) and _clean(f.get("value"))],
        "address": {
            "text": _clean(hit.get("addressString")),
            "is_complete": bool(hit.get("isAddressCompleteAndVisible")) if "isAddressCompleteAndVisible" in hit else None,
            "latitude": _as_float(location.get("lat")),
            "longitude": _as_float(location.get("lon")),
            "region_codes": hit.get("geoHierarchy") or None,
        },
        "photo": (hit.get("primaryPictureImageProps") or {}).get("src"),
        "photo_caption": _clean(hit.get("primaryPictureCaption")),
        "thumbnails": thumbs,
        "published": _clean(hit.get("dateCreated")),
        "is_private": bool(hit.get("isPrivate")) if "isPrivate" in hit else None,
        "is_project": bool(meta.get("hasChildren")) if meta else None,
        "is_social_housing": bool(hit.get("isSocialHousing")) if "isSocialHousing" in hit else None,
        "display_type": _clean(hit.get("displayType")),
        "badges": badges,
        "transit": transit,
        "agency": {
            "id": _clean(hit.get("accountCwid")),
            "company": _clean(contact.get("company")),
            "name": _clean(contact.get("name")),
            "logo": (hit.get("realtorLogoImageProps") or {}).get("src"),
            "portrait": (contact.get("contactImageProps") or {}).get("src"),
        },
    }


def parse_at_search(payload, page):
    """getDataByURL -> {"results", "place", "canonical_path", "pagination"}."""
    payload = payload or {}
    results = payload.get("results") or {}
    pagination = results.get("pagination") or {}
    spots = payload.get("spots") or []
    spot = spots[0] if spots and isinstance(spots[0], dict) else {}
    hits = [_at_hit(h) for h in results.get("hits") or [] if isinstance(h, dict)]
    total = _as_int(results.get("totalHits")) or 0
    total_pages = _as_int(pagination.get("totalPages"))
    if total == 0:
        total_pages = 0
    page_index = _as_int(pagination.get("pageIndex"))
    return {
        "results": hits,
        "place": {"id": _clean(spot.get("id")), "name": _clean(spot.get("label")), "type": _clean(spot.get("type"))}
        if spot else None,
        "canonical_path": _clean(payload.get("URL")),
        "is_exact_match": bool(payload.get("exactMatch")) if "exactMatch" in payload else None,
        "pagination": {
            "page": (page_index + 1) if page_index is not None and hits else page,
            "items_per_page": refs.AT_PAGE_SIZE,
            "total_pages": total_pages if total_pages is not None else 0,
            "total_count": total,
        },
    }


# ---- Austria: expose -----------------------------------------------------------------

def _apollo_state(html):
    """The page's window.__APOLLO_STATE__ object (JS `undefined` -> null)."""
    match = _APOLLO_RE.search(html or "")
    if not match:
        return None
    raw = html[match.end():]
    raw = re.sub(r":\s*undefined\b", ": null", raw)
    try:
        state, _ = json.JSONDecoder().raw_decode(raw)
    except ValueError:
        return None
    return state if isinstance(state, dict) else None


def _augmented(value):
    """{label, value} rows -> the label (what the site prints)."""
    if isinstance(value, dict):
        return _clean(value.get("label") or value.get("value"))
    return _clean(value)


def _augmented_list(values):
    return [_augmented(v) for v in values or [] if _augmented(v)]


def _at_costs(rows):
    out = []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        label = _clean(row.get("label")) or _clean(row.get("text"))
        if not label:
            continue
        out.append({"label": label, "price": _money(row.get("price")) if row.get("price") else None,
                    "note": _clean(row.get("hint"))})
    return out


def parse_at_expose(html, listing_id):
    """An /expose/<id> page -> the listing record; None when the page holds
    no Expose record (the caller maps that to not-found)."""
    state = _apollo_state(html)
    if not state:
        return None
    expose = next((v for k, v in state.items() if k.startswith("Expose:") and isinstance(v, dict)), None)
    if not expose:
        return None
    description = expose.get("description") or {}
    price_info = expose.get("priceInformation") or {}
    prices = price_info.get("prices") or {}
    costs = expose.get("costs") or {}
    contact = expose.get("contact") or {}
    company = contact.get("company") or {}
    localization = expose.get("localization") or {}
    address = localization.get("address") or {}
    info = localization.get("information") or {}
    transit = (localization.get("transit") or {}).get("stops") or []
    condition = expose.get("condition") or {}
    energy = condition.get("energyCertification") or {}
    fitting = expose.get("fitting") or {}
    obj = expose.get("object") or {}
    area = expose.get("area") or {}
    kind = expose.get("type") or {}
    meta = expose.get("meta") or {}
    features = meta.get("features") or {}
    keyfacts = expose.get("keyfacts") or {}
    characteristics = []
    for group in expose.get("characteristics") or []:
        if isinstance(group, dict):
            characteristics.append({
                "group": _clean(group.get("key")),
                "items": [_clean(i.get("text")) for i in group.get("items") or [] if isinstance(i, dict) and _clean(i.get("text"))],
            })
    photos = [{"link": p.get("url"), "caption": _clean(p.get("caption") or p.get("title"))}
              for p in expose.get("pictures") or [] if isinstance(p, dict) and p.get("url")]
    attachments = [{"title": _clean(a.get("title") or a.get("label")), "link": a.get("url")}
                   for a in expose.get("attachments") or [] if isinstance(a, dict) and a.get("url")]
    # the same tokens the list rows carry (new, balcony, free_of_commission…)
    badges = [str(b.get("value")).lower() for b in features.get("badges") or []
              if isinstance(b, dict) and b.get("value")]
    awards = [name for name, flag in (
        ("premium_partner_2023", features.get("premiumPartnerAward2023")),
        ("sales_professional", features.get("salesProfessionalAward")),
        ("immo_expert_three_stars", features.get("immoExpertThreeStarsAward")),
        ("immo_expert_five_stars", features.get("immoExpertFiveStarsAward")),
        ("realtor_gold", features.get("realtorBadgeGold")),
        ("realtor_silver", features.get("realtorBadgeSilver")),
        ("realtor_bronze", features.get("realtorBadgeBronze")),
    ) if flag]
    reduction = price_info.get("priceReduction")
    expose_id = _clean(expose.get("id")) or listing_id
    return {
        "id": expose_id,
        "link": refs.listing_link("at", expose_id),
        "title": _clean(description.get("title")),
        "type": refs.at_type_label(kind.get("estateType"), kind.get("transferType")),
        "detail_type": _clean(kind.get("estateDetailType")),
        "use_type": (_clean(kind.get("useType")) or "").lower() or None,
        "is_private": bool(meta.get("privateInsertion")) if "privateInsertion" in meta else None,
        "is_project": bool(meta.get("hasChildren")) if "hasChildren" in meta else None,
        "parent_id": _clean(meta.get("parentId")),
        "is_social_housing": bool(kind.get("isSocialHousing")) if kind.get("isSocialHousing") is not None else None,
        "is_cooperative_housing": bool(expose.get("isCooperativeHousing")) if expose.get("isCooperativeHousing") is not None else None,
        "badges": badges,
        "price": {
            "amount": _as_float(price_info.get("primaryPrice")),
            "currency": "EUR",
            "label": _clean(price_info.get("primaryPriceLabel")),
            "prefix": _clean(price_info.get("pricePrefix")),
            "purchase_price": _as_float(prices.get("buy")),
            "main_rent": _as_float(prices.get("mainRent")),
            "total_rent": _as_float(prices.get("totalRent")),
            "per_m2": _as_float(prices.get("rentPerSquareMeter") if prices.get("rentPerSquareMeter") is not None else prices.get("buyPerSquareMeter")),
            "has_commission": price_info.get("hasCommission") if isinstance(price_info.get("hasCommission"), bool) else None,
            "commission_note": _clean(price_info.get("commissionNote")),
            "reduction": reduction if isinstance(reduction, (dict, str, int, float)) else None,
            "one_time_costs": _at_costs(costs.get("oneTime")),
            "running_costs": _at_costs(costs.get("running")),
        },
        "key_facts": [_clean(k) for k in keyfacts.get("base") or [] if _clean(k)],
        "quick_info": [{"label": _clean(q.get("label")), "value": _clean(q.get("value"))}
                       for q in keyfacts.get("quickInfo") or [] if isinstance(q, dict) and _clean(q.get("value"))],
        "area": {
            "primary_m2": _as_float(area.get("primaryArea")),
            "living_m2": _as_float(area.get("livingArea")),
            "usable_m2": _as_float(area.get("effectiveArea")),
            "total_m2": _as_float(area.get("totalArea")),
            "plot_m2": _as_float(area.get("plotArea")),
            "balcony_m2": _as_float(area.get("balconyArea")),
            "loggia_m2": _as_float(area.get("loggiaArea")),
            "garden_m2": _as_float(area.get("gardenArea")),
            "cellar_m2": _as_float(area.get("cellarArea")),
            "outdoor_spaces": [str(s).lower() for s in area.get("outdoorSpaces") or []],
        },
        "rooms": _as_float(area.get("numberOfRooms")),
        "bedrooms": _as_int(area.get("numberOfBedrooms")),
        "balconies": _as_int(area.get("numberOfBalconies")),
        "loggias": _as_int(area.get("numberOfLoggia")),
        "floor": _as_int(info.get("floor")),
        "floors_total": _as_int(info.get("numberOfFloors")),
        "unit_label": _clean(keyfacts.get("flatLabel")),
        "condition": (_clean(condition.get("type")) or "").lower() or None,
        "year_built": _as_int(condition.get("yearOfConstruction")),
        "last_renovation": _as_int(condition.get("lastModification")),
        "heating_types": _augmented_list(condition.get("heatingTypes")),
        "firing_types": _augmented_list(condition.get("firingTypes")),
        "energy": {
            "heating_demand": _as_float(_augmented(energy.get("heatingDemand"))),
            "heating_demand_class": _augmented(energy.get("heatingDemandClass")),
            "efficiency_factor": _as_float(_augmented(energy.get("totalEnergyEfficiencyFactor"))),
            "efficiency_class": _augmented(energy.get("totalEnergyEfficiencyFactorClass")),
            "final_energy_demand": _as_float(_augmented(energy.get("finalEnergyDemand"))),
            "final_energy_class": _augmented(energy.get("finalEnergyDemandClass")),
        },
        "features": {
            "kitchen": [str(k).lower() for k in fitting.get("kitchen") or []],
            "lift": bool(fitting.get("lift")),
            "accessibility": [str(a).lower() for a in fitting.get("accessibility") or []],
            "parking_spaces": _as_int(fitting.get("numberOfParkingSpaces")),
            "category": _clean(fitting.get("category")),
        },
        "characteristics": characteristics,
        "availability": {
            "available_from": _clean(obj.get("availableFrom")),
            "is_rented": obj.get("isRented") if isinstance(obj.get("isRented"), bool) else None,
            "pets_allowed": obj.get("petsAllowed") if isinstance(obj.get("petsAllowed"), bool) else _clean(obj.get("petsAllowed")),
            "rental_period": _clean(obj.get("rentalPeriod")),
            "rental_period_unit": (_clean(obj.get("rentalPeriodType")) or "").lower() or None,
        },
        "description": {
            "text": _strip_html(description.get("descriptionNote")),
            "features": _strip_html(description.get("fittingNote")),
            "location": _strip_html(description.get("locationNote")),
            "other": _strip_html(description.get("miscellaneousNote")),
        },
        "address": {
            "text": _clean(expose.get("addressString")),
            "street": _clean(address.get("street")),
            "house_number": _clean(address.get("streetNumber")),
            "postcode": _clean(address.get("zip")),
            "city": _clean(address.get("city")),
            "country": _clean(address.get("countryCode")),
            "region_codes": localization.get("geoHierarchy") or None,
        },
        "transit": [{
            "stop": _clean(s.get("name")),
            "distance": _clean(s.get("distance")),
            "lines": [{"type": (_clean(l.get("type")) or "").lower() or None, "lines": _clean(l.get("lines"))}
                      for l in s.get("lines") or [] if isinstance(l, dict)],
        } for s in transit if isinstance(s, dict)],
        "photos": photos,
        "photos_count": len(photos),
        "documents": attachments,
        "virtual_tour_link": features.get("virtualTourUrl") or None,
        "video_link": features.get("videoUrl") or None,
        "has_remote_viewing": bool(features.get("remoteViewingAvailable")) if "remoteViewingAvailable" in features else None,
        "agent": {
            "name": _clean(contact.get("fullName")),
            "company": _clean(company.get("name")),
            "id": _clean(meta.get("cwid")),
            "website": company.get("url") or None,
            "logo": features.get("logo") or None,
            "portrait": contact.get("avatar") or None,
            "awards": awards,
            "association_badges": _augmented_list(features.get("realtorAssociationBadges")),
        },
        "phones": [{"label": None, "number": _clean(contact.get("contactPhone"))}] if _clean(contact.get("contactPhone")) else [],
        "popularity_score": _as_float((meta.get("popularity") or {}).get("score")),
        "updated_at": _clean((meta.get("auditing") or {}).get("updatedAt")),
        "project_state": _clean((expose.get("project") or {}).get("state")),
        "is_foreign": bool(expose.get("isForeignExpose")) if expose.get("isForeignExpose") is not None else None,
    }
