"""Site health check for prommer.net.

Reads the sitemap, fetches every page (8 at a time, stdlib only), and writes
report.json for index.html to render. Checks are the ones that matter for a
multilingual personal site that has to win inbound: broken pages, slow pages,
missing/duplicate titles and descriptions, canonical pointing elsewhere,
missing og:image, and <html lang> not matching the /xx/ locale in the URL.
"""
import json
import re
import time
import urllib.request
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

SITE = "https://prommer.net"
UA = "Mozilla/5.0 (prommer-build health check; github.com/VeldanDev/prommer-build)"
SLOW_SECONDS = 1.5


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    start = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            body = r.read().decode("utf-8", "replace")
            return r.status, r.geturl(), body, time.monotonic() - start
    except urllib.error.HTTPError as e:
        return e.code, url, "", time.monotonic() - start
    except Exception as e:
        return 0, url, str(e), time.monotonic() - start


def sitemap_urls():
    urls, queue = [], [f"{SITE}/sitemap.xml"]
    while queue:
        _, _, xml, _ = fetch(queue.pop())
        locs = re.findall(r"<loc>([^<]+)</loc>", xml)
        if "<sitemapindex" in xml:
            queue += locs
        else:
            urls += locs
    return urls


def meta(html, attr, name):
    m = re.search(rf'<meta[^>]+{attr}="{re.escape(name)}"[^>]*content="([^"]*)"', html) or \
        re.search(rf'<meta[^>]+content="([^"]*)"[^>]*{attr}="{re.escape(name)}"', html)
    return m.group(1).strip() if m else ""


def check(url):
    status, final, html, secs = fetch(url)
    page = {"url": url, "status": status, "seconds": round(secs, 2), "issues": []}
    issues = page["issues"]
    if status != 200:
        issues.append(f"HTTP {status}" if status else f"unreachable: {html[:80]}")
        return page
    if not final.startswith(SITE):
        # The page moved to another property. Checking the destination's
        # canonical/lang would blame prommer.net for someone else's HTML,
        # so report the one real problem: the sitemap still lists it.
        issues.append(f"in sitemap but redirects off-site to {final.split('/')[2]}")
        page["redirect"] = final
        return page
    if final.rstrip("/") != url.rstrip("/"):
        issues.append(f"redirects to {final}")
    if secs > SLOW_SECONDS:
        issues.append(f"slow: {secs:.1f}s")

    title = re.search(r"<title[^>]*>(.*?)</title>", html, re.S)
    page["title"] = title.group(1).strip() if title else ""
    page["description"] = meta(html, "name", "description")
    if not page["title"]:
        issues.append("missing <title>")
    elif len(page["title"]) > 65:
        issues.append(f"title {len(page['title'])} chars (cut off in Google)")
    if not page["description"]:
        issues.append("missing meta description")
    if not meta(html, "property", "og:image"):
        issues.append("missing og:image (bare link previews)")

    canon = re.search(r'<link[^>]+rel="canonical"[^>]+href="([^"]+)"', html) or \
        re.search(r'<link[^>]+href="([^"]+)"[^>]+rel="canonical"', html)
    if not canon:
        issues.append("missing canonical")
    elif canon.group(1).rstrip("/") != url.rstrip("/"):
        issues.append(f"canonical points to {canon.group(1)}")

    locale = re.match(rf"{re.escape(SITE)}/([a-z]{{2}})/", url)
    lang = re.search(r'<html[^>]+lang="([^"]+)"', html)
    expected = locale.group(1) if locale else "en"
    if not lang:
        issues.append("missing <html lang>")
    elif not lang.group(1).lower().startswith(expected):
        issues.append(f'<html lang="{lang.group(1)}"> on a /{expected}/ page')
    return page


def main():
    urls = sitemap_urls()
    with ThreadPoolExecutor(max_workers=8) as pool:
        pages = list(pool.map(check, urls))

    for field in ("title", "description"):
        counts = Counter(p.get(field) for p in pages if p.get(field))
        for p in pages:
            if p.get(field) and counts[p[field]] > 1:
                p["issues"].append(f"duplicate {field} ({counts[p[field]]} pages)")

    kinds = Counter(re.sub(r"\d+(\.\d+)?|https?://\S+|\"[^\"]*\"|/[a-z]{2}/", "…", i)
                    for p in pages for i in p["issues"])
    report = {
        "site": SITE,
        "checked_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "pages": len(pages),
        "pages_with_issues": sum(1 for p in pages if p["issues"]),
        "issue_kinds": kinds.most_common(),
        "results": sorted(pages, key=lambda p: (-len(p["issues"]), p["url"])),
    }
    with open("report.json", "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=1)
    print(f"{report['pages']} pages, {report['pages_with_issues']} with issues")
    for kind, n in report["issue_kinds"][:12]:
        print(f"{n:4}  {kind}")


if __name__ == "__main__":
    main()
