"""Marshmallow request schemas for every /immoscout24/* route.

ONE param per input (tripadvisor QueryOrIdField convention, never a sibling
`url` / `id` pair):

    query     a place name or postcode ("Berlin Mitte", "10115", "Graz"), a
              location id from locations/search (1276003001 /
              P276-10115-BERLIN for Germany, 009001 for Austria) OR a pasted
              immobilienscout24.de / .at search link (its place, type, filters
              and page are read; params given here win)
    listing   a German expose id, an Austrian expose id (24 hex chars) OR an
              expose link of either site — the id's shape names the country
    project   a German new-build project id OR a link carrying one

`country` picks the market (de = immobilienscout24.de, at =
immobilienscout24.at); a link in `query` overrides it. `type` is the shared
<kind>_<deal> vocabulary of immoscout24/refs.py; a type one market does not
offer is a 400 with the message naming it.
"""
from marshmallow import ValidationError, fields, validate, validates_schema

from schema_fields import (BaseSchema, ChoiceField, CommaListField, Flag, PageField, PageSizeField,
                           PositiveInt, QueryField, RefField, StrippedString)
from immoscout24 import refs

MAX_PAGE = 1000       # the mobile API paged to 249 (Berlin rentals, 20/page) without a cap; .at stops at 100


class ListingRefField(RefField):
    resolver = staticmethod(refs.resolve_listing)


class ProjectRefField(RefField):
    resolver = staticmethod(refs.resolve_project)


class SearchQueryField(QueryField):
    """A place / location id / search link; classified without network, so a
    link of the wrong shape is a 400 here rather than an upstream error."""

    def __init__(self, **kwargs):
        kwargs.setdefault("max_length", 1000)
        super().__init__(**kwargs)

    def _deserialize(self, value, attr, data, **kwargs):
        value = super()._deserialize(value, attr, data, **kwargs)
        if value is None:
            return None
        country = (data or {}).get("country")
        country = str(country).lower() if country else refs.DEFAULT_COUNTRY
        if country not in refs.COUNTRIES:
            country = refs.DEFAULT_COUNTRY
        try:
            refs.classify_query(value, country)
        except ValueError as e:
            raise ValidationError(str(e))
        return value


class Coordinate(fields.Float):
    def __init__(self, low, high, **kwargs):
        kwargs.setdefault("required", True)
        kwargs.setdefault("validate", validate.Range(min=low, max=high))
        super().__init__(**kwargs)


# Defaults are written as literals (= refs.DEFAULT_COUNTRY / DEFAULT_TYPE,
# checked by test_schemas) so the publishing tools can read them.
def _country():
    return ChoiceField(list(refs.COUNTRIES), load_default="de", metadata={
        "description": "market: de (immobilienscout24.de, Germany, default) or at (immobilienscout24.at, Austria); "
                       "a link in `query` overrides it"})


def _type():
    return ChoiceField(refs.TYPES, load_default="apartment_rent", metadata={
        "description": "property type as <kind>_<deal>: apartment_rent (default), apartment_buy, house_rent, "
                       "house_buy, plot_rent, plot_buy, garage_rent, garage_buy, room_rent, short_term_rent, "
                       "office_rent, office_buy, retail_rent, retail_buy, industry_rent, industry_buy, "
                       "gastronomy_rent, gastronomy_buy, special_purpose_rent, special_purpose_buy, "
                       "commercial_plot_rent, commercial_plot_buy, investment_buy, compulsory_auction, "
                       "senior_care, assisted_living, prefab_house (Germany only); hotel_rent, hotel_buy, "
                       "agriculture_rent, agriculture_buy, leisure_rent, leisure_buy (Austria only)"})


def _number(description):
    return fields.Float(load_default=None, validate=validate.Range(min=0), metadata={"description": description})


