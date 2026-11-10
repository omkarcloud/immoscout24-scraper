"""Offline tests for the /immoscout24/* request schemas and the api's
parameter builders.

    python -m pytest immoscout24/test_schemas.py -q
"""
import os
import sys

import pytest
from marshmallow import ValidationError

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from immoscout24 import api, refs, schemas  # noqa: E402


def test_literal_defaults_match_refs():
    for schema in (schemas.ListingsSearchSchema, schemas.ListingsCountSchema, schemas.LocationsSearchSchema):
        assert schema().fields["country"].load_default == refs.DEFAULT_COUNTRY
    for schema in (schemas.ListingsSearchSchema, schemas.ListingsSearchByCoordinatesSchema, schemas.ListingsCountSchema):
        assert schema().fields["type"].load_default == refs.DEFAULT_TYPE


def test_search_schema_defaults():
    loaded = schemas.ListingsSearchSchema().load({"query": " Berlin Mitte "})
    assert loaded["query"] == "Berlin Mitte"
    assert loaded["country"] == "de" and loaded["type"] == "apartment_rent"
    assert loaded["sort"] == "default" and loaded["page"] == 1 and loaded["page_size"] == 20
    assert loaded["features"] is None and loaded["pets"] is None


def test_search_schema_filters():
    loaded = schemas.ListingsSearchSchema().load({
        "query": "1276003001", "country": "DE", "type": "House_Buy", "min_price": "100000", "max_price": "500000",
        "min_rooms": "2.5", "max_area": "150", "min_year": "1990", "features": "Balcony, lift,balcony",
        "pets": "yes", "energy_classes": "A_PLUS,b", "house_types": "villa,bungalow", "new_build": "1",
        "exclude_projects": "true", "keyword": "garten", "sort": "Price_Asc", "page": "3", "page_size": "100"})
    assert loaded["type"] == "house_buy" and loaded["country"] == "de"
    assert loaded["min_price"] == 100000.0 and loaded["max_price"] == 500000.0
    assert loaded["min_rooms"] == 2.5 and loaded["max_area"] == 150.0 and loaded["min_year"] == 1990
    assert loaded["features"] == ["balcony", "lift"]
    assert loaded["pets"] is True and loaded["energy_classes"] == ["a_plus", "b"]
    assert loaded["house_types"] == ["villa", "bungalow"]
    assert loaded["new_build"] is True and loaded["exclude_projects"] is True
    assert loaded["sort"] == "price_asc" and loaded["page"] == 3 and loaded["page_size"] == 100


@pytest.mark.parametrize("params,field", [
    ({}, "query"),
    ({"query": "Berlin", "type": "castle"}, "type"),
    ({"query": "Berlin", "country": "ch"}, "country"),
    ({"query": "Berlin", "sort": "random"}, "sort"),
    ({"query": "Berlin", "page_size": "101"}, "page_size"),
    ({"query": "Berlin", "page": "0"}, "page"),
    ({"query": "Berlin", "features": "pool"}, "features"),
    ({"query": "Berlin", "energy_classes": "z"}, "energy_classes"),
    ({"query": "Berlin", "min_price": "-5"}, "min_price"),
    ({"query": "Berlin", "pets": "maybe"}, "pets"),
    ({"query": "https://www.immoscout24.ch/de/wohnung/mieten/ort-zuerich"}, "query"),
    ({"query": "https://example.com/Suche/de/berlin"}, "query"),
    ({"query": "https://www.immobilienscout24.de/Suche/shape/wohnung-mieten?shape=x"}, "query"),
    ({"query": "Berlin", "url": "x"}, "url"),
])
def test_search_schema_rejects(params, field):
    with pytest.raises(ValidationError) as err:
        schemas.ListingsSearchSchema().load(params)
    assert field in err.value.messages


def test_search_schema_accepts_links_of_both_sites():
    de = schemas.ListingsSearchSchema().load({"query": "https://www.immobilienscout24.de/Suche/de/berlin/berlin/wohnung-mieten?price=-900"})
    assert de["query"].startswith("https://www.immobilienscout24.de/")
    at = schemas.ListingsSearchSchema().load({"query": "https://www.immobilienscout24.at/regional/wien/wien/wohnung-mieten/seite-2", "country": "de"})
    assert at["country"] == "de"   # the link overrides it in api.py


