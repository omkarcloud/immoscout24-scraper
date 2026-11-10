# 🏠 Immoscout24 Scraper

Immoscout24 Scraper is a **free and open-source** scraper that gets you **unlimited** detailed ImmoScout24 property data for free.

## ✨ What Can I Get?

- 🏠 **Full details on 750K+ listings in Germany & Austria** — price & running costs, size, rooms, energy data, every photo, GPS & the agent's phone
- 🔍 **Search Germany & Austria your way** — any city, district, postcode or ImmoScout24 search URL, 17 filters, 33 property types
- 📍 **Search around any point** — every listing within a radius of any GPS point, plus instant listing counts
- 🏗️ **New-build projects** — developer, brochures, phone & every unit for rent or sale

## 🎥 Example: A Full ImmoScout24 Listing

```json
{
  "id": "164121861",
  "link": "https://www.immobilienscout24.de/expose/164121861",
  "title": "2-Zimmer Medium mit exklusiven Gemeinschaftsflächen: Padelplatz, Fitness, Dachterrasse & mehr",
  "type": "apartment_rent",
  "is_new_build": true,
  "price": { "amount": 1589.0, "currency": "EUR", "label": "Kaltmiete", "per_m2": 33.1, "service_charge": 130.0, "heating_costs": 105.0, "total_rent": 1824.0 },
  "area": { "living_m2": 48.0, "usable_m2": null, "plot_m2": null },
  "rooms": 2.0,
  "bedrooms": 1,
  "bathrooms": 1,
  "year_built": 2026,
  "condition": "first_time_use",
  "pets": "yes",
  "features": { "balcony": true, "kitchen": true, "lift": true, "cellar": false },
  "address": { "street": "Buschkrugallee", "house_number": "64", "postcode": "12359", "quarter": "Britz", "city": "Berlin", "latitude": 52.45779, "longitude": 13.4465 },
  "photos": [
    { "caption": "Wohnzimmer", "link": "https://pictures.immobilienscout24.de/listings/75338c90-5f28-47a0-bc94-3accb0584a5d-2116079451.png/ORIG/resize/1500x1000/format/webp/quality/80" }
  ],
  "photos_count": 27,
  "price_comparison": { "unit": "€/m²", "min": 7.1, "max": 39.2, "similar_min": 10.9, "similar_max": 25.6, "this_listing": 33.1, "position_percent": 89.0 },
  "project": { "id": "143514", "units": [{ "id": "164121866", "price": { "amount": 1502.0, "currency": "EUR", "text": "1.502 €" }, "area_m2": 60.0, "rooms": 2.0 }] },
  "agent": { "company": "Momento Berlin", "logo": "https://pictures.immobilienscout24.de/usercontent/62320584-291e-4b14-aac4-4970fabf27be.PNG/ORIG/resize/400x400%3E/format/webp/quality/80" },
  "phones": [{ "label": "Festnetznummer", "number": "+49 30 26475183" }]
}
```

*Trimmed for readability.*

## 🚀 Unlimited Free Immoscout24 Data — Get It in 60 Seconds

1️⃣ Clone and install:
```bash
git clone https://github.com/omkarcloud/immoscout24-scraper
cd immoscout24-scraper
python -m pip install -r requirements.txt
```

2️⃣ Start the API:
```bash
python run.py
```

3️⃣ Get your first data:
```bash
curl "http://localhost:8000/listings/details?listing=164121861"
```

```json
{
  "id": "164121861",
  "title": "2-Zimmer Medium mit exklusiven Gemeinschaftsflächen: Padelplatz, Fitness, Dachterrasse & mehr",
  "type": "apartment_rent",
  "price": { "amount": 1589.0, "currency": "EUR", "label": "Kaltmiete", "per_m2": 33.1, "total_rent": 1824.0 },
  "area": { "living_m2": 48.0, "usable_m2": null, "plot_m2": null },
  "rooms": 2.0,
  "bedrooms": 1,
  "bathrooms": 1,
  "year_built": 2026,
  "address": { "text": "Buschkrugallee 64, 12359 Britz, Berlin", "latitude": 52.45779, "longitude": 13.4465 },
  "photos_count": 27,
  "price_comparison": { "unit": "€/m²", "similar_min": 10.9, "similar_max": 25.6, "this_listing": 33.1 },
  "agent": { "company": "Momento Berlin", "is_verified": false },
  "phones": [{ "label": "Festnetznummer", "number": "+49 30 26475183" }]
}
```

