"""Offline tests for the immoscout24 parsers, reference resolvers and value
helpers.

    python -m pytest immoscout24/test_parsers.py -q

Fixtures are real responses captured 2026-11-07 (immoscout24/fixtures/):
the mobile API's search pages (Berlin rentals, a past-the-end page, a
grouped commercial page, a radius house-buy page), totals, geo lookups,
four exposes + a 404, a project + a 410; the Austrian getDataByURL pages,
tokenize lookups, getURLByParams and three expose pages (project, regular
rental, gone). No network.
"""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from immoscout24 import parsers as P, refs  # noqa: E402

FX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")


def fixture(name):
    with open(os.path.join(FX, name), encoding="utf-8") as f:
        return json.load(f) if name.endswith(".json") else f.read()


def at_data(name):
    return fixture(name)["data"]


# ---- helpers ---------------------------------------------------------------------------

@pytest.mark.parametrize("text,expected", [
    ("1.589 €", 1589.0), ("33,10 €/m²", 33.1), ("125,98 m²", 125.98), ("4,5", 4.5), ("ab 350 m²", 350.0),
    ("852.580 €", 852580.0), ("2 Zi.", 2.0), ("1,5 Zi.", 1.5), ("", None), (None, None), ("Nein", None),
    (1589, 1589.0),
])
def test_parse_de_number(text, expected):
    assert P.parse_de_number(text) == expected


def test_money_and_picture_template():
    assert P._money("1.589 €") == {"amount": 1589.0, "currency": "EUR", "text": "1.589 €"}
    assert P._money("48 m²") is None
    assert P._picture("https://x/ORIG/resize/%WIDTH%x%HEIGHT%%3E/format/webp") == \
        "https://x/ORIG/resize/800x600%3E/format/webp"
    assert P._picture(None) is None


def test_imprint_decodes_email_and_phone():
    imprint = P._imprint("is24://imprint?text=Momento%20Berlin%0ABleidenstr.%201%0A60311%20Frankfurt%0A%2B49%20151%2010834568%0Aberlin%40momentoliving.com")
    assert imprint["email"] == "berlin@momentoliving.com"
    assert imprint["phone"] == "+49 151 10834568"
    assert imprint["text"].startswith("Momento Berlin\nBleidenstr. 1")
    assert P._imprint(None) is None


# ---- refs ------------------------------------------------------------------------------

@pytest.mark.parametrize("value,expected", [
    ("164121861", {"country": "de", "id": "164121861"}),
    ("https://www.immobilienscout24.de/expose/164121861?utm=x#top", {"country": "de", "id": "164121861"}),
    ("6221DAADE5CACEA45C023057", {"country": "at", "id": "6221daade5cacea45c023057"}),
    ("https://www.immobilienscout24.at/expose/6221daade5cacea45c023057", {"country": "at", "id": "6221daade5cacea45c023057"}),
    ("//www.immobilienscout24.de/expose/172444800/", {"country": "de", "id": "172444800"}),
])
def test_resolve_listing(value, expected):
    assert refs.resolve_listing(value) == expected


@pytest.mark.parametrize("value", ["", "abc", "12", "https://www.immoscout24.ch/mieten/4001", "https://example.com/expose/164121861",
                                   "https://www.immobilienscout24.de/Suche/de/berlin/berlin/wohnung-mieten"])
def test_resolve_listing_rejects(value):
    with pytest.raises(ValueError):
        refs.resolve_listing(value)


def test_resolve_project():
    assert refs.resolve_project("143514") == "143514"
    assert refs.resolve_project("is24://project/143514") == "143514"
    assert refs.resolve_project("https://www.immobilienscout24.de/neubau/x?projectId=143514") == "143514"
    with pytest.raises(ValueError):
        refs.resolve_project("momento")


