# FMCP 27

Ask an AI assistant about your running Football Manager 27 career.

FMCP 27 connects Football Manager to Claude, Codex, Pi and other assistants through the Model Context Protocol (MCP). It reads the career you have open, including changes you have not saved yet, so answers can use your actual squad, tactics, finances and match data.

[Website and examples](https://fmcp27.com) · [Download for Mac](https://fmcp27.com/download/FMCP27-mac.zip) · [Updates on X](https://x.com/TurfTerrace)

## What you can ask

- “Who can cover the bench for our next match?”
- “Where are we losing possession?”
- “Find a midfielder who fits our budget and this role.”
- “How did our passing change in the second half?”
- “What do our wage commitments look like next season?”

The reader exposes both named tools and a queryable snapshot of the loaded career. Coverage varies by game build and by the data FM retains. Missing or unsupported data stays explicit.

## Install

You need **an Apple Silicon Mac, Football Manager 27 on Steam, and an assistant that supports MCP**. Windows support is in development.

1. [Download the Mac package](https://fmcp27.com/download/FMCP27-mac.zip) and unzip it.
2. Run its installer in Terminal:

   ```sh
   sh ~/Downloads/FMCP27/install.sh
   ```

3. Paste the full launch line the installer gives you into Football Manager 27 → Properties → General → Launch Options in Steam.
4. Add the server to your assistant. For example:

   ```sh
   # Codex
   codex mcp add fmcp27 -- ~/FMCP27/fmcp27-mcp

   # Claude Code
   claude mcp add --scope user fmcp27 -- ~/FMCP27/fmcp27-mcp
   ```

5. Start the game from Steam, load your career and ask a question.

The [installation guide](packaging/mac/README.txt) covers other assistants, troubleshooting, updates and removal. The first read takes longer while the reader builds its local snapshot. Game updates can require new build data; the reader refuses unsupported builds rather than guessing addresses.

## How it works

A small native library lets the local reader access the running game's memory. The Python MCP server turns that data into tools an assistant can call. The standard download reads the game and does not edit it or your save. Your assistant receives the tool results you ask it to use.

This repository also contains an optional training edit extension in `fm_live_write/`. It is separate from the reader, disabled unless explicitly loaded through `FMCP_EXTENSIONS`, and excluded from the standard Mac download.

## Develop

The reader requires macOS, Xcode Command Line Tools, Python 3.12+ and [uv](https://docs.astral.sh/uv/). Clone the repository and install the pinned dependencies:

```sh
git clone https://github.com/jamespheffernan/fmcp27.git
cd fmcp27
uv sync --locked --extra test
sh scripts/build_helper.sh
sh scripts/build_fast_reader.sh
sh scripts/build_attach_lib.sh
sh scripts/build_vm_accel.sh
sh scripts/build_ui_accel.sh
```

Register the source checkout with an MCP client using its absolute path:

```sh
codex mcp add fmcp27-dev -- /bin/sh "$PWD/scripts/run_mcp.sh"
```

The source launcher speaks MCP over stdin/stdout. It is not an interactive shell. Development builds need a supported installed game and matching address data; see [game updates](docs/GAME_UPDATE.md). For a ready-to-use installation, use the Mac download above.

## Repository guide

| Directory | Contents |
| --- | --- |
| `fm_live_mcp/` | Python reader, MCP server, database queries and match tools |
| `native/` | Native memory transport and acceleration helpers |
| `adviser/` | Pi adviser, football guides, tactic-file tools and reports |
| `fm_live_write/` | Optional training edit extension |
| `tests/` | Reader tests and bounded fixtures |
| `scripts/` | Build, verification and packaging commands |
| `packaging/mac/` | Mac installer and distribution files |
| `tools/match-report/` | Match report renderer |
| `site/` | Source for fmcp27.com |
| `docs/` | Technical reference, supported builds and testing notes |

Start with the [reader reference](docs/READER_REFERENCE.md), [testing guide](docs/TESTING.md), [reader release notes](CHANGELOG.md) or [contribution guide](CONTRIBUTING.md). The adviser is a separate Pi integration; its setup requirements are in [adviser/README.md](adviser/README.md).

The public repository starts from a reviewed source snapshot. Local evidence, session transcripts, credentials, game saves, generated downloads and private development history are excluded. Some research checks need local captures or installed game resources and cannot run from the public checkout alone.

## Feedback

[Open an issue](https://github.com/jamespheffernan/fmcp27/issues) with your macOS version, game build, assistant and steps to reproduce the problem. Remove private paths, credentials and personal data from logs before sharing them. Do not upload your save or game files.

FMCP 27 is an unofficial tool. It is not affiliated with or endorsed by Sports Interactive or SEGA. Football Manager is a trademark of its owners.
