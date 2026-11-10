"""The /immoscout24/* endpoint functions (route_glue's route_table calls
them with the schema's loaded kwargs). Every endpoint caches inside through
cache.cached_call keyed on its validated params; listings/details caches ONE
parsed record per (country, id) so a link and an id for the same expose
share a row.

Germany resolves a place through the mobile API's geo autocomplete (a city /
district / quarter / postcode is searched by its geocode, a street by a
radius around it) and pages the app's search API; Austria resolves a place
through the site's own free-text parser (tokenize), asks getURLByParams for
the canonical list path and pages it through getDataByURL.
"""
from urllib.parse import parse_qs, urlencode, urlparse

from cache import cached_call
from immoscout24 import cache_config as ttl
from immoscout24 import parsers, refs
from immoscout24.fetch import (Immoscout24NotFound, at_expose_page, at_search, at_tokenize, at_url_and_total,
                               de_autocomplete, de_expose, de_project, de_search, de_total)

STREET_RADIUS_KM = 1.0       # a street has no searchable geocode; the app searches around it

_DE_RESIDENTIAL = {"apartmentrent", "apartmentbuy", "houserent", "housebuy", "flatshareroom",
                   "shortTermAccommodation", "houseType", "seniorcare", "assistedliving"}
_DE_COMMERCIAL = {"office", "store", "industry", "gastronomy", "specialpurpose"}

_FILTER_KEYS = ("min_price", "max_price", "min_rooms", "max_rooms", "min_area", "max_area", "min_year",
                "min_floor", "features", "pets", "energy_classes", "apartment_types", "house_types",
                "new_build", "private", "exclude_projects", "keyword")


# ---- helpers ------------------------------------------------------------------------

def _num(value):
    """500.0 -> "500", 2.5 -> "2.5" (the APIs take decimal strings)."""
    if value is None:
        return ""
    if float(value) == int(value):
        return str(int(value))
    return str(value)


def _range(low, high):
    if low is None and high is None:
        return None
    return f"{_num(low)}-{_num(high)}"


def _filters(data):
    return {k: data.get(k) for k in _FILTER_KEYS if data.get(k) not in (None, [], "")}


def _country_type(country, type_):
    """The upstream tokens for a public type on one market, or a ValueError
    (-> 400) when that market does not offer it."""
    table = refs.DE_TYPES if country == "de" else refs.AT_TYPES
    if type_ not in table:
        site = "immobilienscout24.de (Germany)" if country == "de" else "immobilienscout24.at (Austria)"
        raise ValueError(f"type={type_} is not offered on {site}.")
    return table[type_]


# ---- Germany ---------------------------------------------------------------------------

def _de_params(type_, filters, sort=None, page=None, page_size=None):
    real_estate_type, price_type = _country_type("de", type_)
    params = {"realestatetype": real_estate_type}
    if price_type:
        params["pricetype"] = price_type
    price = _range(filters.get("min_price"), filters.get("max_price"))
    if price:
        params["price"] = price
    rooms = _range(filters.get("min_rooms"), filters.get("max_rooms"))
    if rooms:
        params["numberofrooms"] = rooms
    area = _range(filters.get("min_area"), filters.get("max_area"))
    if area and real_estate_type in _DE_RESIDENTIAL:
        params["livingspace"] = area
    elif area and real_estate_type in _DE_COMMERCIAL:
        params["netfloorspace"] = area
    if filters.get("min_year"):
        params["constructionyear"] = f"{filters['min_year']}-"
    if filters.get("min_floor"):
        params["floor"] = f"{filters['min_floor']}-"
    equipment = [refs.FEATURES[f][0] for f in filters.get("features") or [] if refs.FEATURES.get(f, (None,))[0]]
    if equipment:
        params["equipment"] = ",".join(equipment)
    if filters.get("pets"):
        params["petsallowedtypes"] = "yes"
    if filters.get("energy_classes"):
        params["energyefficiencyclasses"] = ",".join(refs.ENERGY_CLASSES[c] for c in filters["energy_classes"])
    if filters.get("apartment_types") and real_estate_type.startswith("apartment"):
        params["apartmenttypes"] = ",".join(refs.APARTMENT_TYPES[t] for t in filters["apartment_types"])
    if filters.get("house_types") and real_estate_type.startswith("house"):
        params["buildingtypes"] = ",".join(refs.HOUSE_TYPES[t] for t in filters["house_types"])
    if filters.get("new_build"):
        params["newbuilding"] = "true"
    if filters.get("exclude_projects"):
        params["exclusioncriteria"] = "projectlisting"
    if filters.get("keyword"):
        params["fulltext"] = filters["keyword"]
    if sort and refs.DE_SORTS.get(sort) and refs.DE_SORTS[sort] != "standard":
        params["sorting"] = refs.DE_SORTS[sort]
    if page is not None:
        params["pagenumber"] = page
        params["pagesize"] = page_size
    return params