def test_parse_de_search_link_region():
    info = refs.parse_de_search_link(
        "https://www.immobilienscout24.de/Suche/de/berlin/berlin/mitte/wohnung-mieten?price=-900&numberofrooms=2.0-"
        "&livingspace=50.0-80.0&equipment=balcony,lift&petsallowedtypes=yes&fulltext=altbau&pagenumber=3")
    assert info["type"] == "apartment_rent"
    assert info["place"] == "berlin mitte"
    assert info["place_slugs"] == ["berlin", "berlin", "mitte"]
    assert info["filters"] == {"max_price": 900.0, "min_rooms": 2.0, "min_area": 50.0, "max_area": 80.0,
                               "features": ["balcony", "lift"], "pets": True, "keyword": "altbau"}
    assert info["page"] == 3


def test_parse_de_search_link_radius_and_new_build():
    info = refs.parse_de_search_link("https://www.immobilienscout24.de/Suche/radius/neubauwohnung-kaufen?geocoordinates=52.52;13.40;3.0")
    assert info["coordinates"] == (52.52, 13.4, 3.0)
    assert info["type"] == "apartment_buy"
    assert info["filters"] == {"new_build": True}
    with pytest.raises(ValueError):
        refs.parse_de_search_link("https://www.immobilienscout24.de/Suche/shape/wohnung-mieten?shape=abc")
    with pytest.raises(ValueError):
        refs.parse_de_search_link("https://www.immobilienscout24.de/expose/1")


def test_parse_at_search_link():
    info = refs.parse_at_search_link("https://www.immobilienscout24.at/regional/wien/wien/wohnung-mieten/seite-2?primaryPriceTo=900")
    assert info == {"path": "/regional/wien/wien/wohnung-mieten", "query": {"primaryPriceTo": "900"}, "page": 2,
                    "type": "apartment_rent"}
    with pytest.raises(ValueError):
        refs.parse_at_search_link("https://www.immobilienscout24.at/expose/6221daade5cacea45c023057")


@pytest.mark.parametrize("value,country,kind", [
    ("Berlin Mitte", "de", "text"), ("10115", "de", "text"), ("1276003001", "de", "geocode"),
    ("p276-10115-berlin", "de", "geocode"), ("009001", "at", "geocode"), ("1010", "at", "text"),
    ("https://www.immobilienscout24.at/regional/wien/wien/wohnung-mieten", "de", "at_link"),
    ("https://www.immobilienscout24.de/Suche/de/berlin/berlin/wohnung-mieten", "at", "de_link"),
])
def test_classify_query(value, country, kind):
    info = refs.classify_query(value, country)
    assert info["kind"] == kind
    if kind.endswith("_link"):
        assert info["country"] == kind[:2]


def test_classify_query_rejects_other_sites():
    with pytest.raises(ValueError):
        refs.classify_query("https://www.immoscout24.ch/de/wohnung/mieten/ort-zuerich", "de")
    with pytest.raises(ValueError):
        refs.classify_query("https://example.com/", "de")


def test_at_type_label():
    assert refs.at_type_label("APARTMENT", "RENT") == "apartment_rent"
    assert refs.at_type_label("APARTMENT", "TEMPORARY_RENT") == "short_term_rent"
    assert refs.at_type_label("HOUSE", "BUY") == "house_buy"
    assert refs.at_type_label(None, "BUY") is None


def test_type_tables_cover_every_public_type():
    assert len(refs.TYPES) == len(set(refs.TYPES))
    assert set(refs.TYPES) == set(refs.DE_TYPES) | set(refs.AT_TYPES)
    assert refs.TYPES[0] == refs.DEFAULT_TYPE
    assert tuple(refs.SORTS) == tuple(refs.DE_SORTS) and set(refs.AT_SORTS) == set(refs.SORTS)
    for name in refs.TYPES:
        assert name in refs.DE_TYPES or name in refs.AT_TYPES
    assert set(refs.DE_TYPE_LABELS.values()) <= set(refs.TYPES) | {"office", "retail", "industry", "gastronomy",
                                                                   "special_purpose", "commercial_plot"}


# ---- Germany: search -------------------------------------------------------------------

