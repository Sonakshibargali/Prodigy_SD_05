# ============================================================
# TASK-05: WEB SCRAPING -- E-Commerce Product Scraper
# ============================================================
# Project  : Web Scraping -- Books to Scrape
# Author   : Amit
# Date     : October 2026
# Python   : 3.x
# Website  : https://books.toscrape.com/
# ============================================================
# Description:
#   This program scrapes product information (name, price,
#   rating) from the "Books to Scrape" demo e-commerce website
#   and stores all data in a timestamped CSV file.
#
# Features:
#   - Pagination -- crawls all 50 pages automatically
#   - Duplicate prevention -- tracks seen product names
#   - Data cleaning -- strips whitespace, converts currencies
#   - Retry logic -- retries failed HTTP requests up to 3 times
#   - Logging -- writes detailed logs to scraper.log
#   - Summary -- prints total products, avg price, avg rating
# ============================================================


# ----------------------------------------------------------------
# STEP 1: Import Required Libraries
# ----------------------------------------------------------------

import requests                 # To send HTTP requests and fetch web pages
from bs4 import BeautifulSoup   # To parse and extract data from HTML
import csv                      # To write data into a CSV file
import time                     # To add polite delays between requests
import logging                  # To record events and errors in a log file
import os                       # To create directories
import re                       # To clean price strings with regex
from datetime import datetime   # To add timestamps to file names and records


# ----------------------------------------------------------------
# STEP 2: Configure Logging
# ----------------------------------------------------------------
# Logging helps us keep a record of what the scraper did,
# which pages it visited, and any errors it encountered.
# Logs are saved to 'scraper.log' and also printed on screen.

logging.basicConfig(
    level=logging.INFO,                          # Log INFO and above (WARNING, ERROR)
    format="%(asctime)s  [%(levelname)s]  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.FileHandler("scraper.log", mode="w", encoding="utf-8"),  # Write to file
        logging.StreamHandler()                                           # Print to console
    ]
)

logger = logging.getLogger(__name__)


# ----------------------------------------------------------------
# STEP 3: Define Constants
# ----------------------------------------------------------------
# We put all configurable values at the top so they are easy
# to find and change without touching the main code.

BASE_URL     = "https://books.toscrape.com/catalogue/page-{}.html"
MAX_PAGES    = 50          # The website has exactly 50 pages
DELAY        = 1.0         # Seconds to wait between page requests (be polite!)
MAX_RETRIES  = 3           # How many times to retry a failed request
RETRY_DELAY  = 3           # Seconds to wait before retrying

# Star-rating CSS class -> numeric rating mapping
RATING_MAP = {
    "One":   1,
    "Two":   2,
    "Three": 3,
    "Four":  4,
    "Five":  5,
}

# Headers mimic a real browser so the server doesn't block us
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}


# ----------------------------------------------------------------
# STEP 4: Helper Function -- Fetch a Web Page (with Retries)
# ----------------------------------------------------------------
# This function fetches the HTML of a URL.  If the request
# fails (e.g. due to a temporary network error), it retries
# up to MAX_RETRIES times before giving up.

def fetch_page(url):
    """
    Send a GET request to `url` and return the Response object.
    Retries up to MAX_RETRIES times on failure.
    Returns None if all retries are exhausted.
    """
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = requests.get(url, headers=HEADERS, timeout=15)
            response.raise_for_status()          # Raise an error for 4xx/5xx status codes
            logger.info("Fetched: %s  (attempt %d)", url, attempt)
            return response

        except requests.exceptions.RequestException as error:
            logger.warning("Attempt %d/%d failed for %s: %s", attempt, MAX_RETRIES, url, error)
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_DELAY)           # Wait before retrying
            else:
                logger.error("All %d attempts failed for %s. Skipping.", MAX_RETRIES, url)
                return None


# ----------------------------------------------------------------
# STEP 5: Helper Function -- Parse One Product Card
# ----------------------------------------------------------------
# Each product on the page sits inside an <article> tag with
# class "product_pod".  This function extracts the name,
# price, and rating from one such article tag.

