---
name: FMCP 27
description: The club's own paperwork, printed in one spot ink on triplicate copy papers and filled in by the tool.
colors:
  ground: "oklch(0.355 0.15 266)"
  ground-text: "oklch(0.975 0.01 266)"
  ground-soft: "oklch(0.87 0.055 266)"
  ground-rule: "oklch(0.52 0.13 266)"
  white: "oklch(0.987 0.004 266)"
  canary: "oklch(0.958 0.068 100)"
  pink: "oklch(0.944 0.028 8)"
  ink: "oklch(0.37 0.16 266)"
  ink-soft: "oklch(0.47 0.12 266)"
  rule: "oklch(0.37 0.16 266 / 0.32)"
  rule-strong: "oklch(0.37 0.16 266)"
  entry: "oklch(0.21 0.03 266)"
  hatch: "oklch(0.37 0.16 266 / 0.32)"
  hatch-edge: "oklch(0.37 0.16 266 / 0.55)"
  mark: "oklch(0.37 0.16 266)"
  code-ground: "oklch(0.37 0.16 266 / 0.12)"
  focus: "oklch(0.86 0.16 96)"
  signal: "oklch(0.630 0.240 28)"
  focus-on-sheet: "oklch(0.37 0.16 266)"
typography:
  display:
    fontFamily: "Archivo, ui-sans-serif, system-ui, -apple-system, Segoe UI, sans-serif"
    fontSize: "clamp(3rem, 16.2vw, 14.75rem)"
    fontWeight: 860
    lineHeight: 0.8
    letterSpacing: "-0.04em"
    fontVariation: "'wdth' 125"
  display-step:
    fontFamily: "Archivo, ui-sans-serif, system-ui, sans-serif"
    fontSize: "clamp(2.75rem, 5.4vw, 4.75rem)"
    fontWeight: 860
    lineHeight: 0.9
    letterSpacing: "-0.035em"
    fontVariation: "'wdth' 125"
  headline:
    fontFamily: "Archivo, ui-sans-serif, system-ui, sans-serif"
    fontSize: "clamp(1.125rem, 1.6vw, 1.375rem)"
    fontWeight: 760
    lineHeight: 1.2
    letterSpacing: "-0.012em"
    fontVariation: "'wdth' 112"
  title:
    fontFamily: "Archivo, ui-sans-serif, system-ui, sans-serif"
    fontSize: "1.0625rem"
    fontWeight: 740
    lineHeight: 1.25
    fontVariation: "'wdth' 106"
  lede:
    fontFamily: "Archivo, ui-sans-serif, system-ui, sans-serif"
    fontSize: "clamp(1.375rem, 2.3vw, 2rem)"
    fontWeight: 600
    lineHeight: 1.16
    letterSpacing: "-0.012em"
    fontVariation: "'wdth' 104"
  step-text:
    fontFamily: "Archivo, ui-sans-serif, system-ui, sans-serif"
    fontSize: "clamp(1.125rem, 1.5vw, 1.3125rem)"
    fontWeight: 500
    lineHeight: 1.36
  entry:
    fontFamily: "Archivo, ui-sans-serif, system-ui, sans-serif"
    fontSize: "clamp(1.125rem, 1.6vw, 1.375rem)"
    fontWeight: 520
    lineHeight: 1.38
    fontVariation: "'wdth' 96"
  question:
    fontFamily: "Archivo, ui-sans-serif, system-ui, sans-serif"
    fontSize: "1.0625rem"
    fontWeight: 500
    lineHeight: 1.4
    fontVariation: "'wdth' 97"
  body:
    fontFamily: "Archivo, ui-sans-serif, system-ui, sans-serif"
    fontSize: "1rem"
    fontWeight: 420
    lineHeight: 1.5
    fontFeature: "'tnum' 1"
  small:
    fontFamily: "Archivo, ui-sans-serif, system-ui, sans-serif"
    fontSize: "0.8125rem"
    fontWeight: 420
    lineHeight: 1.45
  figure:
    fontFamily: "Archivo, ui-sans-serif, system-ui, sans-serif"
    fontSize: "1.25rem"
    fontWeight: 720
    fontVariation: "'wdth' 100"
    fontFeature: "'tnum' 1, 'lnum' 1"
  label:
    fontFamily: "Archivo, ui-sans-serif, system-ui, sans-serif"
    fontSize: "0.75rem"
    fontWeight: 640
    lineHeight: 1.3
    letterSpacing: "0.07em"
    fontVariation: "'wdth' 72"
  form-code:
    fontFamily: "Archivo, ui-sans-serif, system-ui, sans-serif"
    fontSize: "0.875rem"
    fontWeight: 760
    letterSpacing: "0.04em"
    fontVariation: "'wdth' 80"
  nav:
    fontFamily: "Archivo, ui-sans-serif, system-ui, sans-serif"
    fontSize: "0.8125rem"
    fontWeight: 560
    letterSpacing: "0.01em"
    fontVariation: "'wdth' 88"
  wordmark:
    fontFamily: "Archivo, ui-sans-serif, system-ui, sans-serif"
    fontWeight: 800
    letterSpacing: "-0.01em"
    fontVariation: "'wdth' 118"
