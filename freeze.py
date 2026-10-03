# freeze.py — render the Flask site to a static ./dist folder for Netlify.
#
# Run:  python freeze.py
# Then drag the resulting ./dist folder onto Netlify (NOT the project root —
# the project root contains .env).
#
# Delete cache_listings.json first to force a fresh pull from the API.

import shutil
import sys
from pathlib import Path

from app import app, fetch_listings

OUT = Path(__file__).parent / "dist"

STATIC_PAGES = [
    ("/", "index.html"),
    ("/inventory", "inventory/index.html"),
    ("/about", "about/index.html"),
    ("/contact", "contact/index.html"),
    ("/finance", "finance/index.html"),
    ("/gallery", "gallery/index.html"),
    ("/privacy-policy", "privacy-policy/index.html"),
]


def write(rel_path, data):
    dest = OUT / rel_path
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)


def render(client, url):
    resp = client.get(url)
    if resp.status_code != 200:
        raise RuntimeError(f"{url} returned {resp.status_code}")
    return resp.data


def main():
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir()

    failures = []

    with app.test_client() as client:
        for url, rel_path in STATIC_PAGES:
            try:
                write(rel_path, render(client, url))
                print(f"  {url} -> dist/{rel_path}")
            except Exception as e:
                failures.append((url, e))
                print(f"  FAILED {url}: {e}")

        listings = fetch_listings()
        print(f"\nRendering {len(listings)} listing pages...")
        for listing in listings:
            listing_id = listing.get("id")
            if listing_id is None:
                continue
            url = f"/listing/{listing_id}"
            rel_path = f"listing/{listing_id}/index.html"
            try:
                write(rel_path, render(client, url))
            except Exception as e:
                failures.append((url, e))
                print(f"  FAILED {url}: {e}")

    shutil.copytree(Path("static"), OUT / "static")
    print("\nCopied static/ -> dist/static/")

    if failures:
        print(f"\n{len(failures)} page(s) failed:")
        for url, e in failures:
            print(f"  {url}: {e}")
        sys.exit(1)

    total = sum(1 for _ in OUT.rglob("*.html"))
    print(f"\nDone. {total} HTML pages in dist/. Drag dist/ onto Netlify.")


if __name__ == "__main__":
    main()
