"""Daily scrape of Florida state job postings (jobs.myflorida.com).

Incremental: listing pages are crawled every run; detail pages (salary, agency
header) are fetched only for job IDs we haven't seen before. Each job keeps
first_seen / last_seen, so the CSV doubles as a history of when postings opened
and closed.
"""
import csv
import html
import json
import re
import statistics
import sys
import time
import urllib.request
from datetime import date, datetime
from pathlib import Path

BASE = "https://jobs.myflorida.com"
ROOT = Path(__file__).parent
JOBS_CSV = ROOT / "data" / "jobs.csv"
DASH_JSON = ROOT / "docs" / "data.json"
FIELDS = ["job_id", "req_no", "title", "agency", "category", "city", "zip", "posted",
          "closing", "pay_plan", "salary_raw", "salary_min", "salary_max", "url",
          "first_seen", "last_seen"]
DATA_ROLE = re.compile(r"\b(data|analyst|analytics|statistic\w*|database|developer|programmer|"
                       r"software|gis|business intelligence|information technology|"
                       r"systems? (analyst|administrator|engineer)|research)\b", re.I)


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (fl-jobs-pipeline)"})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.read().decode("utf-8", "replace")
        except OSError:
            if attempt == 2:
                raise
            time.sleep(5)


def text(s):
    return html.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", s))).strip()


def span(row, cls):
    m = re.search(rf'<span class="{cls}">(.*?)</span>', row, re.S)
    return text(m.group(1)) if m else ""


def crawl_listings():
    """Every open posting from the search pages: {job_id: fields}."""
    jobs, start = {}, 0
    while True:
        page = get(f"{BASE}/search/?q=&startrow={start}")
        rows = page.split('<tr class="data-row">')[1:]
        for row in rows:
            m = re.search(r'href="(/job/[^"]+/(\d+)/)" class="jobTitle-link">(.*?)</a>', row, re.S)
            if not m:
                continue
            loc = span(row, "jobLocation").split(",")
            jobs[m.group(2)] = {
                "job_id": m.group(2),
                "url": BASE + m.group(1),
                "title": text(m.group(3)),
                "city": loc[0].strip().title(),
                "zip": loc[-1].strip() if len(loc) > 1 else "",
                "posted": datetime.strptime(span(row, "jobDate"), "%b %d, %Y").date().isoformat(),
                "category": span(row, "jobDepartment"),
                "agency": span(row, "jobFacility"),
            }
        if len(rows) < 25:
            return jobs
        start += 25
        time.sleep(0.5)


def parse_salary(s):
    """Annual (min, max) from free-text salary, or (None, None).

    Amounts are annualised by size: <200 hourly, <10k biweekly/monthly, else annual.
    When an annual figure is present the per-period companions are ignored, so
    "$50,000.08 annually / $1,923.08 bi-weekly" doesn't become a 50k-1.3M range.
    """
    s = re.split(r"\bplus\b| \+ ", s, flags=re.I)[0]  # drop differentials/benefits add-ons
    s = re.sub(r"(\d), (\d{3})", r"\1,\2", s)  # "$36, 216.96"
    # with any "$" present, only $-amounts count ("10% increase", "0-3.9yrs=$2,299.04")
    pattern = r"\$\s*(\d[\d,]*\.?\d*)" if "$" in s else r"(\d[\d,]*\.?\d*)"
    amounts = [float(a.replace(",", "")) for a in re.findall(pattern, s)]
    amounts = [a for a in amounts if a >= 7]
    if not amounts:
        return None, None
    annual = [a for a in amounts if a >= 10_000]
    if not annual:
        per = 12 if re.search(r"month", s, re.I) else 26
        annual = [a * 2080 if a < 200 else a * per for a in amounts]
    lo, hi = round(min(annual)), round(max(annual))
    if hi > 3 * lo:  # source typos like "$47,2350.16"; trust the floor
        hi = lo
    return (lo, hi) if 15_000 <= lo <= hi <= 500_000 else (None, None)


