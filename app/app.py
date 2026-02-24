# app.py — The Flask API for our URL shortener
# This is the "brain" of the operation. It handles two jobs:
#   1. Creating short URLs (generating a code, storing it in the database)
#   2. Redirecting short URLs (looking up the code, sending the browser elsewhere)

import os
import string
import random
from datetime import datetime, timezone

from flask import Flask, request, redirect, jsonify
import psycopg2
from psycopg2.extras import RealDictCursor

# --- App Setup ---
# Flask() creates our web application. __name__ tells Flask where to find things.
app = Flask(__name__)

# --- Configuration ---
# We read database connection details from environment variables.
# These will be set in your docker-compose.yml, NOT hardcoded here.
# This is how real-world apps handle config — the app doesn't know or care
# whether it's running in Docker, on a server, or on your laptop.
DB_HOST = os.environ.get("DB_HOST", "db")          # container name in docker-compose
DB_PORT = os.environ.get("DB_PORT", "5432")         # default PostgreSQL port
DB_NAME = os.environ.get("DB_NAME", "urlshortener") # the database name
DB_USER = os.environ.get("DB_USER", "postgres")     # database username
DB_PASS = os.environ.get("DB_PASS", "postgres")     # database password


def get_db_connection():
    """
    Opens a connection to the PostgreSQL database.

    Think of this like picking up the phone and dialing the database.
    Every time Flask needs to read or write data, it calls this function
    to get a live connection, does its work, then hangs up (closes it).

    RealDictCursor means query results come back as dictionaries like:
      {"short_code": "aB7x", "original_url": "https://..."}
    instead of plain tuples like:
      ("aB7x", "https://...")
    which makes the code much easier to read.
    """
    conn = psycopg2.connect(
        host=DB_HOST,
        port=DB_PORT,
        dbname=DB_NAME,
        user=DB_USER,
        password=DB_PASS,
        cursor_factory=RealDictCursor
    )
    return conn