def test_coordinates_schema():
    loaded = schemas.ListingsSearchByCoordinatesSchema().load({"latitude": "52.52", "longitude": "13.40"})
    assert loaded["latitude"] == 52.52 and loaded["longitude"] == 13.4 and loaded["radius_km"] == 5.0
    assert loaded["type"] == "apartment_rent"
    for bad in ({"latitude": "52.52"}, {"latitude": "95", "longitude": "1"}, {"latitude": "1", "longitude": "1", "radius_km": "500"},
                {"latitude": "48.2", "longitude": "16.3", "type": "hotel_buy"}):
        with pytest.raises(ValidationError):
            schemas.ListingsSearchByCoordinatesSchema().load(bad)


def test_count_schema_has_no_paging():
    loaded = schemas.ListingsCountSchema().load({"query": "Graz", "country": "at", "type": "house_buy"})
    assert loaded["country"] == "at" and "page" not in loaded
    with pytest.raises(ValidationError):
        schemas.ListingsCountSchema().load({"query": "Graz", "page": "2"})


def test_listing_schema_accepts_ids_and_links():
    assert schemas.ListingSchema().load({"listing": "164121861"}) == {"listing": {"country": "de", "id": "164121861"}}
    assert schemas.ListingSchema().load({"listing": "https://www.immobilienscout24.de/expose/164121861"}) == \
        {"listing": {"country": "de", "id": "164121861"}}
    assert schemas.ListingSchema().load({"listing": "6221DAADE5CACEA45C023057"}) == \
        {"listing": {"country": "at", "id": "6221daade5cacea45c023057"}}
    assert schemas.ListingSchema().load({"listing": "https://www.immobilienscout24.at/expose/6221daade5cacea45c023057?x=1"}) == \
        {"listing": {"country": "at", "id": "6221daade5cacea45c023057"}}


@pytest.mark.parametrize("value", ["", "abc", "https://www.immoscout24.ch/mieten/4001", "https://example.com/expose/164121861"])
def test_listing_schema_rejects(value):
    with pytest.raises(ValidationError) as err:
        schemas.ListingSchema().load({"listing": value})
    assert "listing" in err.value.messages


def test_listing_schema_rejects_sibling_params():
    with pytest.raises(ValidationError):
        schemas.ListingSchema().load({"listing": "164121861", "id": "164121861"})


def test_project_schema():
    assert schemas.ProjectSchema().load({"project": "143514"}) == {"project": "143514"}
    assert schemas.ProjectSchema().load({"project": "is24://project/143514"}) == {"project": "143514"}
    with pytest.raises(ValidationError):
        schemas.ProjectSchema().load({"project": "momento"})
    with pytest.raises(ValidationError):
        schemas.ProjectSchema().load({})


def test_locations_schema():
    assert schemas.LocationsSearchSchema().load({"query": "graz", "country": "AT"}) == {"query": "graz", "country": "at"}
    assert schemas.LocationsSearchSchema().load({"query": "10115"})["country"] == "de"
    with pytest.raises(ValidationError):
        schemas.LocationsSearchSchema().load({"query": ""})


# ---- api parameter builders (no network) -----------------------------------------------

def test_commercial_rent_price_types_are_the_ones_the_api_accepts():
    # verified against /search/total on 2026-11-10: rentpermonth is a 412 for both
    assert api._de_params("gastronomy_rent", {}) == {"realestatetype": "gastronomy", "pricetype": "lease"}
    assert api._de_params("commercial_plot_rent", {}) == {"realestatetype": "tradesite", "pricetype": "rent"}
    assert api._de_params("office_rent", {})["pricetype"] == "rentpermonth"


def test_sorts_put_the_biggest_first_and_furnished_is_austria_only():
    assert api._de_params("apartment_rent", {}, sort="area")["sorting"] == "-livingspace"
    assert api._de_params("apartment_rent", {}, sort="rooms")["sorting"] == "-rooms"
    assert api._at_params("apartment_rent", {}, sort="area")["sort"] == "AREA_DESC"
    assert "equipment" not in api._de_params("apartment_rent", {"features": ["furnished"]})
    assert api._at_params("apartment_rent", {"features": ["furnished"]})["furnishing"] == "FURNISHED_FULL"