def _de_place(text):
    """A place name / postcode -> (geo params, the place row) through the
    app's autocomplete: the first region-searchable hit, else a radius
    around the first street hit."""
    rows = parsers.parse_de_autocomplete(de_autocomplete(text))
    if not rows:
        raise Immoscout24NotFound(f"no place on immobilienscout24.de matches {text!r}")
    region = next((r for r in rows if r["search_type"] == "region" and r["id"]), None)
    if region:
        return {"searchType": "region", "geocodes": region["id"]}, region
    first = rows[0]
    if first["latitude"] is None or first["longitude"] is None:
        raise Immoscout24NotFound(f"no searchable place on immobilienscout24.de matches {text!r}")
    return ({"searchType": "radius",
             "geocoordinates": f"{first['latitude']};{first['longitude']};{_num(STREET_RADIUS_KM)}"}, first)


def _de_link_place(slugs):
    """The place segments of a www search link (/Suche/de/<land>/<stadt>
    [/<ortsteil>]) -> geo params: the deepest segment is looked up on its
    own, a hit whose parent names the segment above it wins, and a segment
    the autocomplete does not know falls back to the one above."""
    names = [s.replace("-", " ") for s in slugs if s]
    for depth in range(len(names) - 1, -1, -1):
        # a double-named borough ("friedrichshain-kreuzberg") is unknown to
        # the app's autocomplete, which lists its quarters: try the halves
        candidates = [names[depth]] + ([p for p in names[depth].split(" ") if len(p) > 3]
                                       if " " in names[depth] else [])
        parent = names[depth - 1].lower() if depth > 0 else None
        for candidate in candidates:
            rows = [r for r in parsers.parse_de_autocomplete(de_autocomplete(candidate))
                    if r["search_type"] == "region" and r["id"]]
            if not rows:
                continue
            pick = next((r for r in rows if parent and parent in (r["parent"] or "").lower()), None) or rows[0]
            return {"searchType": "region", "geocodes": pick["id"]}, pick
    raise Immoscout24NotFound(f"no place on immobilienscout24.de matches {'/'.join(slugs)!r}")


def _de_geo(info):
    """The classified query -> (geo params, place row | None)."""
    if info["kind"] == "geocode":
        return {"searchType": "region", "geocodes": info["id"]}, {"id": info["id"], "name": None, "type": None}
    if info["kind"] == "de_link":
        if info.get("coordinates"):
            lat, lon, km = info["coordinates"]
            return {"searchType": "radius", "geocoordinates": f"{lat};{lon};{_num(km)}"}, None
        return _de_link_place(info.get("place_slugs") or [info["place"]])
    return _de_place(info["text"])


def _place_out(row):
    if not row:
        return None
    return {"id": row.get("id"), "name": row.get("name"), "type": row.get("type")}


# ---- Austria ---------------------------------------------------------------------------

def _at_params(type_, filters, sort=None):
    estate, transfer, use = _country_type("at", type_)
    params = {"estateType": estate, "transferType": transfer, "useType": use}
    if filters.get("min_price") is not None:
        params["primaryPriceFrom"] = _num(filters["min_price"])
    if filters.get("max_price") is not None:
        params["primaryPriceTo"] = _num(filters["max_price"])
    if filters.get("min_rooms") is not None:
        params["numberOfRoomsFrom"] = _num(filters["min_rooms"])
    if filters.get("max_rooms") is not None:
        params["numberOfRoomsTo"] = _num(filters["max_rooms"])
    if filters.get("min_area") is not None:
        params["primaryAreaFrom"] = _num(filters["min_area"])
    if filters.get("max_area") is not None:
        params["primaryAreaTo"] = _num(filters["max_area"])
    if filters.get("keyword"):
        params["keywords"] = filters["keyword"]
    if filters.get("new_build"):
        params["conditionAge"] = "NEW_BUILDING"
    if filters.get("private"):
        params["isPrivateInsertion"] = "true"
    outdoor = []
    for feature in filters.get("features") or []:
        mapping = refs.FEATURES.get(feature, (None, None))[1]
        if not mapping:
            continue
        field, value = mapping
        if field == "outdoorSpaces":
            outdoor.append(value)
        else:
            params[field] = value
    if outdoor:
        params["outdoorSpaces"] = ",".join(outdoor)
    if sort and refs.AT_SORTS.get(sort):
        params["sort"] = refs.AT_SORTS[sort]
    return params