@pytest.fixture(scope="module")
def de_search():
    return P.parse_de_search(fixture("de_search_apartmentrent_berlin_p1.json"), 1, 20)


def test_de_search_pagination_and_rows(de_search):
    assert de_search["pagination"] == {"page": 1, "items_per_page": 20, "total_pages": 249, "total_count": 4974}
    assert len(de_search["results"]) == 20
    row = de_search["results"][0]
    assert row["id"] == "141689470"
    assert row["link"] == "https://www.immobilienscout24.de/expose/141689470"
    assert row["type"] == "apartment_rent"
    assert row["price"] == {"amount": 1500.0, "currency": "EUR", "text": "1.500 €"}
    assert row["area_m2"] == 57.0 and row["rooms"] == 2.0
    assert row["address"]["latitude"] == 52.56216 and row["address"]["text"].startswith("Prenzlauer Promenade")
    assert row["is_private"] is True and row["has_contact_paywall"] is True
    assert row["published_ago"] == "vor 7 Minuten"
    assert row["photo"].startswith("https://pictures.immobilienscout24.de/")
    assert "%WIDTH%" not in (row["agency_logo"] or "")


def test_de_search_agency_row(de_search):
    row = next(r for r in de_search["results"] if r["id"] == "172446343")
    assert row["is_private"] is False
    assert row["energy_class"] == "D"
    assert row["agency_logo"].startswith("https://pictures.immobilienscout24.de/usercontent/")
    assert row["badges"] == []


def test_de_search_grouped_commercial_rows_are_flattened():
    parsed = P.parse_de_search(fixture("de_search_office_grouped.json"), 1, 5, fallback_type="office_rent")
    assert parsed["pagination"]["total_count"] == 12386
    assert len(parsed["results"]) > 5
    row = parsed["results"][0]
    assert row["developer"]
    assert row["type"] == "office_rent"
    assert row["price_per_m2"] == 12.45 and row["area_m2"] == 114.0
    assert row["address"]["postcode"] == "12107"
    assert row["agency_logo"]


def test_de_search_past_the_end_is_empty():
    parsed = P.parse_de_search(fixture("de_search_past_end.json"), 9999, 20)
    assert parsed["results"] == []
    assert parsed["pagination"]["page"] == 9999
    assert parsed["pagination"]["total_pages"] == 249


def test_de_search_radius_house_buy():
    parsed = P.parse_de_search(fixture("de_search_radius_housebuy.json"), 1, 10)
    assert parsed["pagination"] == {"page": 1, "items_per_page": 10, "total_pages": 2, "total_count": 17}
    assert parsed["results"][0]["price"]["amount"] == 349000.0
    assert parsed["results"][0]["energy_class"] == "D"


def test_de_search_tolerates_garbage():
    assert P.parse_de_search({}, 1, 20) == {"results": [], "pagination": {"page": 1, "items_per_page": 20,
                                                                           "total_pages": 0, "total_count": 0}}
    assert P.parse_de_search({"resultListItems": [None, {"type": "EXPOSE_RESULT"}, {"item": {"id": 5}}]}, 1, 20)["results"][1]["id"] == "5"


def test_de_total_and_autocomplete():
    assert P.parse_de_total(fixture("de_search_total.json")) == {"total": 4974, "coming_soon": 7236}
    rows = P.parse_de_autocomplete(fixture("de_geo_autocomplete_berlin_mitte.json"))
    assert rows[0] == {"id": "1276003001046", "name": "Mitte", "type": "quarterOrTown", "parent": "Berlin",
                       "latitude": 52.5234, "longitude": 13.41139, "search_type": "region"}
    assert rows[1]["search_type"] == "radius" and rows[1]["type"] == "street"
    postcode = P.parse_de_autocomplete(fixture("de_geo_autocomplete_10115.json"))[0]
    assert postcode["id"] == "P276-10115-BERLIN" and postcode["type"] == "postcode"
    assert P.parse_de_autocomplete(fixture("de_geo_autocomplete_nomatch.json")) == []
    assert P.parse_de_autocomplete(None) == []