def init_db():
    """
    Creates the 'urls' table if it doesn't already exist.

    This runs once when the app starts up. It's like setting up the filing
    cabinet before you start filing anything. If the cabinet (table) is
    already there, this does nothing — that's what IF NOT EXISTS means.

    The table has four columns:
      - id:           Auto-incrementing number (PostgreSQL handles this)
      - short_code:   The generated string like 'aB7x' (must be unique)
      - original_url: The long URL the user submitted
      - created_at:   Timestamp of when the link was created
    """
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS urls (
            id SERIAL PRIMARY KEY,
            short_code VARCHAR(10) UNIQUE NOT NULL,
            original_url TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT NOW()
        );
    """)
    conn.commit()  # "commit" means: actually save this change to disk
    cur.close()
    conn.close()


def generate_short_code(length=6):
    """
    Generates a random string of letters and digits.

    Example output: 'aB7xkT'

    string.ascii_letters = 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ'
    string.digits = '0123456789'

    So we're picking 6 random characters from a pool of 62 possible characters.
    That gives us 62^6 = ~56 billion possible combinations, which is plenty
    for a portfolio project. (Bit.ly uses 7 characters for similar reasons.)
    """
    characters = string.ascii_letters + string.digits
    return ''.join(random.choices(characters, k=length))

init_db()
# --- Routes ---

@app.route("/api/shorten", methods=["POST"])
def shorten_url():
    """
    POST /api/shorten
    Expects JSON like: {"url": "https://www.example.com/some/long/path"}
    Returns JSON like: {"short_code": "aB7x", "short_url": "http://localhost/aB7x"}

    This is the "create" endpoint. The frontend sends a long URL here,
    and this function:
      1. Validates that a URL was actually provided
      2. Generates a random short code
      3. Makes sure the code doesn't already exist (astronomically unlikely, but good practice)
      4. Stores the mapping in the database
      5. Sends back the short URL
    """
    # request.get_json() parses the incoming JSON body.
    # If someone sends garbage (not valid JSON), this returns None.
    data = request.get_json()

    if not data or "url" not in data:
        # 400 = "Bad Request" — you sent me something I can't work with
        return jsonify({"error": "Missing 'url' in request body"}), 400

    original_url = data["url"]

    # Strip whitespace — users sometimes accidentally paste URLs with spaces
    original_url = original_url.strip()

    if not original_url:
        return jsonify({"error": "URL cannot be empty"}), 400

    conn = get_db_connection()
    cur = conn.cursor()

    # Generate codes until we get one that's not already in the database.
    # In practice, this loop almost always runs exactly once because the
    # chance of a collision with 62^6 combinations is essentially zero.
    # But defensive coding is a good habit.
    short_code = generate_short_code()
    cur.execute("SELECT id FROM urls WHERE short_code = %s", (short_code,))
    while cur.fetchone() is not None:
        short_code = generate_short_code()
        cur.execute("SELECT id FROM urls WHERE short_code = %s", (short_code,))

    # INSERT the new mapping into the database.
    # %s is a parameterized placeholder — psycopg2 safely substitutes the values.
    # This prevents SQL injection, which is when someone sends malicious SQL
    # as input to try to mess with your database.
    cur.execute(
        "INSERT INTO urls (short_code, original_url) VALUES (%s, %s)",
        (short_code, original_url)
    )
    conn.commit()
    cur.close()
    conn.close()

    # Build the short URL using the Host header from the request.
    # This means if you deploy this somewhere with a real domain, it
    # automatically uses that domain instead of "localhost".
    host = request.host
    short_url = f"http://{host}/{short_code}"

    # 201 = "Created" — the standard HTTP status code for "I made the thing you asked for"
    return jsonify({
        "short_code": short_code,
        "short_url": short_url,
        "original_url": original_url
    }), 201


@app.route("/<short_code>")
def redirect_to_url(short_code):
    """
    GET /<short_code>  (e.g., GET /aB7x)

    This is the "redirect" endpoint. When someone visits a short URL:
      1. Flask extracts the short code from the URL path
      2. Looks it up in the database
      3. If found: sends an HTTP 302 redirect to the original URL
      4. If not found: returns a 404 error

    The angle brackets in the route decorator — /<short_code> — are Flask's
    way of saying "capture whatever is in this part of the URL and pass it
    to the function as a parameter." So visiting /aB7x calls this function
    with short_code="aB7x".

    We use 302 (temporary redirect) instead of 301 (permanent redirect)
    because 301s get cached aggressively by browsers, which makes debugging
    a nightmare during development. In production, you might switch to 301.
    """
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT original_url FROM urls WHERE short_code = %s", (short_code,))
    result = cur.fetchone()
    cur.close()
    conn.close()

    if result is None:
        # 404 = "Not Found" — there's no mapping for this code
        return jsonify({"error": "Short URL not found"}), 404

    # redirect() is a Flask helper that builds the HTTP redirect response.
    # The browser receives this and automatically navigates to the original URL.
    return redirect(result["original_url"], code=302)


@app.route("/api/urls", methods=["GET"])
def list_urls():
    """
    GET /api/urls

    Returns a JSON list of all shortened URLs in the database.
    This is purely for the frontend — so you can display a table of
    all the links that have been created.

    ORDER BY created_at DESC means newest first.
    """
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT short_code, original_url, created_at FROM urls ORDER BY created_at DESC")
    urls = cur.fetchall()
    cur.close()
    conn.close()

    # fetchall() returns a list of RealDictRow objects.
    # We convert each one to a plain dict so jsonify can serialize it.
    # The created_at timestamp gets converted to an ISO format string
    # (e.g., "2025-02-15T14:30:00") so JSON can handle it — JSON doesn't
    # natively understand Python datetime objects.
    return jsonify([
        {
            "short_code": url["short_code"],
            "original_url": url["original_url"],
            "short_url": f"http://{request.host}/{url['short_code']}",
            "created_at": url["created_at"].isoformat() if url["created_at"] else None
        }
        for url in urls
    ])


@app.route("/api/health", methods=["GET"])
def health_check():
    """
    GET /api/health

    A simple health check endpoint. Returns 200 if the app is running
    and can connect to the database.

    This isn't just for show — Docker Compose has a 'healthcheck' option
    that can hit this endpoint to know if the container is actually working,
    not just running. This is a real-world pattern you'll see everywhere.
    """
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT 1")  # simplest possible query — just checks the DB is alive
        cur.close()
        conn.close()
        return jsonify({"status": "healthy", "database": "connected"}), 200
    except Exception as e:
        return jsonify({"status": "unhealthy", "database": str(e)}), 500


# --- Entry Point ---
# This block runs when you execute the file directly (python app.py).
# In Docker, this is what starts the app.
#
# host="0.0.0.0" means "listen on all network interfaces." By default,
# Flask only listens on 127.0.0.1 (localhost), which means ONLY the
# container itself could reach it. Since Nginx lives in a different
# container and needs to forward requests here, we need Flask to listen
# on 0.0.0.0 so it's reachable from outside the container.
#
# port=5000 is Flask's default port.
if __name__ == "__main__":
    init_db()  # Create the table if it doesn't exist
    app.run(host="0.0.0.0", port=5000)
