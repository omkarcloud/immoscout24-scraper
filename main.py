"""Use the scraper straight from Python — no server needed.

    python main.py

Every function returns the same JSON the API does (paged endpoints carry a
`pagination` block instead of next / previous links); results are written
to output/*.json. The schemas fill in every default, exactly as the API does.
"""
import json
import os

from immoscout24 import api, schemas

os.makedirs("output", exist_ok=True)


def save(name, data):
    path = os.path.join("output", name)
    with open(path, "w") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"saved {path}")


def params(schema_cls, **query):
    """Validate a query exactly like the API: defaults filled, links resolved."""
    return schema_cls().load(query)


if __name__ == "__main__":
    # a German or Austrian listing ID, or any immobilienscout24.de / .at listing link
    save("listing_164121861.json", api.listing_details(
        **params(schemas.ListingSchema, listing="164121861")))

    # up to 100 listings per page in Germany; a place name, postcode, location ID or search link
    save("search_berlin.json", api.listings_search(
        **params(schemas.ListingsSearchSchema, query="Berlin", features="balcony", sort="newest")))

    # Austria: 25 listings per page
    save("search_vienna.json", api.listings_search(
        **params(schemas.ListingsSearchSchema, query="Wien", country="at", type="apartment_buy")))