# ---- Germany: expose -------------------------------------------------------------------

@pytest.fixture(scope="module")
def rental():
    return P.parse_de_expose(fixture("de_expose_apartmentrent.json"), "164121861")


@pytest.fixture(scope="module")
def private_rental():
    return P.parse_de_expose(fixture("de_expose_private.json"), "172444800")


@pytest.fixture(scope="module")
def house_buy():
    return P.parse_de_expose(fixture("de_expose_housebuy.json"), "166144730")


def test_de_expose_identity_and_price(rental):
    assert rental["id"] == "164121861"
    assert rental["link"] == "https://www.immobilienscout24.de/expose/164121861"
    assert rental["title"].startswith("2-Zimmer Medium")
    assert rental["type"] == "apartment_rent"
    assert rental["publication_state"] == "active"
    price = rental["price"]
    assert price["amount"] == 1589.0 and price["label"] == "Kaltmiete" and price["currency"] == "EUR"
    assert price["per_m2"] == 33.1
    assert price["service_charge"] == 130.0 and price["heating_costs"] == 105.0
    assert price["is_heating_in_service_charge"] is False
    assert price["total_rent"] == 1824.0
    assert price["costs"]["Gesamtmiete"] == "1.824 €"


def test_de_expose_attributes_and_address(rental):
    assert rental["area"]["living_m2"] == 48.0
    assert rental["rooms"] == 2.0 and rental["bedrooms"] == 1 and rental["bathrooms"] == 1
    assert rental["year_built"] == 2026
    assert rental["condition"] == "first_time_use"
    assert rental["pets"] == "yes"
    assert rental["features"]["balcony"] is True and rental["features"]["cellar"] is False
    assert rental["attributes"]["main"]["Balkon/Terrasse"] is True
    assert "SCHUFA-BonitätsCheck" not in rental["attributes"]["main"]   # LINK rows are ads
    address = rental["address"]
    assert address["text"] == "Buschkrugallee 64, 12359 Britz, Berlin"
    assert address["street"] == "Buschkrugallee" and address["house_number"] == "64"
    assert address["postcode"] == "12359" and address["city"] == "Berlin" and address["quarter"] == "Britz"
    assert address["latitude"] == 52.45779 and address["longitude"] == 13.4465


def test_de_expose_media_texts_and_project(rental):
    assert rental["photos_count"] == 27 and len(rental["photos"]) == 27
    assert rental["photos"][0]["link"].endswith("/resize/1500x1000/format/webp/quality/80")
    assert rental["photos"][1]["caption"] == "Wohnzimmer"
    assert rental["description"]["text"].startswith("Kontaktieren Sie uns")
    assert rental["description"]["features"].startswith("Die 2-Zimmer Medium")
    assert rental["description"]["location"] and rental["description"]["other"]
    assert rental["project"]["id"] == "143514"
    assert len(rental["project"]["units"]) == 16
    assert rental["project"]["units"][0] == {
        "id": "164121866", "link": "https://www.immobilienscout24.de/expose/164121866", "title": None,
        "price": {"amount": 1502.0, "currency": "EUR", "text": "1.502 €"}, "area_m2": 60.0, "rooms": 2.0,
        "key_facts": ["1.502 €", "60 m²", "2 Zi."],
        "photo": "https://pictures.immobilienscout24.de/listings/24519106-b081-44d3-bed5-7074d5f3a956-2116149062.png/ORIG/legacy_thumbnail/800x600/format/jpg/quality/50",
        "features": None}
    assert [l["title"] for l in rental["links"]] == ["Virtueller Rundgang Earthy", "Virtueller Rundgang Calm"]