def fetch_detail(url):
    page = get(url)
    i = page.find("jobdescription")
    t = text(page[i:i + 4000]) if i >= 0 else ""

    def field(label, nxt):
        m = re.search(rf"{label}:\s*(.*?)\s*(?:{nxt}):", t)
        return m.group(1).strip() if m else ""

    salary = field("Salary", "Posting Closing Date")
    lo, hi = parse_salary(salary)
    closing = re.search(r"Posting Closing Date:\s*(\d\d/\d\d/\d{4})", t)
    return {
        "req_no": field("Requisition No", "Agency"),
        "pay_plan": field("Pay Plan", "Position Number|Salary"),
        "salary_raw": salary[:120],
        "salary_min": lo or "",
        "salary_max": hi or "",
        "closing": datetime.strptime(closing.group(1), "%m/%d/%Y").date().isoformat() if closing else "",
    }


def load():
    if not JOBS_CSV.exists():
        return {}
    with JOBS_CSV.open() as f:
        return {r["job_id"]: r for r in csv.DictReader(f)}


def save(jobs):
    JOBS_CSV.parent.mkdir(exist_ok=True)
    with JOBS_CSV.open("w", newline="") as f:
        w = csv.DictWriter(f, FIELDS)
        w.writeheader()
        w.writerows(sorted(jobs.values(), key=lambda r: (r["first_seen"], r["job_id"])))


def build_dashboard(jobs, today):
    """Compact JSON for docs/index.html: open postings + daily open-count trend."""
    open_jobs = [j for j in jobs.values() if j["last_seen"] == today]
    days = sorted({j["first_seen"] for j in jobs.values()} | {j["last_seen"] for j in jobs.values()})
    trend = [{"date": d,
              "open": sum(j["first_seen"] <= d <= j["last_seen"] for j in jobs.values()),
              "new": sum(j["first_seen"] == d for j in jobs.values())} for d in days]
    salaries = [int(j["salary_min"]) for j in open_jobs if j["salary_min"]]
    DASH_JSON.parent.mkdir(exist_ok=True)
    DASH_JSON.write_text(json.dumps({
        "updated": today,
        "tracked_total": len(jobs),
        "median_salary": statistics.median(salaries) if salaries else None,
        "trend": trend,
        # short keys keep the file small: title, agency, category, city, posted, closing, min, max, data-role, url path
        "jobs": [{"t": j["title"], "a": j["agency"], "c": j["category"], "l": j["city"],
                  "p": j["posted"], "x": j["closing"],
                  "lo": int(j["salary_min"]) if j["salary_min"] else None,
                  "hi": int(j["salary_max"]) if j["salary_max"] else None,
                  "d": bool(DATA_ROLE.search(j["title"])), "u": j["url"].removeprefix(BASE)}
                 for j in sorted(open_jobs, key=lambda j: j["posted"], reverse=True)],
    }, separators=(",", ":")))


def main():
    today = date.today().isoformat()
    jobs = load()
    listed = crawl_listings()
    if len(listed) < 100:  # site change or outage: fail loudly rather than mark everything closed
        sys.exit(f"only {len(listed)} listings found, aborting")
    new = [jid for jid in listed if jid not in jobs]
    print(f"{len(listed)} open, {len(new)} new")
    for n, jid in enumerate(new, 1):
        row = {**dict.fromkeys(FIELDS, ""), **listed[jid], "first_seen": today}
        try:
            row.update(fetch_detail(row["url"]))
        except OSError as e:
            print(f"detail failed {jid}: {e}")
        jobs[jid] = row
        if n % 100 == 0:
            print(f"  {n}/{len(new)} details")
        time.sleep(0.3)
    for jid, fields in listed.items():
        jobs[jid].update(fields)  # titles/categories can change on the listing
        jobs[jid]["last_seen"] = today
    save(jobs)
    build_dashboard(jobs, today)


if __name__ == "__main__":
    main()
