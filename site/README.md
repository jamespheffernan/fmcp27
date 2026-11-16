# fmcp27.com

Static site for FMCP 27, hosted on Cloudflare Pages (project `fmcp27`).

The public source repository is https://github.com/jamespheffernan/fmcp27. The home-page navigation and the home/404 footers link to it.

- `public/` is the deployed output: `index.html`, `404.html`, `styles.css`, `app.js`, fonts (Archivo and JetBrains Mono, SIL OFL, self-hosted), `favicon.svg`, `og.png`, `_headers`, `robots.txt`, `sitemap.xml`.
- `functions/_middleware.js` redirects `www.fmcp27.com` to `https://fmcp27.com` with a 301.
- `og/og.html` is the source of `public/og.png`.

`public/download/FMCP27-mac.zip` is the Mac download the page's button links to. It is not in git. Build it from the repository root before a deploy, and check it:

```sh
sh scripts/package_mac.sh            # writes site/public/download/FMCP27-mac.zip from HEAD
python3 scripts/test_package_mac.py  # installs it into an empty HOME and calls the MCP server
```

The package carries the address files of the game build installed on the packaging Mac. After a game update, run `scripts/fm_update_build.py --installed`, then package and deploy again; until then players on the new build are refused by the reader. Cloudflare Pages serves no file over 25 MiB (the package is under 6 MB); a larger one would go to an R2 bucket and the button would link there. The install steps on the page (the INS-1 sheet) repeat `packaging/mac/README.txt`; change them together.

No build step otherwise. The domain serves CSS and JS with a four-hour browser cache, so the pages load them by a versioned URL. After changing `public/styles.css` or `public/app.js`, run `python3 stamp.py` to update the version in `index.html` and `404.html`. Then deploy from this directory:

```sh
wrangler pages deploy public --project-name fmcp27 --branch main
```

Preview locally: `python3 -m http.server 8727 --directory public`.

Re-render the Open Graph image:

```sh
"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" --headless=new --hide-scrollbars \
  --allow-file-access-from-files --window-size=1200,630 --virtual-time-budget=2000 \
  --screenshot=public/og.png "file://$PWD/og/og.html"
```

## Optional X measurement

`public/tracking.js` is a first-party deferred script on the home page and 404. It loads X's `uwt.js` only after opt-in (or a still-valid saved opt-in), then configures pixel `rj4xn` once per page. Only a trusted activation of `a[href="/download/FMCP27-mac.zip"][download]` sends `twq('event', 'tw-rj4xn-rj6h1', {})`. This measures a button activation, not download completion. No earlier clicks are replayed, and the download is never intercepted or delayed. Without JavaScript the original link works and X does not load.

The non-modal consent sheet gives Accept and Reject the same styling. Privacy settings remain in the footer; the home-page privacy disclosure also works without JavaScript. Choice is held in first-party localStorage (`fmcp27.x-consent.v1`) for six calendar months, with a versioned record and expiry checks. Unavailable/invalid storage defaults to off. GPC or DNT veto tracking, including a saved acceptance. Rejecting after acceptance, cross-tab withdrawal, or expiry on an open page discards the local queue and reloads to unload X; this cannot recall requests already sent or erase cookies previously set by X.

The CSP retains the site's other restrictions and permits only X's static script host plus its documented image/connect destinations. `https://t.co` is also allowed in img/connect because the current official `uwt.js` uses its adsct/adsctp endpoints. There are no inline scripts, preconnects, noscript pixels or optional identifying event parameters.

Run the dependency-free regression tests from the repository root:

```sh
node --test site/tests/tracking.test.cjs
node --check site/public/tracking.js
python3 site/stamp.py
```

The stamp includes `tracking.js` as well as app.js/styles.css. Before deploying this tracking-only change, preserve the verified live Mac ZIP rather than rebuilding it from a different working tree. Browser verification should use the real script and response CSP, fresh storage, both choices, a native download-link activation, reloads and withdrawal; test clicks may appear in the X event account.

## Basic analytics (Lodd)

Added 16 November 2026. Free tier: 2,500 combined pageviews/custom events per month; collection pauses at the limit. No paid plan was enabled. Lodd MCP and REST API provide agent-first reporting without a dashboard.

- `public/analytics.js` loads Lodd only on canonical `fmcp27.com`, respects GPC/DNT, and provides an independent persistent opt-out. This is separate from optional X consent.
- Pageviews include referrers, UTM tags, country and device statistics. The official Lodd script uses a tab-scoped sessionStorage identifier and no cookies. Privacy disclosure and opt-out are in the footer.
- `download_mac` means a trusted activation of the direct Mac ZIP link, not a completed transfer or install. Properties: `file`, `platform`, `placement`. The download is never delayed/intercepted. No earlier clicks are replayed after opt-out.
- Credentials: `~/.config/fmcp27/lodd.json`, permission 0600, outside git and public assets. The public tracker collection identifier is not an account API key.
- From the repository root: `node site/scripts/analytics.mjs summary 7`, `node site/scripts/analytics.mjs events 7`, or `node site/scripts/analytics.mjs usage`.
- Project `.mcp.json` runs the official pinned `@lodd/mcp-server@0.1.18` via the local credential-loading wrapper. MCP-capable clients that support project config need to reload it. Other clients can use the REST CLI directly or connect to `https://api.lodd.dev/mcp` with OAuth.
- `summary` returns pageviews/visitors, event totals and download source conversion data. For arbitrary reports use the Lodd MCP tools; download conversion event is `download_mac`, site is `fmcp27.com`.
- API reference: https://lodd.dev/api ; privacy: https://lodd.dev/privacy
- Run `node --test site/tests/*.test.cjs`. The stamp script includes analytics.js.

Tracking-only deploys must preserve the live ZIP and avoid publishing unrelated local copy changes. The 16 November analytics deployment was built from the verified production files in an isolated directory. Verification pageviews and one Mac download click may be included in that day's totals.