def parse_product(article):
    """
    Extract product name, price, and rating from a single
    <article class="product_pod"> element.

    Returns a dictionary with keys:
        product_name, price_gbp, rating, availability
    Returns None if the product cannot be parsed.
    """
    try:
        # -- Product Name --
        # The full title is stored in the <a> tag's "title" attribute
        # inside the <h3> heading.  We use this because the visible
        # text is often truncated (e.g. "A Light in the ...").
        h3_tag = article.find("h3")
        if h3_tag and h3_tag.find("a"):
            product_name = h3_tag.find("a")["title"].strip()
        else:
            product_name = "N/A"

        # -- Price --
        # The price is inside <p class="price_color"> and looks
        # like "51.77".  We remove the pound sign and convert to float.
        price_tag = article.find("p", class_="price_color")
        if price_tag:
            raw_price = price_tag.get_text(strip=True)
            # Use regex to extract only digits and decimal point
            # This handles any currency symbol regardless of encoding
            price_match = re.search(r"[\d.]+", raw_price)
            if price_match:
                price = float(price_match.group())
            else:
                price = 0.0
        else:
            price = 0.0

        # -- Rating --
        # The rating is encoded as a CSS class on <p class="star-rating Three">.
        # We extract the second class name ("Three") and map it to a number.
        rating_tag = article.find("p", class_="star-rating")
        if rating_tag:
            # Classes list looks like: ['star-rating', 'Three']
            rating_classes = rating_tag.get("class", [])
            # The second class is the rating word
            rating_word = rating_classes[1] if len(rating_classes) > 1 else "Zero"
            rating = RATING_MAP.get(rating_word, 0)
        else:
            rating = 0

        # -- Availability --
        # Availability is inside <p class="instock availability">.
        avail_tag = article.find("p", class_="availability")
        if avail_tag:
            availability = avail_tag.get_text(strip=True)
        else:
            availability = "Unknown"

        return {
            "product_name": product_name,
            "price_gbp":    price,
            "rating":       rating,
            "availability": availability,
        }

    except Exception as error:
        logger.warning("Could not parse a product: %s", error)
        return None


# ----------------------------------------------------------------
# STEP 6: Helper Function -- Scrape One Page
# ----------------------------------------------------------------
# Given a page number, this function fetches the HTML, finds
# all product cards, and returns a list of product dicts.

def scrape_page(page_number, seen_names):
    """
    Scrape all products from a single page.

    Parameters:
        page_number (int): The page to fetch (1-50).
        seen_names  (set): Set of product names already scraped
                           (used to avoid duplicates).

    Returns:
        list[dict]: List of product dictionaries from this page.
    """
    url = BASE_URL.format(page_number)
    response = fetch_page(url)

    if response is None:
        return []       # Could not fetch this page; skip it

    # Parse the HTML with BeautifulSoup using the built-in html.parser
    soup = BeautifulSoup(response.text, "html.parser")

    # Find all product cards on the page
    articles = soup.find_all("article", class_="product_pod")
    logger.info("Page %d: found %d product cards.", page_number, len(articles))

    products = []
    for article in articles:
        product = parse_product(article)

        if product is None:
            continue

        # -- Duplicate Prevention --
        # If we have already seen this product name, skip it.
        if product["product_name"] in seen_names:
            logger.debug("Duplicate skipped: %s", product["product_name"])
            continue

        seen_names.add(product["product_name"])
        products.append(product)

    return products


# ----------------------------------------------------------------
# STEP 7: Helper Function -- Save Products to CSV
# ----------------------------------------------------------------
# This function writes the list of product dictionaries into
# a CSV file.  The filename includes a timestamp so you can
# run the scraper multiple times without overwriting results.

def save_to_csv(products, filename):
    """
    Write a list of product dicts to a CSV file.

    CSV columns:
        Serial No, Product Name, Price (GBP), Rating (1-5),
        Availability, Scraped At
    """
    fieldnames = [
        "serial_no",
        "product_name",
        "price_gbp",
        "rating",
        "availability",
        "scraped_at",
    ]

    scrape_timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    try:
        with open(filename, mode="w", newline="", encoding="utf-8") as csvfile:
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            writer.writeheader()

            for index, product in enumerate(products, start=1):
                writer.writerow({
                    "serial_no":    index,
                    "product_name": product["product_name"],
                    "price_gbp":    product["price_gbp"],
                    "rating":       product["rating"],
                    "availability": product["availability"],
                    "scraped_at":   scrape_timestamp,
                })

        logger.info("CSV saved successfully: %s", filename)

    except IOError as error:
        logger.error("Failed to save CSV: %s", error)