rounded:
  none: "0px"
spacing:
  frame: "1.5px"
  cell-y: "9px"
  cell-x: "12px"
  field-y: "12px"
  pad: "clamp(14px, 1.8vw, 22px)"
  gap: "clamp(16px, 2.4vw, 32px)"
  band: "clamp(28px, 4vw, 52px)"
  step-top: "clamp(28px, 4vw, 56px)"
  step-bottom: "clamp(36px, 5vw, 72px)"
  copy-offset: "7px"
  wrap: "1320px"
components:
  sheet-white:
    backgroundColor: "{colors.white}"
    textColor: "{colors.entry}"
    rounded: "{rounded.none}"
  sheet-canary:
    backgroundColor: "{colors.canary}"
    textColor: "{colors.entry}"
    rounded: "{rounded.none}"
  sheet-pink:
    backgroundColor: "{colors.pink}"
    textColor: "{colors.entry}"
    rounded: "{rounded.none}"
  sheet-head-code:
    textColor: "{colors.ink}"
    typography: "{typography.form-code}"
    padding: "10px clamp(14px, 1.8vw, 22px)"
  sheet-head-title:
    textColor: "{colors.ink}"
    typography: "{typography.headline}"
    padding: "10px clamp(14px, 1.8vw, 22px)"
  field:
    textColor: "{colors.entry}"
    padding: "12px clamp(14px, 1.8vw, 22px) 14px"
  field-label:
    textColor: "{colors.ink-soft}"
    typography: "{typography.label}"
  figure-cell:
    textColor: "{colors.entry}"
    typography: "{typography.figure}"
    padding: "10px 12px 12px"
  question-cell:
    textColor: "{colors.entry}"
    typography: "{typography.question}"
    padding: "13px clamp(14px, 1.8vw, 22px) 14px"
  roadmap-row:
    textColor: "{colors.entry}"
    typography: "{typography.title}"
    padding: "11px clamp(14px, 1.8vw, 22px)"
  switch-button:
    backgroundColor: "transparent"
    textColor: "{colors.ink}"
    rounded: "{rounded.none}"
    padding: "6px 12px"
    height: "34px"
  switch-button-pressed:
    backgroundColor: "{colors.ink}"
    textColor: "{colors.white}"
  switch-button-hover:
    backgroundColor: "{colors.code-ground}"
  attribute-track:
    backgroundColor: "{colors.mark}"
    width: "52px"
    height: "6px"
  ghost-cell:
    width: "52px"
    height: "26px"
    rounded: "{rounded.none}"
  tick-box:
    size: "15px"
    rounded: "{rounded.none}"
  tick-box-on:
    backgroundColor: "{colors.ink}"
  phase-number:
    textColor: "{colors.ink}"
    size: "26px"
    rounded: "{rounded.none}"
  step-number:
    textColor: "{colors.ground-text}"
    size: "48px"
    rounded: "{rounded.none}"
  step-title:
    textColor: "{colors.ground-text}"
    typography: "{typography.display-step}"
  step-sentence:
    textColor: "{colors.ground-soft}"
    typography: "{typography.step-text}"
  nav-link:
    textColor: "{colors.ground-soft}"
    typography: "{typography.nav}"
    padding: "14px 10px"
  nav-link-hover:
    textColor: "{colors.ground-text}"
  status-box:
    textColor: "{colors.ground-text}"
    rounded: "{rounded.none}"
