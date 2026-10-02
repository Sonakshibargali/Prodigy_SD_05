# ============================================================
# WEB SCRAPING DASHBOARD — Flask Backend
# ============================================================
# Serves the dashboard UI and provides API endpoints for:
#   - Starting / stopping the scraper
#   - Streaming live progress via Server-Sent Events (SSE)
#   - Fetching scraped results as JSON
#   - Downloading results as CSV
# ============================================================

import os
import re
import csv
import time
import json
import threading
import logging
from io import StringIO
from datetime import datetime

import requests
from bs4 import BeautifulSoup
from flask import Flask, render_template, jsonify, Response, request, send_file

# ----------------------------------------------------------------
# Flask App Setup
# ----------------------------------------------------------------

app = Flask(__name__, template_folder="templates", static_folder="static")

# ----------------------------------------------------------------
# Scraper Configuration
# ----------------------------------------------------------------

BASE_URL    = "https://books.toscrape.com/catalogue/page-{}.html"
MAX_PAGES   = 50
DELAY       = 1.0
MAX_RETRIES = 3
RETRY_DELAY = 2
GBP_TO_INR  = 110.0       # Approximate GBP to INR conversion rate

RATING_MAP = {
    "One": 1, "Two": 2, "Three": 3, "Four": 4, "Five": 5,
}

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}

# ----------------------------------------------------------------
# Shared State (thread-safe)
# ----------------------------------------------------------------

scraper_state = {
    "status": "idle",          # idle | running | completed | error | stopped
    "current_page": 0,
    "total_pages": MAX_PAGES,
    "products": [],
    "seen_names": set(),
    "progress_events": [],     # list of SSE event dicts
    "start_time": None,
    "elapsed": 0,
    "error_message": "",
    "csv_filename": None,
}

state_lock = threading.Lock()
stop_event = threading.Event()

# ----------------------------------------------------------------
# Scraper Logic (runs in background thread)
# ----------------------------------------------------------------

def fetch_page(url):
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = requests.get(url, headers=HEADERS, timeout=15)
            resp.raise_for_status()
            return resp
        except requests.exceptions.RequestException as e:
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_DELAY)
            else:
                return None


def parse_product(article):
    try:
        h3 = article.find("h3")
        if h3 and h3.find("a"):
            name = h3.find("a")["title"].strip()
            product_url = h3.find("a").get("href", "")
        else:
            name = "N/A"
            product_url = ""

        price_tag = article.find("p", class_="price_color")
        if price_tag:
            raw = price_tag.get_text(strip=True)
            m = re.search(r"[\d.]+", raw)
            price = float(m.group()) if m else 0.0
        else:
            price = 0.0

        rating_tag = article.find("p", class_="star-rating")
        if rating_tag:
            classes = rating_tag.get("class", [])
            word = classes[1] if len(classes) > 1 else "Zero"
            rating = RATING_MAP.get(word, 0)
        else:
            rating = 0

        avail_tag = article.find("p", class_="availability")
        availability = avail_tag.get_text(strip=True) if avail_tag else "Unknown"

        price_inr = round(price * GBP_TO_INR, 2)

        return {
            "product_name": name,
            "product_url":  product_url,
            "price_inr":    price_inr,
            "rating": rating,
            "availability": availability,
        }
    except Exception:
        return None


def push_event(event_type, data):
    """Push a progress event into the shared state."""
    with state_lock:
        scraper_state["progress_events"].append({
            "type": event_type,
            "data": data,
            "timestamp": datetime.now().isoformat(),
        })


