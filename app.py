# app.py
from flask import Flask, render_template, request, jsonify
import requests
from dotenv import load_dotenv
import os
import json
import time
from datetime import datetime
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

load_dotenv()

app = Flask(__name__)

# Configuration
USERNAME = os.getenv("AUTOTRADER_USERNAME")
PASSWORD = os.getenv("AUTOTRADER_PASSWORD")
API_URL = os.getenv("API_URL")

# Cache settings
CACHE_FILE = "cache_listings.json"
CACHE_TIMEOUT = 1800  # 30 minutes (in seconds)


class VehicleListingProcessor:
    """Handles processing and formatting of vehicle listings"""
    
    @staticmethod
    def parse_iso_datetime(dt_str):
        """
        Safely parse ISO 8601 datetime string.
        Returns Unix timestamp for sorting.
        """
        try:
            if not dt_str:
                return 0
            
            # Handle different datetime formats
            if dt_str.endswith('Z'):
                dt_str = dt_str[:-1] + '+00:00'
            
            # Fix missing colon in timezone offset
            if '+' in dt_str and len(dt_str.split('+')[-1]) == 4:
                parts = dt_str.split('+')
                dt_str = f"{parts[0]}+{parts[1][:2]}:{parts[1][2:]}"
            
            dt = datetime.fromisoformat(dt_str)
            return dt.timestamp()
        except Exception as e:
            logger.warning(f"Failed to parse datetime: {dt_str} | Error: {e}")
            return 0

    @staticmethod
    def format_price(raw_price_str):
        """Format price string for display and sorting"""
        price_display = "POA"
        price_value_for_sorting = 0

        if not raw_price_str or (isinstance(raw_price_str, str) and 
                                raw_price_str.upper() in ["POA", "ON REQUEST", "PRICE ON APPLICATION", ""]):
            return price_display, price_value_for_sorting

        try:
            if isinstance(raw_price_str, str):
                raw_price_str = raw_price_str.strip()
                parts = raw_price_str.split(',')
                
                if len(parts) == 2:
                    major_part_str = parts[0]
                    minor_part_str = parts[1][:2]
                    major_digits_only = ''.join(filter(str.isdigit, major_part_str))
                    
                    if not major_digits_only:
                        major_digits_only = "0"
                    
                    price_float_str = f"{major_digits_only}.{minor_part_str}"
                    price_value_for_sorting = float(price_float_str)
                    major_int = int(major_digits_only)
                    formatted_major = f"{major_int:,}".replace(',', ' ')
                    price_display = f"R{formatted_major}"
                else:
                    clean_str = ''.join(filter(str.isdigit, raw_price_str))
                    if clean_str:
                        price_value_for_sorting = float(clean_str)
                        price_display = f"R{price_value_for_sorting:,.0f}".replace(',', ' ')
            elif isinstance(raw_price_str, (int, float)):
                price_value_for_sorting = float(raw_price_str)
                price_display = f"R{price_value_for_sorting:,.0f}".replace(',', ' ')
                
        except (ValueError, IndexError, TypeError) as e:
            logger.warning(f"Error parsing price '{raw_price_str}': {e}")

        return price_display, price_value_for_sorting

    @staticmethod
    def format_mileage(mileage):
        """Format mileage with spaces as thousand separators"""
        try:
            mileage_int = int(mileage) if mileage else 0
            return f"{mileage_int:,}".replace(',', ' ')
        except (ValueError, TypeError):
            return "0"

    @staticmethod
    def process_listing(item):
        """Process a single listing item"""
        make = item.get("make", "Unknown").title()
        model = item.get("model", "Model").title()
        year = item.get("year", "N/A")
        location = item.get("location", "South Africa")
        colour = item.get("colour", "Unknown")
        description = item.get("description", "No description available.").replace('\r', '')
        variant = item.get("variant", "")
        body_type = item.get("bodyType", "")
        engine = item.get("engine", "N/A")

        # Price handling
        price_display, price_value_for_sorting = VehicleListingProcessor.format_price(item.get("price", ""))

        # Mileage handling
        formatted_mileage = VehicleListingProcessor.format_mileage(item.get("mileageInKm", 0))

        # Images
        image_urls = item.get("imageUrls", [])
        if not image_urls:
            image_urls = [f"https://source.unsplash.com/random/800x600/?car,{make.lower()}+{model.lower()}"]

        # Created timestamp
        created = item.get("created", "")
        created_timestamp = VehicleListingProcessor.parse_iso_datetime(created) if created else time.time()

        return {
            "id": item.get("id"),
            "make": make,
            "model": model,
            "year": year,
            "price_display": price_display,
            "price": price_value_for_sorting,
            "image_urls": image_urls,
            "variant": variant,
            "body_type": body_type,
            "colour": colour,
            "location": location,
            "mileage": formatted_mileage,
            "description": description,
            "created": created,
            "created_timestamp": created_timestamp,
            "engine": engine
        }