---

# Design System: FMCP 27

## Overview

**Creative North Star: "The Club's Paperwork"**

The surface is a file of internal club forms laid on a deep ultramarine desk. Every table, figure and example is a form: a white, canary or pink copy sheet ruled in one spot ink, with a form code in the left corner, a title, and a metadata cell on the right. Entries are set in a blue-black near the ink, with tabular figures. The desk itself carries the name, one sentence, the availability box and the three step headings. Everything is drawn: boxes, tick boxes, rules, hatched blanks. Nothing glows, floats or rounds off.

Density is that of a working document. Content sits in ruled cells with consistent internal padding, tables carry exact values, and a blank is drawn as deliberately as a value. Type does its work on Archivo's width axis: condensed for labels and codes, normal for entries, wide for titles, the masthead and the display lines on the desk. Archivo is the only face.

The dark theme is the same forms as night copies: the desk deepens, the papers become low-chroma tinted grounds, and the ink turns pale. The system rejects the dark dashboard with neon, the generic developer-tool landing page, and grey of any kind.

**Key Characteristics:**
- One spot ink (hue 266) for every rule, label, code and mark; secondary text is tinted ink, never grey.
- Three copy papers (white, canary, pink) as the only content surfaces.
- Square corners everywhere (0px).
- No shadows; depth only by one sheet overlapping another.
- Role encoded on the width axis of one variable face.
- Unknown values drawn as hatched ghost cells, ranges drawn as partial fills on a 20-step track.

## Colors

One deep ultramarine ink printed on three triplicate copy papers, laid on a desk of the same hue.

### Primary
- **Spot Ultramarine** (`ink`): every printed element on a sheet: form codes, sheet titles, row headers in the requirements table, phase numbers, tick-box fills, the pressed switch. `rule-strong` and `mark` hold the same value in light mode and separate in dark mode (`rule-strong` at 85% alpha, `mark` slightly lighter at oklch(0.87 0.062 266)). Every token is inside sRGB, so the declared colour is the rendered one.
- **Faded Ink** (`ink-soft`): field labels, table column heads, notes, the key, the club line under a player's name, unfilled roadmap statuses. This is the system's secondary text colour.

### Secondary
- **Canary Copy** (`canary`): the second copy paper. Used for the roadmap sheet (PLN-1), and for the first copy beneath a stacked sheet. Dark: oklch(0.2 0.032 95).
- **Pink Copy** (`pink`): the third copy paper. Used for the two illustration sheets: the scouting shortlist (SCT-1) and the half-time read (MAT-1). Dark: oklch(0.195 0.026 330).

### Tertiary
- **Proof Yellow** (`focus`): the focus ring on the desk, the skip link and text selection. On sheets the ring switches to `focus-on-sheet` (the ink in light mode, Proof Yellow in dark mode).
- **Signal Red** (`signal`): one box in the logo, and the block cursor after the name where the name is set with one. It appears nowhere else. It is the same value in light and dark mode.

### Neutral
- **Desk Ultramarine** (`ground`): page background. Dark: oklch(0.24 0.1 266).
- **Desk Type** (`ground-text`): primary text on the desk: the wordmark, "FMCP" in the name, the lede, the step numbers and step titles.
- **Desk Soft** (`ground-soft`): secondary text on the desk: "27" in the name, the sentence under each step title, nav links at rest, footer text. It also draws the status-box frame and the step-number frame.
- **Desk Rule** (`ground-rule`): the masthead and footer rules, the rule above each step, the status-box inner rules.
- **Top Copy** (`white`): the default sheet paper, used for reference sheets (SAV-1, ASK-1, REQ-1, ERR-404) and for the second copy beneath a stacked sheet. Dark: oklch(0.18 0.035 266).
- **Entry Ink** (`entry`): what is written on the form: answers, request text, questions, table values, figures. Dark: oklch(0.965 0.012 266).
- **Ruling** (`rule`): 1px internal rules between fields, rows and cells (32% ink; 45% in dark mode).
- **Hatch** (`hatch`): diagonal hatching in ghost cells (32% ink; 45% in dark mode). **Hatch Edge** (`hatch-edge`) draws the ghost cell's dashed border at 55% (60% in dark mode), which clears 3:1 against every paper.
- **Ink Wash** (`code-ground`): switch hover only (12% ink; 16% in dark mode). The token keeps the name it had when the site showed code.