All 6 endpoints are now live at `http://localhost:8000`.

## 📚 Endpoints

6 endpoints cover everything you need.

| Endpoint | Path | Returns |
|---|---|---|
| Listing Details | `/listings/details` | Everything about one listing: price, costs, photos, GPS, agent phone |
| Search Locations | `/locations/search` | Location IDs for any German or Austrian city, district or postcode |
| Search Listings | `/listings/search` | Up to 100 listings per page, 17 filters, 7 sort orders |
| Search by Coordinates | `/listings/search_by_coordinates` | Every listing within a radius of any point, 100 per page |
| Count Listings | `/listings/count` | Instant listing count for any place and filters |
| Project Details | `/projects/details` | A new-build project: developer, brochures, phone and every unit |

## 🔍 Exploring Parameters

The same API is published on RapidAPI, and its playground is the easiest place to try parameters and see raw responses. Once a request looks right, run it locally for **unlimited free** data.

1. [Subscribe to the free plan](https://rapidapi.com/OmkarCloud/api/best-immoscout24-scraper-free-1000-calls/pricing) — 1,000 calls/month, no credit card.
2. [Try the endpoints in the playground](https://rapidapi.com/OmkarCloud/api/best-immoscout24-scraper-free-1000-calls/playground) — every param is pre-filled, so you see real data in one click.
3. Copy the generated code and replace `https://best-immoscout24-scraper-free-1000-calls.p.rapidapi.com` with `http://localhost:8000`. It will now run against your local API.

```python
import requests

# generated by the playground, host swapped for the local API
response = requests.get(
    "http://localhost:8000/listings/details",
    params={"listing": "164121861"},
)
print(response.json())
```

## 💬 Have Questions? We Have Answers.

You're a developer — we know how hard completing a project can be. So we offer full support: just message us and we'll reply ✅ with a solution within 1 working day.

[![Message Us on WhatsApp about Immoscout24 Scraper](https://raw.githubusercontent.com/omkarcloud/assets/master/images/whatsapp-us.png)](https://www.omkar.cloud/l/immoscout24-scraper-github-whatsapp)

[![Ask Us by Email about Immoscout24 Scraper](https://raw.githubusercontent.com/omkarcloud/assets/master/images/ask-on-email.png)](mailto:happy.to.help@omkar.cloud?subject=Help%20with%20Immoscout24%20Scraper%20API&body=I%20need%20help%20using%20the%20Immoscout24%20Scraper%20API.)

## ⚡ Popular Scrapers by Omkar Cloud

- [**Google Maps Scraper (3,100+ GitHub Stars)**](https://github.com/omkarcloud/google-maps-scraper) — type "dentists in New York", get every business as a ready-to-call lead list: phones, emails, websites & reviews. Up to 100K free leads/month.
- [**G2 Scraper**](https://www.omkar.cloud/tools/g2-scraper) — G2 product details, ratings & AI-found contacts
- [**Website Email Contact Scraper**](https://www.omkar.cloud/tools/website-email-contact-scraper) — emails, phones & socials from any website
- [**AliExpress Scraper**](https://www.omkar.cloud/tools/aliexpress-scraper-api) — live product details, SKU variants, stock & shipping
- [**Booking Scraper**](https://www.omkar.cloud/tools/booking-scraper) — Booking.com hotels: prices, ratings, rooms & amenities
- [**Etsy Scraper**](https://www.omkar.cloud/tools/etsy-scraper) — Etsy products: prices, discounts, shops & variations

## ⭐ Love It? [Star It ⭐!](https://github.com/omkarcloud/immoscout24-scraper)

Star the repo ⭐ and become my star hero!

It's just 1 click, but it means the world to me.

[![Star us on GitHub](https://raw.githubusercontent.com/omkarcloud/google-maps-scraper/master/screenshots/star-us.png)](https://github.com/omkarcloud/immoscout24-scraper)