def _at_place(text):
    """A place name / postcode -> ({"region": id} | {"zipCode": plz}, place row)
    through the site's free-text parser."""
    parsed = parsers.parse_at_tokenize(at_tokenize(text))
    rows = parsed["locations"]
    if not rows:
        raise Immoscout24NotFound(f"no place on immobilienscout24.at matches {text!r}")
    row = rows[0]
    key = "zipCode" if row["search_type"] == "postcode" else "region"
    return {key: row["id"]}, row


def _at_paged_path(path, page, extra_query=None):
    """"/regional/wien/wien/wohnung-mieten?primaryPriceTo=900" + page 3 ->
    "/regional/wien/wien/wohnung-mieten/seite-3?primaryPriceTo=900"."""
    parsed = urlparse(path)
    base = parsed.path.rstrip("/")
    query = {k: v[-1] for k, v in parse_qs(parsed.query).items()}
    query.update(extra_query or {})
    if page and page > 1:
        base += f"/seite-{page}"
    return base + ("?" + urlencode(query) if query else "")


def _strip_page(path):
    parsed = urlparse(path or "")
    return refs._AT_PAGE_RE.sub("", parsed.path.rstrip("/"))


# ---- listings/search -----------------------------------------------------------------

def _listings_search(query, country, type, sort, page, page_size, **filters):
    info = refs.classify_query(query, country)
    country = info["country"]
    filters = _filters(filters)
    if info["kind"] in ("de_link", "at_link"):
        # the link's own filters / type / page apply where the request is silent
        for key, value in (info.get("filters") or {}).items():
            filters.setdefault(key, value)
        if info.get("type"):
            type = info["type"]
        if info.get("page") and page == 1:
            page = info["page"]
    out = {"query": query, "country": country, "type": type, "place": None}

    if country == "de":
        geo, place = _de_geo(info)
        params = _de_params(type, filters, sort, page, page_size)
        params.update(geo)
        parsed = parsers.parse_de_search(de_search(params), page, page_size, fallback_type=type)
        out["place"] = _place_out(place)
        out["results"], out["pagination"] = parsed["results"], parsed["pagination"]
        return out

    # Austria
    if info["kind"] == "at_link":
        extra = {k: v for k, v in _at_params(type, filters, sort).items()
                 if k not in ("estateType", "transferType", "useType")}
        path = _at_paged_path(info["path"] + ("?" + urlencode(info["query"]) if info.get("query") else ""), page, extra)
        requested = _strip_page(info["path"])
        place = None
    else:
        params = _at_params(type, filters, sort)
        if info["kind"] == "geocode":
            params["region"], place = info["id"], {"id": info["id"], "name": None, "type": None}
        else:
            where, place = _at_place(info["text"])
            params.update(where)
        canonical, _ = at_url_and_total(params)
        if not canonical:
            raise Immoscout24NotFound(f"immobilienscout24.at has no list page for {query!r}")
        path = _at_paged_path(canonical, page)
        requested = _strip_page(canonical)
    parsed = parsers.parse_at_search(at_search(path), page)
    if parsed["is_exact_match"] is False and _strip_page(parsed["canonical_path"]) != requested \
            and parsed["pagination"]["total_count"] == 0 and page == 1:
        raise Immoscout24NotFound(f"immobilienscout24.at knows no place for {query!r}")
    out["place"] = _place_out(place) or parsed["place"]
    out["link"] = refs.SITES["at"] + path
    out["results"], out["pagination"] = parsed["results"], parsed["pagination"]
    return out


def listings_search(**data):
    """Search homes and commercial property for rent or sale in a German or
    Austrian place: a place name, a postcode, a location id or a pasted
    ImmoScout24 search link, with price, rooms, area, feature, energy-class
    and property-type filters and sorting. Germany pages 1-100 rows, Austria
    25 rows (100 pages at most)."""
    return cached_call("immoscout24.search", data, _listings_search, ttl.SEARCH_CACHE)


# ---- listings/search_by_coordinates --------------------------------------------------