### Named Rules
**The One Ink Rule.** Every colour on a sheet is the ink at some strength or the paper beneath it. No second hue is printed on a form. The logo is the one exception: its red box.

**The No Grey Rule.** Secondary text, rules and hatching are tinted ink (hue 266). A neutral grey anywhere is a defect.

**The Copy Paper Rule.** Content surfaces are white, canary or pink and nothing else. Paper colour sorts content by kind (white for reference, canary for work in progress, pink for illustrations); it does not decorate.

## Typography

**Display Font:** Archivo (variable, width 62% to 125%, weight 100 to 900), with ui-sans-serif and system-ui fallbacks
**Body Font:** Archivo

**Character:** One grotesque stretched and squeezed into every role a printed form needs, from a wide black name that runs the width of the page to condensed caps field labels. The stylesheet declares no second face.

### Hierarchy
- **Display** (860, width 125%, three sizes):
  - the name "FMCP 27": clamp(3rem, 16.2vw, 14.75rem), line height 0.8, -0.04em, set on one line. The name is about 5.35em wide, so 16.2vw fills the wrap from phone width up to the 1320px cap. "27" is in desk soft.
  - the three step titles ("You play.", "It reads.", "You ask."): clamp(2.75rem, 5.4vw, 4.75rem), line height 0.9, -0.035em.
  - the 404 numeral: clamp(4rem, 12vw, 9rem), line height 0.85, -0.04em.
  The name and the step titles start 0.045em left of the column edge so the heavy stems align with the text below them.
- **Headline** (760, clamp(1.125rem, 1.6vw, 1.375rem), 1.2, width 112%, -0.012em): sheet titles in the form header, set in ink.
- **Title** (740, 1.0625rem, 1.25, width 106%): roadmap phase names, in entry ink. The availability entry in REQ-1 is a lighter relative (700, 1.0625rem, width 104%).
- **Lede** (600, clamp(1.375rem, 2.3vw, 2rem), 1.16, width 104%, -0.012em, max 26ch, balanced): the one sentence under the name.
- **Step text** (500, clamp(1.125rem, 1.5vw, 1.3125rem), 1.36, max 30ch, desk soft): the one sentence under each step title. The cap widens to 44ch at 1100px and below.
- **Entry** (520, clamp(1.125rem, 1.6vw, 1.375rem), 1.38, width 96%): the written request on a form. The call, the assistant's one-line decision, uses the same size at 660 weight, width 100%, line height 1.3.
- **Question** (500, 1.0625rem, 1.4, width 97%): each question in ASK-1. Answer text also runs at 1.0625rem (line height 1.5), with the instruction in 680 weight.
- **Body** (420, 1rem, 1.5, tabular figures): field text and table cells. Paragraphs in a field cap at 56ch.
- **Small** (420, 0.8125rem, 1.45): notes, the key, the club line under a player's name. Roadmap statuses use the same size at 560 weight (680 when the box is filled). The footer and the secondary line in a requirements cell run at 0.875rem.
- **Figure** (720, 1.25rem, width 100%): numbers in figure strips. The framed numbers are relatives at 760 weight and width 90%: step numbers at 1.375rem, phase numbers at 0.875rem.
- **Label** (640, 0.75rem, 1.3, width 72%, 0.07em, uppercase): field labels, table column heads, header metadata, the status-box heading. 12px is the floor for any text.
- **Form Code** (760, 0.875rem, width 80%, 0.04em): the form code in each sheet's first header cell.
- **Nav** (560, 0.8125rem, width 88%, 0.01em): masthead links. The switch segments are a relative at 620 weight and width 86%.
- **Wordmark** (800, width 118%, -0.01em): "FMCP 27" in the masthead and "fmcp27.com" in the footer.