def test_de_expose_agent_phone_and_price_bar(rental):
    agent = rental["agent"]
    assert agent["company"] == "Momento Berlin" and agent["name"] == "Frau Beata Sanders"
    assert agent["profile_link"] == "https://www.immobilienscout24.de/anbieter/momento-berlin/a9298ed300f3907707bc200"
    assert agent["homepage"] == "https://www.momentoliving.com/en/our-locations/berlin/berlin"
    assert agent["imprint"]["email"] == "berlin@momentoliving.com"
    assert agent["address"] == "Buschkrugallee 64, 12359 Berlin"
    assert agent["id"] == "20770133" and agent["is_verified"] is False
    assert rental["phones"] == [{"label": "Festnetznummer", "number": "+49 30 26475183"}]
    assert rental["price_comparison"] == {"unit": "€/m²", "min": 7.1, "max": 39.2, "similar_min": 10.9,
                                          "similar_max": 25.6, "this_listing": 33.1, "position_percent": 89.0}
    assert rental["stats"] == {"views": None, "contact_requests": None, "shortlisted": None, "online_since": None}
    assert rental["badges"] == ["only_on_immoscout"] and rental["is_exclusive"] is True
    assert rental["purchase_costs"] is None


def test_de_expose_private_sparse(private_rental):
    assert private_rental["is_private"] is True
    assert private_rental["agent"]["company"] is None and private_rental["agent"]["name"] == "Herr Yves Haririan"
    assert private_rental["agent"]["imprint"] is None and private_rental["agent"]["profile_link"] is None
    assert private_rental["phones"][0]["number"] == "+49 152 37334462"
    assert private_rental["contact"]["private_offer_window_until"] == "2026-11-10T07:43:02.634+00:00"
    assert private_rental["price"]["deposit"] == "1200"
    assert private_rental["price"]["is_heating_in_service_charge"] is True
    assert private_rental["floor"] == 4 and private_rental["floors_total"] == 5
    assert private_rental["available_from"] == "1.12.2026"
    assert private_rental["address"]["street"] == "Am Carlsgarten"
    assert private_rental["project"] is None
    assert private_rental["badges"] == []


def test_de_expose_house_buy_costs(house_buy):
    assert house_buy["type"] == "house_buy"
    assert house_buy["price"]["amount"] == 852580.0 and house_buy["price"]["label"] == "Kaufpreis"
    assert house_buy["price"]["purchase_price"] == 852580.0 and house_buy["price"]["per_m2"] == 6768.0
    assert house_buy["price"]["has_buyer_commission"] is False
    assert house_buy["area"] == {"living_m2": 125.98, "usable_m2": None, "plot_m2": 17.81}
    assert house_buy["rooms"] == 4.5 and house_buy["house_type"] == "mid_terrace_house"
    assert house_buy["address"]["street"] == "Daumstraße" and house_buy["address"]["house_number"] == "53 – 61"
    costs = house_buy["purchase_costs"]
    assert costs["total"] == 920786.0 and costs["land_transfer_tax"] == {"amount": 51155.0, "percent": 6.0, "text": "51.155 €"}
    assert costs["monthly_rate_text"] == "Finanziere ab 2.926 € / Monat"
    assert house_buy["price_comparison"]["unit"] == "€" and house_buy["price_comparison"]["this_listing"] == 852580.0
    assert house_buy["agent"]["is_verified"] is True and house_buy["agent"]["verification"] == ["Identität verifiziert"]
    assert house_buy["documents"][0]["link"].endswith(".pdf")


def test_de_expose_apartment_buy_parking():
    flat = P.parse_de_expose(fixture("de_expose_apartmentbuy.json"), "172402044")
    assert flat["price"]["parking_price"] == {"amount": 38900.0, "currency": "EUR", "text": "38.900 €"}
    assert flat["features"]["parking"] == "underground_garage" and flat["features"]["parking_spaces"] == 1
    assert flat["available_from"] == "Sofort"
    assert len(flat["links"]) == 5 and flat["documents"][0]["title"].startswith("Pandion Midtown")