def _listings_search_by_coordinates(latitude, longitude, radius_km, type, sort, page, page_size, **filters):
    params = _de_params(type, _filters(filters), sort, page, page_size)
    params.update({"searchType": "radius", "geocoordinates": f"{latitude};{longitude};{_num(radius_km)}"})
    parsed = parsers.parse_de_search(de_search(params), page, page_size, fallback_type=type)
    return {
        "country": "de",
        "type": type,
        "centre": {"latitude": latitude, "longitude": longitude, "radius_km": radius_km},
        "results": parsed["results"],
        "pagination": parsed["pagination"],
    }


def listings_search_by_coordinates(**data):
    """Search German listings within a radius (km) of a latitude / longitude,
    with the same filters, sorting and paging as listings/search."""
    return cached_call("immoscout24.search_radius", data, _listings_search_by_coordinates, ttl.SEARCH_CACHE)


# ---- listings/count --------------------------------------------------------------------

def _listings_count(query, country, type, **filters):
    info = refs.classify_query(query, country)
    country = info["country"]
    filters = _filters(filters)
    if info["kind"] in ("de_link", "at_link"):
        for key, value in (info.get("filters") or {}).items():
            filters.setdefault(key, value)
        if info.get("type"):
            type = info["type"]
    out = {"query": query, "country": country, "type": type, "place": None}
    if country == "de":
        geo, place = _de_geo(info)
        params = _de_params(type, filters)
        params.update(geo)
        totals = parsers.parse_de_total(de_total(params))
        out["place"] = _place_out(place)
        out.update(totals)
        return out
    if info["kind"] == "at_link":
        extra = {k: v for k, v in _at_params(type, filters).items() if k not in ("estateType", "transferType", "useType")}
        path = _at_paged_path(info["path"] + ("?" + urlencode(info["query"]) if info.get("query") else ""), 1, extra)
        parsed = parsers.parse_at_search(at_search(path), 1)
        if parsed["is_exact_match"] is False and _strip_page(parsed["canonical_path"]) != _strip_page(info["path"]):
            raise Immoscout24NotFound(f"immobilienscout24.at knows no place for {query!r}")
        out["place"] = parsed["place"]
        out["total"] = parsed["pagination"]["total_count"]
        return out
    params = _at_params(type, filters)
    if info["kind"] == "geocode":
        params["region"], place = info["id"], {"id": info["id"], "name": None, "type": None}
    else:
        where, place = _at_place(info["text"])
        params.update(where)
    _, total = at_url_and_total(params)
    out["place"] = _place_out(place)
    out["total"] = int(total or 0)
    return out


def listings_count(**data):
    """Count the listings that match a place and filters without paging
    through them; Germany also reports the coming-soon count."""
    return cached_call("immoscout24.count", data, _listings_count, ttl.COUNT_CACHE)


# ---- listings/details ------------------------------------------------------------------

def _listing_record(country, id):
    if country == "de":
        return parsers.parse_de_expose(de_expose(id), id)
    record = parsers.parse_at_expose(at_expose_page(id), id)
    if record is None:
        raise Immoscout24NotFound(f"listing {id} not found")
    return record


def listing_details(listing):
    """Everything the site shows on one listing (expose), phones included:
    price and running costs, area, rooms, floor, condition, energy data, the
    full description, every photo, the address with coordinates, the agent
    with phone and imprint, the local price comparison and the sibling units
    of its new-build project. Takes a German or Austrian expose id or link."""
    return cached_call("immoscout24.listing", {"country": listing["country"], "id": listing["id"]},
                       _listing_record, ttl.LISTING_CACHE)


# ---- projects/details ------------------------------------------------------------------

def _project_details(project):
    return parsers.parse_de_project(de_project(project), project)


def project_details(**data):
    """A German new-build project: name, developer, description, address
    with coordinates, photos, brochures, contact phones and every unit it
    currently lists for rent or sale."""
    return cached_call("immoscout24.project", data, _project_details, ttl.PROJECT_CACHE)


# ---- locations/search ------------------------------------------------------------------

def _locations_search(query, country):
    if country == "de":
        rows = parsers.parse_de_autocomplete(de_autocomplete(query))
        return {"query": query, "country": country, "count": len(rows), "results": rows}
    parsed = parsers.parse_at_tokenize(at_tokenize(query))
    return {"query": query, "country": country, "count": len(parsed["locations"]), "results": parsed["locations"],
            "parsed_filters": parsed["filters"] or None, "unmatched": parsed["unmatched"]}


def locations_search(**data):
    """Look up places by name or postcode and get the location ids the
    search endpoints accept: cities, districts, quarters, postcodes and
    streets in Germany; states, cities, districts and postcodes in Austria."""
    return cached_call("immoscout24.locations", data, _locations_search, ttl.LOCATIONS_CACHE)