### Named Rules
**The Width Axis Rule.** Width carries role. Labels, codes, nav and framed numbers are condensed (72% to 90%); entries and body sit near normal (96% to 104%); titles, the wordmark and display run wide (106% to 125%). Do not make a new role with size alone when a width step already says it.

**The Tabular Rule.** Body text sets tabular figures; tables add lining figures. Numbers line up in every column.

## Layout

A centred wrap (max 1320px) with side padding `gap`. The page runs in this order: masthead strip, opening, three steps, one full-width sheet, a pair of sheets, footer.

**Opening.** A 7:5 grid with its items aligned to the bottom. The name spans both columns on one line. Under it the lede sits on the left and the status box sits at the right edge. Padding is clamp(28px, 4.5vw, 60px) above and clamp(36px, 5vw, 68px) below.

**Steps.** An ordered list of three steps, each ruled off above by a 1px desk rule that runs the full width of the page. Inside the wrap each step is a 5:7 grid: the step's words on the left (a 48px framed number, 20px of space, the step title, then one sentence 18px below it) and one sheet on the right. Padding is `step-top` above and `step-bottom` below. From 1101px up the left column is sticky 28px from the top of the viewport, so the words stay beside a tall sheet while it scrolls. Print turns the sticky position off.

**Bands.** Below the steps, content runs in bands (vertical padding `band`; a band that follows the steps or another band drops its top padding). A band holds one full-width sheet or a two-column pair of sheets. From 1101px up the two sheets in a pair stretch to the same height and the roadmap's rows share that height equally.

**Inside a sheet,** everything is a ruled cell. Header cells and fields pad horizontally by `pad` (clamp 14px to 22px); table cells pad 9px 12px with first and last cells widening to `pad`. Multi-column structures inside a sheet (the five-cell figure strip, the two-column question list, the roadmap rows) divide with 1px internal rules and no gaps. The requirements table gives its row headers a column 22% wide.

**Footer.** A 1px desk rule, then a two-column grid: the notes on the left (0.875rem, desk soft, max 60ch) and the site name on the right in the Wordmark role.

**Breakpoints.**
- 1100px and below: the opening becomes one column and the status box moves to the left edge; each step becomes one column with its words above its sheet; pairs become one column.
- 900px and below: the question list becomes one column; the masthead nav wraps under the wordmark.
- 760px and below: header metadata drops to its own row under the code and title, ruled off above and left-aligned; the figure strip becomes three cells over two; each requirements row stacks its header above its value; the footer and the 404 page become one column; the copies beneath a stacked sheet offset by 6px and 12px.
- 600px and below: the scouting table becomes one ruled block per player on a 12-column grid. The name takes eight columns, potential takes four with the label "Potential" above it, and the four attributes take three columns each on the next row, each labelled with its column name. The column heads stay available to screen readers and the table no longer scrolls sideways.
- 520px and below: each roadmap row puts its status under the phase name.
- Coarse pointers: switch segments are 44px tall.
- Below 1.5 device pixels per CSS pixel: `frame` is 2px.

## Elevation & Depth

The system is flat. There is no box-shadow anywhere. Depth exists only as paper overlap: a stacked sheet carries two copies beneath it, each a full sheet with its own `frame` border in strong ink and a copy-paper fill (canary, then white), offset down and right by 7px and 14px (6px and 12px at 760px and below). The copies sit on z-index -1 and -2 inside a stacking host.

### Named Rules
**The Overlap Only Rule.** Depth is one sheet lying on another, drawn flat. A copy beneath a sheet is a real sheet: copy-paper fill and ruled border, never a solid ink block, blur or gradient. The build uses it once, on MAT-1, the sheet beside the third step.

## Shapes

Square corners throughout (0px), the focus outline included. Outer frames are 1.5px (`frame`) in strong ink, 2px on screens below 1.5 device pixels per CSS pixel so the frame stays heavier than the ruling; internal rules are 1px in ruling. Small drawn marks follow the same language: 48px step numbers on the desk framed at `frame` in desk soft; 26px phase numbers and 15px tick boxes framed at 1.5px in strong ink; the 18px box in the status box framed at 1.5px in desk type; the half-done tick box filled on a 135-degree diagonal; the 22px form mark beside the wordmark, a ruled square holding one filled cell and one dashed cell.