def test_de_expose_partial_payloads_never_crash():
    empty = P.parse_de_expose({}, "1")
    assert empty["id"] == "1" and empty["title"] is None and empty["phones"] == [] and empty["photos"] == []
    assert empty["price"]["amount"] is None and empty["agent"]["name"] is None
    weird = P.parse_de_expose({"header": {"id": 7}, "sections": [None, {"type": "MEDIA", "media": [None, {}]},
                                                                 {"type": "ATTRIBUTE_LIST", "attributes": [{"type": "TEXT"}]}]}, "7")
    assert weird["id"] == "7" and weird["photos"][0]["link"] is None
    # no "Provision für Käufer" row: obj_courtage n = no buyer commission
    assert P.parse_de_expose({"adTargetingParameters": {"obj_courtage": "n"}}, "8")["price"]["has_buyer_commission"] is False
    assert P.parse_de_expose({"adTargetingParameters": {"obj_courtage": "y"}}, "8")["price"]["has_buyer_commission"] is True


def test_de_not_found_bodies_hold_no_record():
    body = fixture("de_expose_not_found.json")
    assert "ERROR_RESOURCE_NOT_FOUND" in body["error"]
    assert "not published" in fixture("de_project_not_found.json")["error"]


# ---- Germany: project ------------------------------------------------------------------

def test_de_project():
    project = P.parse_de_project(fixture("de_project.json"), "143514")
    assert project["id"] == "143514" and project["name"] == "Momento Berlin"
    assert project["subtitle"].startswith("Modernes Wohnen")
    assert project["price_text"] == "Kaltmiete 941 € - 1.908 €"
    assert project["address"]["text"] == "Buschkrugallee 64, 12359 Berlin"
    assert project["address"]["latitude"] == 52.45774 and project["address"]["postcode"] == "12359"
    assert project["photos_count"] == 37
    assert project["homepage"] == "https://www.momentoliving.com/de/our-locations/berlin/berlin"
    assert project["documents"][0]["link"].endswith(".pdf")
    assert project["unit_groups"][0]["title"] == "Zur Miete (17)"
    assert project["units_count"] == 17
    unit = project["unit_groups"][0]["units"][0]
    assert unit["id"] == "164121843" and unit["features"] == "Balkon/Terrasse, Einbauküche, Lift"
    assert project["agent"]["name"] == "Beata Sanders" and project["agent"]["imprint"]["email"] == "berlin@momentoliving.com"
    assert project["phones"] == [{"label": None, "number": "+49 30 26475183"}]
    assert project["description"].startswith("Kontaktieren Sie uns")
    assert project["location_description"].startswith("Momento Berlin liegt")
    assert P.parse_de_project({}, "9")["id"] == "9"


# ---- Austria: search -------------------------------------------------------------------

@pytest.fixture(scope="module")
def wien_p2():
    return P.parse_at_search(at_data("at_getdata_wien_p2.json")["getDataByURL"], 2)


def test_at_search_pagination_and_place(wien_p2):
    assert wien_p2["pagination"] == {"page": 2, "items_per_page": 25, "total_pages": 16, "total_count": 389}
    assert wien_p2["place"] == {"id": "009001", "name": "Wien", "type": "city"}
    assert wien_p2["canonical_path"] == "/regional/wien/wien/wohnung-mieten/seite-2?primaryPriceTo=900"
    assert wien_p2["is_exact_match"] is True
    assert len(wien_p2["results"]) == 25


def test_at_search_row(wien_p2):
    row = wien_p2["results"][0]
    assert row["id"] == "6aedbe6fc9369bb8e16b8420"
    assert row["link"] == "https://www.immobilienscout24.at/expose/6aedbe6fc9369bb8e16b8420"
    assert row["type"] == "apartment_rent"
    assert row["price"]["amount"] == 777.16 and row["price"]["text"] == "777,16 €"
    assert row["area_m2"] == 38.19 and row["rooms"] == 1.0
    assert row["address"]["text"] == "Tokiostraße 12, 1220 Wien"
    assert row["address"]["latitude"] == pytest.approx(48.24945, abs=1e-4)
    assert row["address"]["region_codes"] == ["009", "009001", "009001022"]
    assert row["published"] == "2026-11-06T11:48:00.038Z"
    assert row["badges"] == ["new", "parking_generic"]
    assert row["transit"] == [{"lines": "U1", "stop": "Kagran"}]
    assert row["agency"]["company"] == "teamneunzehn-Gruppe" and row["agency"]["id"] == "012.0012000001E3r9Y"
    assert row["photo"].startswith("https://pictures.immobilienscout24.de/")
    assert row["is_private"] is False and row["is_project"] is False


