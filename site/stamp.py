#!/usr/bin/env python3
"""Stamp the stylesheet and script URLs in the pages with a hash of their contents.

The site's domain serves CSS and JS with a four-hour browser cache. Without a
version in the URL, a returning visitor gets new HTML with an old stylesheet.
Run this after changing public/styles.css, public/app.js, public/tracking.js or public/analytics.js and before deploying.
"""
import hashlib
import pathlib
import re

public = pathlib.Path(__file__).parent / "public"
assets = {name: hashlib.sha256((public / name).read_bytes()).hexdigest()[:10] for name in ("styles.css", "app.js", "tracking.js", "analytics.js")}

for page in ("index.html", "404.html"):
    path = public / page
    html = path.read_text()
    for name, digest in assets.items():
        html = re.sub(rf'(["\']/{re.escape(name)})(\?v=[0-9a-f]+)?(["\'])', rf"\g<1>?v={digest}\g<3>", html)
    path.write_text(html)
    print(page, {name: digest for name, digest in assets.items() if f"/{name}?v={digest}" in html})