## Components

### Sheets
The form is the container for every table, figure and example.
- **Corner Style:** square (0px).
- **Background:** one copy paper (white, canary or pink).
- **Border:** `frame` in strong ink.
- **Header:** a three-cell grid: form code (Form Code type, ruled off on the right), title (Headline type), metadata cell (Label type, ruled off on the left, right-aligned). The header is ruled off from the body at `frame`. The metadata cell holds one label, or the view switch on SCT-1. ERR-404 has no metadata cell. Every sheet carries a code. Codes in use: SAV-1, SCT-1, MAT-1, ASK-1, PLN-1, REQ-1, ERR-404.
- **Fields:** a Label over its entry, padded 12px `pad` 14px, ruled off at 1px; the last field drops its rule.

### Step words
The left column of each step, set on the desk. A 48px square framed in desk soft holds the step number (760, 1.375rem, width 90%, desk type). Below it the step title is in display style, and below that one sentence is in Step text. The number is the ordinal of an ordered list and is hidden from screen readers; the heading carries "Step 1:" as hidden text.

### Figure strip
Five ruled cells, each a Label over a Figure, padded 10px 12px 12px. Values sit on one baseline even when a label wraps. When the strip sits directly in a sheet it is ruled off below at 1px. SAV-1 opens with one; MAT-1 places one between the question and the answer. At 760px and below it becomes three cells over two.

### Answer parts
MAT-1 shows a full exchange: the question in Entry type, a figure strip, then the answer. The answer opens with **the call**: the assistant's decision in one line, in entry ink at the Entry size, 660 weight, capped at 34ch. One instruction follows at 1.0625rem with the instruction itself in 680 weight. A note in faded ink at the Small size closes the answer.

### Question list
ASK-1 holds six questions as a ruled list, two across. Each question sits in its own cell (13px `pad` 14px) in entry ink in the Question role. A 1px rule separates the two columns and each row; the last row drops its rule. At 900px and below the list becomes one column.

### Roadmap rows
PLN-1 holds four ruled rows. Each row is a three-column grid: a 26px framed phase number, the phase name in the Title role, and a tick-box status on the right. Rows pad 11px `pad`. At 520px and below the status moves under the phase name.

