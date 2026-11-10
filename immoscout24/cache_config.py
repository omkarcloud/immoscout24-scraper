"""Cache TTL per /immoscout24/* endpoint (cache.py, keyed on the validated
params). Listings move fast on both sites (Berlin rentals get a new row every
few minutes), so searches are cached briefly; one listing record is cached
longer because its price / text / photos change rarely and the agent's
phone never. The two details endpoints share ONE cached record per listing
(api._listing_record), so repeated calls for the same expose cost one fetch.
"""
from datetime import timedelta

# A search page: the result order shifts as listings come and go.
SEARCH_CACHE = timedelta(minutes=10)
# Totals move with the same cadence as the search pages.
COUNT_CACHE = timedelta(minutes=10)
# One listing record: price cuts and text edits are rare within a day; a
# removed listing keeps serving from the cache until it expires.
LISTING_CACHE = timedelta(hours=6)
# A new-build project changes when units are added or sold.
PROJECT_CACHE = timedelta(hours=12)
# Place lookups: the geo tree is static.
LOCATIONS_CACHE = timedelta(days=7)
