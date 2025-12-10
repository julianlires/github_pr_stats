import requests
import datetime
import sqlite3
import json
import os
from collections import defaultdict
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# -----------------------
# Configuration
# -----------------------
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
OWNER = os.getenv("GITHUB_OWNER")
REPO = os.getenv("GITHUB_REPO")

if not GITHUB_TOKEN or not OWNER or not REPO:
    raise ValueError("Missing required environment variables. Please check your .env file.")

BASE_URL = "https://api.github.com"
HEADERS = {"Authorization": f"token {GITHUB_TOKEN}"}
DB_FILE = "github_pr_cache.db"


def init_database():
    """Initialize SQLite database with schema for caching PRs and reviews."""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    # Table for pull requests
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS pull_requests (
            pr_number INTEGER PRIMARY KEY,
            title TEXT,
            state TEXT,
            created_at TEXT,
            updated_at TEXT,
            pr_data TEXT,
            cached_at TEXT
        )
    """)
    
    # Table for reviews
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS reviews (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            pr_number INTEGER,
            review_data TEXT,
            cached_at TEXT,
            FOREIGN KEY (pr_number) REFERENCES pull_requests(pr_number)
        )
    """)
    
    conn.commit()
    conn.close()


def iso_to_dt(s):
    return datetime.datetime.fromisoformat(s.replace("Z", "+00:00"))


def fetch_all(url):
    results = []
    while url:
        r = requests.get(url, headers=HEADERS)
        r.raise_for_status()
        results.extend(r.json())

        # pagination
        if "next" in r.links:
            url = r.links["next"]["url"]
        else:
            url = None

    return results