class CacheManager:
    """Handles caching of API data"""
    
    @staticmethod
    def get_listings_from_cache():
        """Read cached data if it exists and is still fresh"""
        if os.path.exists(CACHE_FILE):
            try:
                with open(CACHE_FILE, "r", encoding="utf-8") as f:
                    cache = json.load(f)
                if time.time() - cache["timestamp"] < CACHE_TIMEOUT:
                    logger.info("✅ Using cached API data")
                    return cache["data"]
                else:
                    logger.info("⏳ Cache expired, will fetch fresh data")
            except (json.JSONDecodeError, KeyError) as e:
                logger.warning(f"⚠️ Cache file corrupted or invalid: {e}")
        return None

    @staticmethod
    def save_listings_to_cache(data):
        """Save API response to cache with timestamp"""
        try:
            cache = {
                "timestamp": time.time(),
                "data": data
            }
            with open(CACHE_FILE, "w", encoding="utf-8") as f:
                json.dump(cache, f, indent=2, ensure_ascii=False)
            logger.info("💾 Fresh data saved to cache")
        except Exception as e:
            logger.error(f"❌ Failed to save cache: {e}")


class APIClient:
    """Handles API communication"""
    
    @staticmethod
    def fetch_listings_from_api():
        """Fetch vehicle listings from API"""
        logger.info("📡 Fetching fresh data from API...")
        try:
            response = requests.get(
                API_URL,
                auth=(USERNAME, PASSWORD),
                timeout=10,
                headers={
                    "Accept": "application/json",
                    "User-Agent": "AutoTrader-Client-App/1.0"
                }
            )

            if response.status_code == 200:
                raw_data = response.json()
                
                # Normalize response structure
                if isinstance(raw_data, list):
                    return raw_data
                elif isinstance(raw_data, dict):
                    return raw_data.get("listings", []) or raw_data.get("vehicles", []) or []
                else:
                    return []
            else:
                logger.error(f"❌ API Error {response.status_code}: {response.text}")
                return None
                
        except Exception as e:
            logger.error(f"🚨 Request failed: {e}")
            return None


def fetch_listings():
    """Fetch vehicle listings from API or cache, then sort by 'created' (newest first)"""
    
    # Try to get from cache first
    cached_data = CacheManager.get_listings_from_cache()
    
    if cached_data is not None:
        raw_listings = cached_data
    else:
        # Cache miss — fetch from API
        raw_listings = APIClient.fetch_listings_from_api()
        
        if raw_listings is not None:
            # Save to cache
            CacheManager.save_listings_to_cache(raw_listings)
        elif cached_data is not None:
            # Fallback to stale cache
            logger.warning("⚠️ Using stale cache due to API failure")
            raw_listings = cached_data
        else:
            logger.error("❌ No cache available. Showing empty list.")
            raw_listings = []

    # Process each listing
    listings = [VehicleListingProcessor.process_listing(item) for item in raw_listings]
    
    # Sort by 'created_timestamp' — newest first
    listings.sort(key=lambda x: x["created_timestamp"], reverse=True)
    
    logger.info(f"📦 Total processed & sorted listings: {len(listings)}")
    return listings


@app.route("/")
def home():
    """Home page route — shows top 3 most expensive vehicles"""
    try:
        listings = fetch_listings()
        # Sort by price (descending) — highest price first
        sorted_by_price = sorted(listings, key=lambda x: x.get("price", 0), reverse=True)
        featured_listings = sorted_by_price[:3] if sorted_by_price else []
        return render_template("home.html", featured_listings=featured_listings)
    except Exception as e:
        logger.error(f"Error in home route: {e}")
        return render_template("home.html", featured_listings=[])

@app.route("/inventory")
def inventory():
    """Inventory page route - shows all listings"""
    try:
        listings = fetch_listings()
        return render_template("index.html", listings=listings)
    except Exception as e:
        logger.error(f"Error in inventory route: {e}")
        return render_template("index.html", listings=[])


@app.route("/listing/<int:listing_id>")
def listing_detail(listing_id):
    try:
        # First check if we have the listing in our current listings
        listings = fetch_listings()
        for listing in listings:
            if str(listing.get("id")) == str(listing_id):
                return render_template("listing.html", car=listing)
        
        # If not found, try to fetch directly from API
        raw_listings = APIClient.fetch_listings_from_api()
        if raw_listings:
            for item in raw_listings:
                if str(item.get("id")) == str(listing_id):
                    processed_listing = VehicleListingProcessor.process_listing(item)
                    return render_template("listing.html", car=processed_listing)
                    
    except Exception as e:
        logger.error(f"🚨 Error fetching listing {listing_id}: {e}")
    
    return "Car not found", 404


# Route for about page
@app.route("/about.html")
def about():
    return render_template("about.html")


@app.route("/about")
def about_page():
    return render_template("about.html")


# Add route for finance calculator page
@app.route("/finance")
def finance():
    return render_template("finance.html")


@app.route("/finance.html")
def finance_html():
    return render_template("finance.html")


# Add route for contact page
@app.route("/contact.html")
def contact():
    return render_template("contact.html")


@app.route("/contact")
def contact_page():
    return render_template("contact.html")


# Add route for trade-in page
@app.route("/trade-in")
def trade_in():
    return render_template("trade-in.html")


# Health check endpoint
@app.route("/health")
def health_check():
    return jsonify({"status": "healthy", "timestamp": datetime.now().isoformat()})

# Add route for gallery page
@app.route("/gallery")
def gallery():
    return render_template("gallery.html")

if __name__ == "__main__":
    app.run(debug=True) 


