"""Debug the Output.asp?all=1 response which has all job data."""
import httpx
from bs4 import BeautifulSoup

url = "https://www.applitrack.com/humbleisd/onlineapp/jobpostings/Output.asp?all=1"
resp = httpx.get(url, timeout=30, follow_redirects=True, headers={"User-Agent": "Mozilla/5.0 Chrome/121.0.0.0"})
soup = BeautifulSoup(resp.text, "lxml")

# Check the structure of the tables
tables = soup.find_all("table")
print(f"Total tables: {len(tables)}")

# Look at the first few tables
for i, table in enumerate(tables[:5]):
    rows = table.find_all("tr")
    print(f"\nTable {i}: class={table.get('class')} rows={len(rows)}")
    for j, row in enumerate(rows[:3]):
        cells = row.find_all(["td", "th"])
        texts = [c.get_text(strip=True)[:50] for c in cells]
        print(f"  Row {j}: {texts}")

# Look for links that seem like job posting detail links
detail_links = soup.find_all("a", href=lambda x: x and ("BrowseFile" in str(x) or "view" in str(x).lower() or "detail" in str(x).lower()))
print(f"\nDetail links: {len(detail_links)}")
for link in detail_links[:5]:
    print(f"  {link.get_text(strip=True)[:60]} -> {link.get('href', '')[:80]}")

# Try to find the job titles - look for text patterns
# Job titles in Applitrack are typically in bold or in specific cells
bolds = soup.find_all("b")
print(f"\nBold elements: {len(bolds)}")
for b in bolds[:10]:
    text = b.get_text(strip=True)
    if text and len(text) > 5:
        print(f"  {text[:80]}")

# Look for the actual job listing pattern
print("\n--- Sample HTML from middle of page ---")
all_text = str(soup)
mid = len(all_text) // 4
print(all_text[mid:mid+2000])