def test_at_search_developer_row(wien_p2):
    row = next(r for r in wien_p2["results"] if r["display_type"] != "REGULAR")
    assert row["is_project"] is True
    assert row["price"]["amount"] is None
    assert row["key_facts"] == ["32,25 – 83,33 m²", "1 – 4 Zi."]


def test_at_search_edge_pages():
    past = P.parse_at_search(at_data("at_getdata_past_end.json")["getDataByURL"], 101)
    assert past["results"] == [] and past["pagination"]["total_count"] == 0 and past["is_exact_match"] is False
    unknown = P.parse_at_search(at_data("at_getdata_unknown_place.json")["getDataByURL"], 1)
    assert unknown["place"]["type"] == "country" and unknown["canonical_path"] == "/regional/oesterreich/wohnung-mieten"
    postcode = P.parse_at_search(at_data("at_getdata_plz_1010.json")["getDataByURL"], 1)
    assert postcode["place"] == {"id": "1010", "name": "1010 Wien", "type": "postcode"}
    assert postcode["pagination"]["total_pages"] == 9
    office = P.parse_at_search(at_data("at_getdata_office_p2.json")["getDataByURL"], 2)
    assert office["results"][0]["type"] == "office_rent"
    assert office["pagination"]["total_pages"] == 100
    assert P.parse_at_search({}, 3)["pagination"] == {"page": 3, "items_per_page": 25, "total_pages": 0, "total_count": 0}


def test_at_tokenize():
    graz = P.parse_at_tokenize(at_data("at_tokenize_graz.json")["tokenize"])
    assert graz["locations"][0] == {"id": "006001", "name": "Graz", "type": "city", "match": "parsed", "search_type": "region"}
    assert graz["locations"][1]["name"] == "Graz-Umgebung"
    assert graz["filters"] == {"countryCode": "AT", "region": "006001"} and graz["unmatched"] == []
    plz = P.parse_at_tokenize(at_data("at_tokenize_1010.json")["tokenize"])
    assert plz["locations"] == [{"id": "1010", "name": "1010 Wien", "type": "postcode", "match": "parsed", "search_type": "postcode"}]
    none = P.parse_at_tokenize(at_data("at_tokenize_nomatch.json")["tokenize"])
    assert none["locations"] == [] and none["unmatched"] == ["zzzqqq"]
    mixed = P.parse_at_tokenize(at_data("at_tokenize_innsbruck_filters.json")["tokenize"])
    assert mixed["locations"][0]["id"] == "007001" and mixed["filters"]["numberOfRoomsFrom"] == "3"
    assert P.parse_at_tokenize(None) == {"locations": [], "filters": {}, "unmatched": []}


def test_at_url_and_total_fixture_shape():
    data = at_data("at_url_and_total.json")
    assert data["getURLByParams"]["URL"].startswith("/regional/1010/haus-kaufen/geringster-preis-zuerst?")
    assert data["getTotalHitsByParams"]["totalHits"] == 0


# ---- Austria: expose -------------------------------------------------------------------

@pytest.fixture(scope="module")
def at_rental():
    return P.parse_at_expose(fixture("at_expose_rent.html"), "6aedbe6fc9369bb8e16b8420")