def run_scraper():
    """Main scraper loop — runs in a background thread."""
    with state_lock:
        scraper_state["status"] = "running"
        scraper_state["current_page"] = 0
        scraper_state["products"] = []
        scraper_state["seen_names"] = set()
        scraper_state["progress_events"] = []
        scraper_state["start_time"] = time.time()
        scraper_state["error_message"] = ""
        scraper_state["csv_filename"] = None

    stop_event.clear()
    push_event("start", {"message": "Scraper started", "total_pages": MAX_PAGES})

    all_products = []
    seen = set()

    for page_num in range(1, MAX_PAGES + 1):
        if stop_event.is_set():
            push_event("stopped", {"message": "Scraper stopped by user", "page": page_num})
            with state_lock:
                scraper_state["status"] = "stopped"
            break

        url = BASE_URL.format(page_num)
        with state_lock:
            scraper_state["current_page"] = page_num

        push_event("page_start", {"page": page_num, "url": url})

        resp = fetch_page(url)
        if resp is None:
            push_event("page_error", {"page": page_num, "message": "Failed to fetch page"})
            continue

        soup = BeautifulSoup(resp.text, "html.parser")
        articles = soup.find_all("article", class_="product_pod")
        page_products = []

        for article in articles:
            product = parse_product(article)
            if product is None:
                continue
            product_key = product["product_url"] or product["product_name"]
            if product_key in seen:
                continue
            seen.add(product_key)
            page_products.append(product)

        all_products.extend(page_products)

        with state_lock:
            scraper_state["products"] = list(all_products)
            scraper_state["seen_names"] = set(seen)
            scraper_state["elapsed"] = time.time() - scraper_state["start_time"]

        push_event("page_done", {
            "page": page_num,
            "found": len(page_products),
            "total": len(all_products),
            "elapsed": round(time.time() - scraper_state["start_time"], 1),
        })

        if page_num < MAX_PAGES and not stop_event.is_set():
            time.sleep(DELAY)

    # Save CSV
    if all_products:
        os.makedirs("output", exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        csv_path = os.path.join("output", f"scraped_books_{ts}.csv")
        try:
            with open(csv_path, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=[
                    "serial_no", "product_name", "price_inr", "rating", "availability", "scraped_at"
                ])
                writer.writeheader()
                scrape_ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                for i, p in enumerate(all_products, 1):
                    writer.writerow({
                        "serial_no": i,
                        "product_name": p["product_name"],
                        "price_inr": p["price_inr"],
                        "rating": p["rating"],
                        "availability": p["availability"],
                        "scraped_at": scrape_ts,
                    })
            with state_lock:
                scraper_state["csv_filename"] = csv_path
        except IOError:
            pass

    with state_lock:
        if scraper_state["status"] == "running":
            scraper_state["status"] = "completed"
        scraper_state["elapsed"] = time.time() - scraper_state["start_time"]

    push_event("complete", {
        "total": len(all_products),
        "elapsed": round(scraper_state["elapsed"], 1),
        "csv": scraper_state.get("csv_filename", ""),
    })


# ----------------------------------------------------------------
# API Routes
# ----------------------------------------------------------------

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/start", methods=["POST"])
def api_start():
    with state_lock:
        if scraper_state["status"] == "running":
            return jsonify({"error": "Scraper is already running"}), 409

    thread = threading.Thread(target=run_scraper, daemon=True)
    thread.start()
    return jsonify({"message": "Scraper started"})


@app.route("/api/stop", methods=["POST"])
def api_stop():
    with state_lock:
        if scraper_state["status"] != "running":
            return jsonify({"error": "Scraper is not running"}), 409
    stop_event.set()
    return jsonify({"message": "Stop signal sent"})


@app.route("/api/status")
def api_status():
    with state_lock:
        return jsonify({
            "status": scraper_state["status"],
            "current_page": scraper_state["current_page"],
            "total_pages": scraper_state["total_pages"],
            "product_count": len(scraper_state["products"]),
            "elapsed": round(scraper_state["elapsed"], 1),
            "csv_filename": scraper_state["csv_filename"],
        })


@app.route("/api/events")
def api_events():
    """Server-Sent Events stream for live progress."""
    def generate():
        last_index = 0
        while True:
            with state_lock:
                events = scraper_state["progress_events"][last_index:]
                status = scraper_state["status"]
            for ev in events:
                yield f"data: {json.dumps(ev)}\n\n"
                last_index += 1
            if status in ("completed", "stopped", "error", "idle") and not events:
                # Send a final keepalive then close
                yield f"data: {json.dumps({'type': 'end', 'data': {'status': status}})}\n\n"
                break
            time.sleep(0.3)

    return Response(generate(), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.route("/api/results")
def api_results():
    with state_lock:
        products = list(scraper_state["products"])
    return jsonify(products)


@app.route("/api/download")
def api_download():
    with state_lock:
        csv_file = scraper_state.get("csv_filename")
    if csv_file and os.path.exists(csv_file):
        return send_file(csv_file, as_attachment=True)
    return jsonify({"error": "No CSV file available"}), 404


# ----------------------------------------------------------------
# Run
# ----------------------------------------------------------------

if __name__ == "__main__":
    print()
    print("=" * 55)
    print("  Web Scraping Dashboard")
    print("  Open:  http://localhost:5000")
    print("=" * 55)
    print()
    app.run(debug=False, port=5000, threaded=True)