### Buttons (view switch)
The only button in the system is a segmented switch in the metadata cell of SCT-1's header.
- **Shape:** square, 1px strong ink frame, segments divided by 1px strong ink.
- **Rest:** transparent, ink text, 620 weight, width 86%, 0.8125rem, 6px 12px, min height 34px.
- **Pressed:** ink fill, paper-coloured text (reads the host sheet's paper).
- **Hover / Active:** an ink wash on unpressed segments; a 1px press-down on active. 34px tall for a mouse, 44px on coarse pointers. The switch pulls in 3px above and below so the header keeps its height. Colour transitions at 120ms ease-out, removed under reduced motion.
- **Behaviour:** hidden without JavaScript, so the sheet stays in Manager view. Changing the view writes the new view's description to a status region for screen readers.

### Attribute value and track
A 1-to-20 value set over a 52px by 6px track ruled into quarters. The fill spans the known range in `mark`. An exact value is a single step at full strength; a range fills its span at 55% opacity and sets the number at 560 weight. In the key the track shortens to 40px and carries no number.

Values are set by class, because the site's content security policy allows no inline styles. `lo-15 hi-15` places an exact 15; `lo-9 hi-12` places a range. The stylesheet declares one class per value the page uses (`lo-6` to `lo-17`, `hi-6` to `hi-18`). A new value needs its class added to the stylesheet.

Potential uses the same track in two forms. In Manager view it is a star range: the track is ruled into five stars and filled in half-star steps, set by `sl-` and `sh-` classes (`sl-8 sh-9` is 4 to 4½ stars). In Full read it is potential ability out of 200: the track has no ruling and fills from the left to the value, set by a `pa-` class (`pa-167`).

### Ghost cell
An unknown or hidden value is drawn as a cell: 52px by 26px with a 1px dashed hatch-edge border and 135-degree hatch lines every 6px. In the key it scales to 26px by 14px. In SCT-1 the Consistency and Big matches columns hold ghost cells in Manager view and values in Full read.

### Key
A row under the scouting table, ruled off above at 1px, in faded ink at the Small size. It shows one exact track, one range track and one ghost cell, each with its meaning beside it. The items wrap with gaps of 8px by 22px.

### Tables
Full-width, collapsed, 1px ruling between rows, last row unruled. Column heads use the Label role over a `frame` rule in strong ink and do not wrap. A vertical 1px rule separates column groups. A table wider than its sheet scrolls sideways inside a focusable region with a thin scrollbar in ruling.
- **Scouting shortlist (SCT-1):** a player column, a potential column and four attribute columns. The player's name is 620 weight in entry ink with age and club below it at the Small size in faded ink. Potential and attribute cells are centred (minimum 84px and 74px wide). Cells do not wrap.
- **Requirements (REQ-1):** row headers in ink, 680 weight, width 96%, in a column 22% wide. Cells pad 12px above and below and align to the top. A secondary line in a cell is 0.875rem in faded ink.

### Tick boxes and status
- **Tick box:** 15px square, 1.5px strong ink frame. On: ink fill with a drawn paper-coloured check, entry-coloured label at 680. Half: diagonal ink fill. Off: empty, faded-ink label.
- **Status box (on the desk):** `frame` in desk soft, max 36ch, a Label header in desk soft ruled off below, a 44px tick column holding an 18px box, and a 560-weight statement. The box stays empty until the product is available, matching the roadmap where a filled box means built.

### Navigation
The masthead strip sits on the desk over a 1px desk rule, min height 52px: wordmark left (800, width 118%, with the 22px logo: eleven boxes in a 4-4-2, drawn on the 22px grid as 4px boxes with 2px gaps, one forward in Signal Red), four section links right in the Nav role in desk soft, turning desk type with a 1px underline on hover. At 900px and below the list wraps under the wordmark; each link is at least 44px tall there. Link colour eases over 120ms on hover. Print hides the nav, the switch and the skip link.

### Links and focus
Links inherit colour with a 1px underline at 0.2em offset, thickening to 2px on hover. Focus is a 2px outline at 3px offset in Proof Yellow on the desk and in `focus-on-sheet` inside a sheet. Scroll regions and the switch draw the ring inside their own edge so no side falls onto the desk or the pressed segment. Hover styles apply only to fine pointers.

### Motion
The view swap re-inks changed values: 220ms from 25% opacity and a 1.5px blur to clear, on cubic-bezier(0.16, 1, 0.3, 1). The two view descriptions share one grid cell, so the sheet keeps its height when the view changes. Under reduced motion the re-ink animation, smooth anchor scrolling and the 120ms colour transitions are all off.

## Do's and Don'ts

### Do:
- **Do** put every table, figure and example on a sheet with a form code and a title in its header.
- **Do** keep the desk to the masthead, the name, the lede, the status box, the step words and the footer.
- **Do** choose the paper by kind: white for reference, canary for work in progress, pink for illustrations.
- **Do** draw secondary text in faded ink (`ink-soft`) on sheets and desk soft (`ground-soft`) on the desk.
- **Do** divide inside a sheet with 1px ruling and frame the sheet at 1.5px.
- **Do** draw unknown values as ghost cells and ranges as partial fills on the 20-step track.
- **Do** set attribute, star and potential values by class; the content security policy blocks inline styles.
- **Do** set role on Archivo's width axis: condensed caps at width 72% for labels, wide at 106% to 125% for titles and display.
- **Do** keep the focus ring visible on both desk and sheet, swapping to `focus-on-sheet` inside sheets.

### Don't:
- **Don't** use a neutral grey for text, rules or backgrounds.
- **Don't** add a box-shadow, glow or blur for depth; overlap flat sheets instead.
- **Don't** round a corner.
- **Don't** print a second accent hue on a sheet; Proof Yellow is for focus and selection only, and Signal Red is for the logo's one box.
- **Don't** show an unknown as a dash, blank or "N/A".
- **Don't** let a field label float above a section heading on the desk; labels belong inside a ruled cell of a form.