def test_de_params_residential():
    params = api._de_params("apartment_rent", {"min_price": 500.0, "max_price": 900.0, "min_rooms": 2.5, "min_area": 50.0,
                                               "min_year": 1990, "features": ["balcony", "lift", "terrace"], "pets": True,
                                               "energy_classes": ["a_plus"], "apartment_types": ["penthouse"],
                                               "new_build": True, "exclude_projects": True, "keyword": "altbau"},
                            sort="newest", page=2, page_size=50)
    assert params == {"realestatetype": "apartmentrent", "price": "500-900", "numberofrooms": "2.5-", "livingspace": "50-",
                      "constructionyear": "1990-", "equipment": "balcony,lift", "petsallowedtypes": "yes",
                      "energyefficiencyclasses": "a_plus", "apartmenttypes": "penthouse", "newbuilding": "true",
                      "exclusioncriteria": "projectlisting", "fulltext": "altbau", "sorting": "-firstactivation",
                      "pagenumber": 2, "pagesize": 50}


def test_de_params_commercial_and_houses():
    assert api._de_params("office_rent", {"min_area": 100.0}) == {"realestatetype": "office", "pricetype": "rentpermonth",
                                                                   "netfloorspace": "100-"}
    assert api._de_params("office_buy", {}) == {"realestatetype": "office", "pricetype": "buy"}
    assert api._de_params("house_buy", {"house_types": ["villa"], "apartment_types": ["loft"]}) == \
        {"realestatetype": "housebuy", "buildingtypes": "villa"}
    assert api._de_params("plot_buy", {"min_area": 100.0}) == {"realestatetype": "livingbuysite"}   # no area filter on plots
    with pytest.raises(ValueError):
        api._de_params("hotel_buy", {})


def test_at_params():
    params = api._at_params("house_buy", {"min_price": 100000.0, "max_price": 500000.5, "min_rooms": 3.0, "max_area": 200.0,
                                          "features": ["balcony", "garden", "lift", "cellar"], "new_build": True,
                                          "private": True, "keyword": "pool"}, sort="price_desc")
    assert params == {"estateType": "HOUSE", "transferType": "BUY", "useType": "RESIDENTIAL", "primaryPriceFrom": "100000",
                      "primaryPriceTo": "500000.5", "numberOfRoomsFrom": "3", "primaryAreaTo": "200", "keywords": "pool",
                      "conditionAge": "NEW_BUILDING", "isPrivateInsertion": "true", "outdoorSpaces": "BALCONY,GARDEN",
                      "lift": "true", "sort": "PRICE_DESC"}
    assert api._at_params("short_term_rent", {}) == {"estateType": "APARTMENT", "transferType": "TEMPORARY_RENT",
                                                      "useType": "RESIDENTIAL"}
    with pytest.raises(ValueError):
        api._at_params("prefab_house", {})


def test_at_paged_path():
    assert api._at_paged_path("/regional/wien/wien/wohnung-mieten?primaryPriceTo=900", 3) == \
        "/regional/wien/wien/wohnung-mieten/seite-3?primaryPriceTo=900"
    assert api._at_paged_path("/regional/wien/wien/wohnung-mieten", 1) == "/regional/wien/wien/wohnung-mieten"
    assert api._at_paged_path("/regional/1010/haus-kaufen", 2, {"numberOfRoomsFrom": "3"}) == \
        "/regional/1010/haus-kaufen/seite-2?numberOfRoomsFrom=3"
    assert api._strip_page("/regional/wien/wien/wohnung-mieten/seite-7?x=1") == "/regional/wien/wien/wohnung-mieten"


def test_every_public_type_builds_on_at_least_one_market():
    for name in refs.TYPES:
        built = False
        for builder in (api._de_params, api._at_params):
            try:
                builder(name, {})
                built = True
            except ValueError:
                pass
        assert built, name
