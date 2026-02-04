import sqlite3
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from bs4 import BeautifulSoup
from datetime import datetime

# Updated URL to show all job postings
BASE_URL = "https://www.applitrack.com/humbleisd/onlineapp/default.aspx?all=1"
DB_NAME = "jobs.db"

def init_db():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS jobs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            location TEXT NOT NULL,
            posting_date DATE,
            url TEXT NOT NULL,
            scraped_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    conn.commit()
    conn.close()

def save_jobs(jobs):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    for job in jobs:
        c.execute('''
            INSERT OR REPLACE INTO jobs (title, location, posting_date, url)
            VALUES (?, ?, ?, ?)
        ''', (job["title"], job["location"], job["posting_date"], job["url"]))
    conn.commit()
    conn.close()

def scrape_jobs():
    # Set up headless Chrome
    options = Options()
    options.add_argument("--headless")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    
    driver = webdriver.Chrome(options=options)
    
    try:
        driver.get(BASE_URL)
        driver.implicitly_wait(10)  # Increased wait time for full load
        
        # Get the rendered HTML
        soup = BeautifulSoup(driver.page_source, "html.parser")
        
        # Find the job listings table
        job_table = soup.find("table", id="listy")
        if not job_table:
            print("No job table found with id='listy'. Checking alternatives...")
            print(soup.prettify()[:2000])  # Debug output
            return []
        
        jobs = []
        # Parse each job row
        for row in job_table.find_all("tr")[1:]:  # Skip header row
            cols = row.find_all("td")
            if len(cols) >= 3:
                title = cols[0].text.strip()
                location = cols[1].text.strip()
                posting_date_str = cols[2].text.strip()
                
                # Parse posting date
                try:
                    posting_date = datetime.strptime(posting_date_str, "%m/%d/%Y").date()
                except ValueError:
                    posting_date = None
                
                # Get job URL
                link_tag = cols[0].find("a")
                job_url = link_tag["href"] if link_tag else BASE_URL
                if job_url.startswith("/"):
                    job_url = "https://www.applitrack.com/humbleisd/onlineapp/" + job_url

                job = {
                    "title": title,
                    "location": location,
                    "posting_date": posting_date,
                    "url": job_url
                }
                jobs.append(job)
        
        return jobs
    
    finally:
        driver.quit()

def main():
    init_db()
    print("Scraping jobs from Humble ISD Applitrack...")
    jobs = scrape_jobs()
    
    if jobs:
        save_jobs(jobs)
        print(f"Saved {len(jobs)} jobs to the database.")
        conn = sqlite3.connect(DB_NAME)
        c = conn.cursor()
        c.execute("SELECT * FROM jobs LIMIT 5")
        for row in c.fetchall():
            print(row)
        conn.close()
    else:
        print("No jobs found or scraping failed.")

if __name__ == "__main__":
    main()