# ----------------------------------------------------------------
# STEP 8: Helper Function -- Print Summary
# ----------------------------------------------------------------
# After scraping, we print a quick summary showing totals,
# averages, and the price range.

def print_summary(products):
    """
    Display a summary of the scraped data in the console.
    """
    total = len(products)

    if total == 0:
        logger.warning("No products were scraped. Nothing to summarise.")
        return

    prices  = [p["price_gbp"] for p in products]
    ratings = [p["rating"]    for p in products]

    avg_price  = sum(prices)  / total
    avg_rating = sum(ratings) / total
    min_price  = min(prices)
    max_price  = max(prices)

    # Count products per rating
    rating_counts = {}
    for r in ratings:
        rating_counts[r] = rating_counts.get(r, 0) + 1

    print()
    print("+------------------------------------------------------+")
    print("|            SCRAPING SUMMARY                          |")
    print("+------------------------------------------------------+")
    print("|  Total Products Scraped  :  %-22d |" % total)
    print("|  Average Price (GBP)     :  GBP %-18.2f |" % avg_price)
    print("|  Min Price (GBP)         :  GBP %-18.2f |" % min_price)
    print("|  Max Price (GBP)         :  GBP %-18.2f |" % max_price)
    print("|  Average Rating (1-5)    :  %-22.2f |" % avg_rating)
    print("+------------------------------------------------------+")
    print("|  Rating Distribution:                                |")

    for star in sorted(rating_counts.keys()):
        count = rating_counts[star]
        stars_str = "*" * star + "." * (5 - star)
        bar = "#" * (count // 5)
        print("|    %s  (%d/5)  :  %-4d %-16s |" % (stars_str, star, count, bar))

    print("+------------------------------------------------------+")

    logger.info("Summary: %d products, avg price GBP %.2f, avg rating %.2f", total, avg_price, avg_rating)


# ----------------------------------------------------------------
# STEP 9: Main Function -- Orchestrate Everything
# ----------------------------------------------------------------
# The main() function ties all the helper functions together:
#   1. Loop through each page (1 to 50)
#   2. Scrape all products on each page
#   3. Save everything to a CSV
#   4. Print a summary

def main():
    """
    Entry point of the scraper.
    Scrapes all pages, saves to CSV, and prints a summary.
    """
    print("=" * 55)
    print("  Books to Scrape -- Web Scraper")
    print("  Target: https://books.toscrape.com/")
    print("=" * 55)
    print()

    logger.info("Scraper started.")
    start_time = time.time()

    all_products = []       # Master list of all scraped products
    seen_names   = set()    # Set to track already-seen product names (for dedup)

    # -- Loop through all pages --
    for page_num in range(1, MAX_PAGES + 1):
        print("  [Page %d/%d] Scraping ..." % (page_num, MAX_PAGES), end="  ")

        page_products = scrape_page(page_num, seen_names)
        all_products.extend(page_products)

        print("OK  Got %d products  (Total so far: %d)" % (len(page_products), len(all_products)))

        # Polite delay between requests to avoid overloading the server
        if page_num < MAX_PAGES:
            time.sleep(DELAY)

    # -- Generate timestamped CSV filename --
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    csv_filename = os.path.join("output", "scraped_books_%s.csv" % timestamp)

    # Create the output directory if it doesn't exist
    os.makedirs("output", exist_ok=True)

    # -- Save to CSV --
    save_to_csv(all_products, csv_filename)

    # -- Print Summary --
    print_summary(all_products)

    # -- Elapsed Time --
    elapsed = time.time() - start_time
    minutes = int(elapsed // 60)
    seconds = elapsed % 60

    print()
    print("  Time taken  : %dm %.1fs" % (minutes, seconds))
    print("  Data saved  : %s" % csv_filename)
    print("  Log file    : scraper.log")
    print()

    logger.info("Scraper finished. %d products saved to %s", len(all_products), csv_filename)


# ----------------------------------------------------------------
# STEP 10: Run the Scraper
# ----------------------------------------------------------------
# The standard Python idiom: only run main() when this file
# is executed directly (not when imported as a module).

if __name__ == "__main__":
    main()
