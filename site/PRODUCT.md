# Product

<!-- impeccable:product-schema 1 -->

Source: the owner's written brief for the fmcp27.com site (11 November 2026), relayed by the parent agent. No interview round was possible in this session (no question tool available to the building agent); every fact below comes from that brief. Lines marked "inferred" are the building agent's reading of it. Later the same day the owner reviewed the first build and asked for two changes: stronger examples, and a page that explains a product to a player instead of reporting engineering progress (his example of what to cut: "21 correct on first try"). The page rules below reflect that. On 12 November 2026 he asked for a page that explains the product, how it works and what a manager might do with it, with much less text and fewer examples; he chose a three-step structure with one example, recorded in `.impeccable/surfaces/public-index-html.md`.

## Platform

web

## Stack

Static HTML and CSS with minimal JavaScript, no framework (brief preference). Hosted on Cloudflare Pages, project `fmcp27`, domain fmcp27.com with www redirecting to the apex.

## Users

People who play Football Manager 27 seriously and care about its data: they open the scouting, finance and match-analysis screens as much as the match engine. They use an AI assistant (Codex, Claude, Pi) and want it to answer questions about their own career save. Inferred: they arrive from a link shared by the owner, read the page on a desktop or phone, and want to know what the tool does, what it needs, and whether they can get it.

## Product Purpose

FMCP 27 is a local tool for macOS on Apple Silicon that lets an AI assistant read a running Football Manager 27 career and answer questions about it. It is an MCP (Model Context Protocol) server plus a terminal adviser client called pi-fm.

## Positioning

It reads the live game's memory, read-only. It never advances the game, clicks the UI, or calls game functions. It answers from the save you are actually playing, with purpose-built tools, and can restrict answers to what your club knows in-universe.

## Operating Context

The game runs on the same Mac. The assistant calls the MCP tools; the reader is pinned to Football Manager 27 build 27.0.0.2493426 and refuses other builds.

## Capabilities and Constraints

State as of 11 November 2026 (reader 0.164.0, private, not available to download). These are the facts on hand. The page uses the ones a player cares about (what it reads, the size of a save, how fast a question is answered, what each view shows). Verification counts, evaluation scores, token counts and implementation mechanics stay in the repository docs and off the page:
- 189 tools: players (attributes, hidden attributes, ability, personality, health, contracts, wages, clauses, loans), staff, clubs and finances (budgets, debt, FFP projections, sell-on and appearance clauses), competitions, stages, standings, fixtures, registration rules, tactics and training setups, live and retained match data (shots with xG, pass networks, average positions, heatmaps, player match statistics), database fields, the SQL snapshot, game screens, saved-file queries, and an HTML match report.
- Database fields: the game ships its own schema (2,269 field codes across 38 record types); FMCP 27 replays the game's own accessor code in an emulator to read any of them. Against the hand-built decoders, 31,385 of 31,601 compared cells agree (99.3%); every difference is classified (for example the displayed, translated currency name against the stored one).
- SQL snapshot of the whole save: 170,499 people, 28,022 clubs, 8,136 competitions in the owner's save. One whole-save query takes about a second once the columns are filled; refresh after a game day about a minute; first build on a new game version about 25 minutes; a background process fills the slower columns (about 40 minutes for all 66,043 players). Direct read plans are used only where they agree with the game's getter on separate records (0 mismatches in 101,529 checked cells).
- Manager view (fog of war): any query can be limited to what your club knows. Exact, range or unknown per attribute; ability as the game's star ranges; unmasked tables not readable through it; covers the whole save. Matches the game's visibility computation on 4,794 of 4,794 cells (engine check) and 2,350 of 2,350 (SQL view). 979 of 1,000 sampled players at least partly known, 8 fully unknown. Masking of non-attribute fields (wages, contracts of other clubs' players) is a conservative policy, not confirmed game behaviour; the page says so.
- Game screens: the game's own screen handlers built in the emulator (board confidence with per-area grades and sentences, inbox, calendar, player happiness and promises, club vision, scouting, transfers, squad dynamics, training, medical, finances, youth intake, league table, manager profile, season expectations). Board confidence, club-vision objectives, wages and board members matched the owner's screens. Gaps: objective judgements ("Pleased", "On Course") not readable yet; texts that depend on the game's random draws can differ from an already-drawn screen.
- pi-fm 1.2.0: declares 17 tools up front and finds the rest by search (first model call about 10.8K tokens, down from about 61K); answered all 22 questions of a 22-question evaluation from real sessions, 21 correctly on the first run; writes self-contained HTML reports.
- One optional, explicitly confirmed edit: a player's training intensity.

Roadmap (owner's words): phase 1 full read access to all data in the active save (built, in private testing; limits: youth placeholder players, some club budget fields, match-engine data still from purpose-built tools); phase 2 fog of war (built); phase 3 full write abilities in the manner of a real-time editor (not started beyond the training-intensity edit); phase 4 game control and automation (not started).

Requirements: macOS on Apple Silicon; Football Manager 27 build 27.0.0.2493426; an MCP-capable client (Codex, Claude, Pi).

## Brand Commitments

- Name: FMCP 27. Client name: pi-fm.
- Voice: plain, literal statements addressed to a Football Manager player, in the game's own terms (scouts, stars, hidden attributes, board confidence, FFP). No hype, no "not X but Y", no ellipses, no exclamation marks, no engineering vocabulary (emulator, accessor, decoder, token).
- Unofficial. Not affiliated with or endorsed by Sports Interactive or SEGA. Football Manager is a trademark of its owners. No SI/SEGA logos, game screenshots, club crests or real player photos.
- Real club and player names appear in the examples. The owner chose this on 11 November 2026, replacing the earlier invented-names rule. The footer says the events happened in the game, not in real football.
- Owner's name and email do not appear on the site.
- The one outbound link is the product's X account, @TurfTerrace (https://x.com/TurfTerrace), for release news. The owner approved it on 11 November 2026. There is still no sign-up form or mailing list. Since 13 November 2026 the page offers the Mac download (`/download/FMCP27-mac.zip`, built by `scripts/package_mac.sh`): Apple Silicon, the Steam copy of the game only, reading is free, Windows is "coming soon".

## Evidence on Hand

The measured numbers above. No download, price, public repository, mailing list, testimonials or users to cite. Do not invent any of these. The examples are condensed from the owner's real pi-fm sessions on his Newcastle United career (game dates November to December 2030), in `sessions/` of the installed adviser: the PSG half-time read and the rest of that match, the Man City match at 68 minutes, the Woltemade and Henrique diagnosis, the post-match "more attackers in the box" answer, the January profile and the midfielder profiles. Each is labelled "Real session, condensed" or "excerpts". The owner rejected the first set of invented examples as unsophisticated; the standard is what the adviser really said, including its trade-offs, checkpoints and admissions of what the data cannot show. Numbers on the page were checked against the saved match report where one exists: the session said Hall had two shots in the box at Man City, the match data shows one, and the page uses the match data. The scouting shortlist uses real values read from the save on 10 December 2030; its Manager view answer quotes a real report and its Full read answer was written for the page from the real values. The "What you can ask" questions are the owner's own, with typos fixed.

## Product Principles

1. Read-only by default; any write is explicit and confirmed.
2. Describe what a manager can do with it. Use a number only when a player would care about it, and state it exactly. Mark what is built, in testing or not started.
3. Answer from the save the player is actually running.
4. Respect what the manager would know (fog of war) when asked to.

## Accessibility & Inclusion

No product-specific requirement given. Inferred: WCAG AA contrast, keyboard focus, reduced motion, readable at phone width.