class _FilterMixin:
    """The search filters shared by listings/search, listings/search_by_coordinates
    and listings/count. Germany supports every one of them; Austria the price,
    rooms, area, keyword, new_build, private, furnished / balcony / garden /
    terrace / loggia / lift features and sort (the rest is ignored there)."""
    min_price = _number("lowest price in EUR (monthly rent or purchase price, by type)")
    max_price = _number("highest price in EUR")
    min_rooms = _number("fewest rooms (2.5 allowed)")
    max_rooms = _number("most rooms")
    min_area = _number("smallest living / floor area in m²")
    max_area = _number("largest living / floor area in m²")
    min_year = PositiveInt(max_value=2100, metadata={"description": "earliest construction year (Germany only)"})
    min_floor = PositiveInt(max_value=200, metadata={"description": "lowest floor (Germany only)"})
    features = CommaListField(allowed=list(refs.FEATURES), upper=False, max_items=12, metadata={
        "description": "comma list of required features: balcony, garden, terrace, loggia, kitchen, lift, cellar, "
                       "parking, guest_toilet, barrier_free, furnished (terrace / loggia / furnished are Austria "
                       "only; kitchen, cellar, parking, guest_toilet, barrier_free are Germany only)"})
    pets = Flag(metadata={"description": "true = only listings that allow pets (Germany only)"})
    energy_classes = CommaListField(allowed=list(refs.ENERGY_CLASSES), upper=False, max_items=9, metadata={
        "description": "comma list of energy efficiency classes: a_plus, a, b, c, d, e, f, g, h (Germany only)"})
    apartment_types = CommaListField(allowed=list(refs.APARTMENT_TYPES), upper=False, max_items=10, metadata={
        "description": "comma list for apartment types: apartment, roof_storey, loft, maisonette, penthouse, "
                       "terraced_flat, ground_floor, raised_ground_floor, half_basement, other (Germany only)"})
    house_types = CommaListField(allowed=list(refs.HOUSE_TYPES), upper=False, max_items=10, metadata={
        "description": "comma list for house types: single_family, mid_terrace, end_terrace, semi_detached, "
                       "multi_family, bungalow, farmhouse, villa, castle, special (Germany only)"})
    new_build = Flag(metadata={"description": "true = new builds only"})
    private = Flag(metadata={"description": "true = private (non-agency) listings only (Austria only)"})
    exclude_projects = Flag(metadata={"description": "true = drop new-build project units (Germany only)"})
    keyword = StrippedString(load_default=None, validate=validate.Length(max=100), metadata={
        "description": "free text the listing must mention (e.g. 'balkon')"})


class ListingsSearchSchema(_FilterMixin, BaseSchema):
    query = SearchQueryField(metadata={
        "description": "place name or postcode ('Berlin Mitte', '10115', 'Graz'), a location id from "
                       "locations/search, or a pasted immobilienscout24.de / .at search link"})
    country = _country()
    type = _type()
    sort = ChoiceField(refs.SORTS, load_default="default", metadata={
        "description": "default, price_asc, price_desc, rooms (most first), area (largest first), newest, oldest "
                       "(Austria: default, price_asc, price_desc, area, newest)"})
    page = PageField(max_page=MAX_PAGE)
    page_size = PageSizeField(default=refs.DE_PAGE_SIZE_DEFAULT, max_size=refs.DE_PAGE_SIZE_MAX, metadata={
        "description": "rows per page, 1-100 (Germany; Austria always serves 25)"})


class ListingsSearchByCoordinatesSchema(_FilterMixin, BaseSchema):
    latitude = Coordinate(low=-90, high=90, metadata={"description": "centre latitude, e.g. 52.52"})
    longitude = Coordinate(low=-180, high=180, metadata={"description": "centre longitude, e.g. 13.40"})
    radius_km = fields.Float(load_default=5.0, validate=validate.Range(min=0.1, max=100), metadata={
        "description": "search radius in km (default 5, max 100)"})
    type = _type()
    sort = ChoiceField(refs.SORTS, load_default="default", metadata={
        "description": "default, price_asc, price_desc, rooms (most first), area (largest first), newest, oldest"})
    page = PageField(max_page=MAX_PAGE)
    page_size = PageSizeField(default=refs.DE_PAGE_SIZE_DEFAULT, max_size=refs.DE_PAGE_SIZE_MAX, metadata={
        "description": "rows per page, 1-100"})

    @validates_schema
    def _germany_only_types(self, data, **kwargs):
        if data.get("type") and data["type"] not in refs.DE_TYPES:
            raise ValidationError(f"type={data['type']} exists only on immobilienscout24.at; the radius search "
                                  "covers Germany.", "type")


class ListingsCountSchema(_FilterMixin, BaseSchema):
    query = SearchQueryField(metadata={
        "description": "place name or postcode, a location id from locations/search, or a pasted search link"})
    country = _country()
    type = _type()


class ListingSchema(BaseSchema):
    listing = ListingRefField(metadata={
        "description": "expose id (164121861 for Germany, a 24-character id for Austria) or an "
                       "immobilienscout24.de / .at expose link"})


class ProjectSchema(BaseSchema):
    project = ProjectRefField(metadata={
        "description": "German new-build project id (from listings/details `project.id`) or a link carrying one"})


class LocationsSearchSchema(BaseSchema):
    query = QueryField(max_length=100, metadata={
        "description": "place name, district or postcode to look up ('berlin mitte', '10115', 'Graz')"})
    country = _country()