def save_pr_to_db(pr):
    """Save a pull request to the database."""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    cursor.execute("""
        INSERT OR REPLACE INTO pull_requests 
        (pr_number, title, state, created_at, updated_at, pr_data, cached_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (
        pr["number"],
        pr["title"],
        pr["state"],
        pr["created_at"],
        pr["updated_at"],
        json.dumps(pr),
        datetime.datetime.now().isoformat()
    ))
    
    conn.commit()
    conn.close()


def save_reviews_to_db(pr_number, reviews):
    """Save reviews for a PR to the database."""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    # Delete existing reviews for this PR
    cursor.execute("DELETE FROM reviews WHERE pr_number = ?", (pr_number,))
    
    # Insert new reviews
    for review in reviews:
        cursor.execute("""
            INSERT INTO reviews (pr_number, review_data, cached_at)
            VALUES (?, ?, ?)
        """, (
            pr_number,
            json.dumps(review),
            datetime.datetime.now().isoformat()
        ))
    
    conn.commit()
    conn.close()


def get_pr_from_db(pr_number):
    """Retrieve a PR from the database."""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    cursor.execute(
        "SELECT pr_data FROM pull_requests WHERE pr_number = ?",
        (pr_number,)
    )
    
    row = cursor.fetchone()
    conn.close()
    
    if row:
        return json.loads(row[0])
    return None


def get_reviews_from_db(pr_number):
    """Retrieve reviews for a PR from the database."""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    cursor.execute(
        "SELECT review_data FROM reviews WHERE pr_number = ?",
        (pr_number,)
    )
    
    rows = cursor.fetchall()
    conn.close()
    
    return [json.loads(row[0]) for row in rows]


def get_cached_closed_prs():
    """Get all closed PRs from the database."""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    cursor.execute(
        "SELECT pr_data FROM pull_requests WHERE state = 'closed'"
    )
    
    rows = cursor.fetchall()
    conn.close()
    
    return [json.loads(row[0]) for row in rows]


def fetch_prs():
    print("Fetching pull requests...")
    return fetch_all(f"{BASE_URL}/repos/{OWNER}/{REPO}/pulls?state=all&per_page=100")


def fetch_reviews(pr_number):
    return fetch_all(f"{BASE_URL}/repos/{OWNER}/{REPO}/pulls/{pr_number}/reviews")


def get_stats(from_date=None, to_date=None):
    """
    Get PR statistics with optional date filtering.
    
    Args:
        from_date: Start date (ISO format string or None)
        to_date: End date (ISO format string or None)
    """
    # Initialize database
    init_database()
    
    # Parse date parameters
    from_dt = None
    to_dt = None
    
    if from_date:
        from_dt = datetime.datetime.fromisoformat(from_date.replace("Z", "+00:00"))
        if from_dt.tzinfo is None:
            from_dt = from_dt.replace(tzinfo=datetime.timezone.utc)
    
    if to_date:
        to_dt = datetime.datetime.fromisoformat(to_date.replace("Z", "+00:00"))
        if to_dt.tzinfo is None:
            to_dt = to_dt.replace(tzinfo=datetime.timezone.utc)
    elif from_date and not to_date:
        # If only from_date is provided, to_date is now
        to_dt = datetime.datetime.now(datetime.timezone.utc)
    
    # Display date filter info
    if from_dt and to_dt:
        print(f"\n=== Filtering PRs from {from_dt.date()} to {to_dt.date()} ===")
    elif from_dt:
        print(f"\n=== Filtering PRs from {from_dt.date()} to now ===")
    else:
        print("\n=== No date filter applied ===")
    
    # Fetch ALL PRs from API (both open and closed)
    print("Fetching all pull requests from API...")
    all_prs = fetch_all(f"{BASE_URL}/repos/{OWNER}/{REPO}/pulls?state=all&per_page=100")
    
    print(f"Found {len(all_prs)} total PRs")
    
    # Cache all PRs
    for pr in all_prs:
        save_pr_to_db(pr)
    
    # Apply date filtering
    if from_dt or to_dt:
        filtered_prs = []
        for pr in all_prs:
            created_at = iso_to_dt(pr["created_at"])
            
            if from_dt and created_at < from_dt:
                continue
            if to_dt and created_at > to_dt:
                continue
            
            filtered_prs.append(pr)
        
        print(f"After date filtering: {len(filtered_prs)} PRs")
        all_prs = filtered_prs
    
    reviewer_metrics = defaultdict(list)
    pr_metrics = []

    for pr in all_prs:
        pr_number = pr["number"]
        created_at = iso_to_dt(pr["created_at"])
        updated_at = iso_to_dt(pr["updated_at"])
        title = pr["title"]
        state = pr["state"]

        print(f"Processing PR #{pr_number}: {title} [{state}]")

        # For closed PRs, try to use cached reviews first
        if state == "closed":
            reviews = get_reviews_from_db(pr_number)
            if reviews:
                print(f"  Using cached reviews for closed PR #{pr_number}")
            else:
                print(f"  Fetching reviews for closed PR #{pr_number} (not in cache)")
                reviews = fetch_reviews(pr_number)
                save_reviews_to_db(pr_number, reviews)
        else:
            # For open PRs, always fetch fresh reviews
            print(f"  Fetching fresh reviews for open PR #{pr_number}")
            reviews = fetch_reviews(pr_number)
            save_reviews_to_db(pr_number, reviews)

        if not reviews:
            pr_metrics.append({
                "pr_number": pr_number,
                "title": title,
                "created_at": created_at,
                "first_review_at": None,
                "time_to_first_review_hours": None
            })
            continue

        # Sort reviews by submission time
        reviews_sorted = sorted(reviews, key=lambda r: r.get("submitted_at") or "")

        # First review time
        first_review = next((r for r in reviews_sorted if r.get("submitted_at")), None)

        if first_review:
            first_review_at = iso_to_dt(first_review["submitted_at"])
            delta = first_review_at - created_at
            hours = delta.total_seconds() / 3600
        else:
            first_review_at = None
            hours = None

        # Save PR metric
        pr_metrics.append({
            "pr_number": pr_number,
            "title": title,
            "created_at": created_at,
            "first_review_at": first_review_at,
            "time_to_first_review_hours": hours
        })

        # Per-reviewer metrics
        for r in reviews_sorted:
            if not r.get("submitted_at"):
                continue

            reviewer = r["user"]["login"]
            submitted = iso_to_dt(r["submitted_at"])
            reviewer_delta = submitted - created_at

            reviewer_metrics[reviewer].append(reviewer_delta.total_seconds() / 3600)

    # -------------------------
    # Print results
    # -------------------------

    print("\n=== PR Review Times ===")
    for pr in pr_metrics:
        print(f"PR #{pr['pr_number']}: {pr['title']}")
        print(f"  Created: {pr['created_at']}")
        print(f"  First review: {pr['first_review_at']}")
        print(f"  Time to first review (hours): {pr['time_to_first_review_hours']}")
        print()

    print("\n=== Reviewer Statistics ===")
    for reviewer, times in sorted(reviewer_metrics.items()):
        avg = sum(times) / len(times)
        fastest = min(times)
        slowest = max(times)
        print(f"{reviewer}:")
        print(f"  Average: {avg:.2f} hours")
        print(f"  Fastest: {fastest:.2f} hours")
        print(f"  Slowest: {slowest:.2f} hours")
        print(f"  Total reviews: {len(times)}")
        print()


def parse_and_execute(command):
    """
    Parse and execute a command in the format: method(arg1, arg2, ...)
    """
    command = command.strip()
    
    # Check if command has parentheses
    if '(' not in command or ')' not in command:
        print("Error: Invalid command format. Use: method(arg1, arg2, ...)")
        return
    
    # Extract method name and arguments
    method_name = command[:command.index('(')].strip()
    args_str = command[command.index('(') + 1:command.rindex(')')].strip()
    
    # Parse arguments
    args = []
    if args_str:
        # Split by comma, but be careful with quoted strings
        import re
        # Simple argument parser - handles quoted strings and bare values
        args = [arg.strip().strip('"').strip("'") for arg in re.split(r',\s*(?=(?:[^"]*"[^"]*")*[^"]*$)', args_str) if arg.strip()]
    
    # Execute the method
    if method_name == 'get_stats':
        if len(args) == 0:
            get_stats()
        elif len(args) == 1:
            get_stats(args[0])
        elif len(args) == 2:
            get_stats(args[0], args[1])
        else:
            print(f"Error: get_stats accepts 0, 1, or 2 arguments, got {len(args)}")
    else:
        print(f"Error: Unknown method '{method_name}'")
        print("Available methods:")
        print("  - get_stats(): Get all PR statistics")
        print("  - get_stats(from_date): Get PR statistics from date to now")
        print("  - get_stats(from_date, to_date): Get PR statistics in date range")


def main():
    """
    Main interactive loop - keeps process alive and waits for commands.
    """
    print("="*60)
    print("GitHub PR Statistics - Interactive Mode")
    print("="*60)
    print("\nAvailable commands:")
    print("  get_stats()                      - Get all PR statistics")
    print("  get_stats(from_date)             - From date to now")
    print("  get_stats(from_date, to_date)    - Date range filter")
    print("\nDate format: YYYY-MM-DD (e.g., 2024-01-01)")
    print("Type 'exit' or 'quit' to stop\n")
    print("="*60)
    
    while True:
        try:
            command = input("\n> ").strip()
            
            if not command:
                continue
            
            if command.lower() in ['exit', 'quit', 'q']:
                print("Goodbye!")
                break
            
            if command.lower() in ['help', '?']:
                print("\nAvailable commands:")
                print("  get_stats()                      - Get all PR statistics")
                print("  get_stats(from_date)             - From date to now")
                print("  get_stats(from_date, to_date)    - Date range filter")
                print("\nExamples:")
                print("  get_stats()")
                print("  get_stats(2024-01-01)")
                print("  get_stats(2024-01-01, 2024-12-31)")
                continue
            
            parse_and_execute(command)
            
        except KeyboardInterrupt:
            print("\n\nInterrupted. Type 'exit' to quit.")
        except Exception as e:
            print(f"Error: {e}")
            import traceback
            traceback.print_exc()


if __name__ == "__main__":
    main()