def test_at_expose_rental(at_rental):
    assert at_rental["id"] == "6aedbe6fc9369bb8e16b8420"
    assert at_rental["link"] == "https://www.immobilienscout24.at/expose/6aedbe6fc9369bb8e16b8420"
    assert at_rental["title"].startswith("All-inclusive wohnen")
    assert at_rental["type"] == "apartment_rent" and at_rental["use_type"] == "residential"
    price = at_rental["price"]
    assert price["amount"] == 777.0 and price["label"] == "Monatliche Kosten" and price["per_m2"] == 20.35
    assert price["has_commission"] is False
    assert price["running_costs"][0] == {"label": "Monatliche Kosten", "price": {"amount": 777.16, "currency": "EUR", "text": "777,16 €"}, "note": None}
    assert price["one_time_costs"][1]["label"] == "Kaution: 3 Bruttomonatsmieten"
    assert at_rental["area"]["living_m2"] == 38.19 and at_rental["rooms"] == 1.0
    assert at_rental["floor"] == 4 and at_rental["floors_total"] == 9 and at_rental["unit_label"] == "Top 414"
    assert at_rental["heating_types"] == ["Zentralheizung", "Fernwärme", "Fußbodenheizung"]
    assert at_rental["energy"] == {"heating_demand": 40.6, "heating_demand_class": "B", "efficiency_factor": 1.05,
                                   "efficiency_class": "C", "final_energy_demand": None, "final_energy_class": None}
    assert at_rental["features"]["kitchen"] == ["open_kitchen"] and at_rental["features"]["lift"] is True
    assert at_rental["availability"] == {"available_from": "ab sofort", "is_rented": False, "pets_allowed": None,
                                         "rental_period": "3", "rental_period_unit": "year"}
    assert at_rental["address"]["street"] == "Tokiostraße" and at_rental["address"]["postcode"] == "1220"
    assert at_rental["transit"][0]["stop"] == "Wien Josef-Baumann-Gasse"
    assert at_rental["transit"][0]["lines"][0] == {"type": "tram", "lines": "25, 26, 27"}
    assert at_rental["photos_count"] == 16 and at_rental["photos"][0]["link"].startswith("https://pictures.")
    assert at_rental["description"]["text"].startswith("Smart wohnen in Bestlage")
    assert "<p>" not in at_rental["description"]["text"] and "<br" not in at_rental["description"]["text"]
    assert "Arzt <250m" in at_rental["description"]["text"]   # a literal "<" in the copy survives tag stripping
    assert at_rental["agent"]["company"] == "teamneunzehn-Gruppe" and at_rental["agent"]["name"] == "Frau Sylwia Zagula"
    assert at_rental["phones"] == [{"label": None, "number": "+43676852243502"}]
    assert at_rental["badges"] == ["free_of_commission", "parking_generic"]
    assert at_rental["quick_info"][1] == {"label": "Befristung", "value": "3 Jahre"}


def test_at_expose_project_sparse():
    project = P.parse_at_expose(fixture("at_expose_project.html"), "6221daade5cacea45c023057")
    assert project["type"] == "apartment_buy" and project["is_project"] is True
    assert project["price"]["amount"] is None and project["price"]["label"] == "Preis auf Anfrage"
    assert project["area"]["outdoor_spaces"] == ["garden", "terrace"]
    assert project["key_facts"] == ["188 m² - 189 m²", "5 - 5 Zimmer", "Garten, Terrasse"]
    assert project["firing_types"] == ["Erdwärme", "Solar"]
    assert project["energy"]["efficiency_class"] == "A+"
    assert project["characteristics"][0]["group"] == "condition"
    assert "Unterkellert" in project["characteristics"][0]["items"]
    assert project["address"]["street"] is None and project["address"]["postcode"] == "1170"
    assert project["agent"]["website"] == "https://www.pkimmobilien.at" and project["agent"]["awards"] == ["realtor_silver"]
    assert project["phones"][0]["number"] == "+436648512133"
    assert project["popularity_score"] == 1.0 and project["updated_at"] == "2026-11-01T03:04:08.008Z"


def test_at_expose_gone_page_has_no_record():
    assert P.parse_at_expose(fixture("at_expose_not_found.html"), "000000000000000000000000") is None
    assert P.parse_at_expose("", "x") is None
    assert P.parse_at_expose("<html>window.__APOLLO_STATE__ = {broken", "x") is None
