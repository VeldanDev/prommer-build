# prommer.net health check

`check.py` reads the prommer.net sitemap, fetches every page (Python stdlib, 8 parallel requests) and writes `report.json`. `index.html` renders it.

Live report: https://veldandev.github.io/prommer-build/

Run again: `python check.py`
