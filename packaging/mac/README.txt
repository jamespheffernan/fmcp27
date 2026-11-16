FMCP 27 for Mac
===============

FMCP 27 lets an AI assistant read your running Football Manager 27 career.

You need: a Mac with Apple Silicon, Football Manager 27 on Steam, and an
assistant that takes MCP servers (Claude, Codex, Pi or another).


Install
-------

1. Open Terminal (in Applications > Utilities) and paste this line:

     sh ~/Downloads/FMCP27/install.sh

   If you unzipped the download somewhere else, use that folder in the line.
   The installer copies FMCP 27 to the folder FMCP27 in your home folder and
   downloads Python for its own use into that folder. It needs the internet
   for a few minutes and no password. It ends by showing the lines for steps
   2 and 3.

2. In Steam, open Football Manager 27 > Properties > General > Launch Options
   and paste the line the installer showed. The installer also put it on the
   clipboard. It is this, with your own user name in the path:

     /Users/YOUR-NAME/FMCP27/fm_launch.sh %command%

   Use the full path. Steam does not understand "~" here: the game then fails
   to start with "OS Error 260".

3. Add FMCP 27 to your assistant. In Terminal:

     Claude Code:  claude mcp add --scope user fmcp27 -- ~/FMCP27/fmcp27-mcp
     Codex:        codex mcp add fmcp27 -- ~/FMCP27/fmcp27-mcp
     Pi:           pi mcp add fmcp27 -- ~/FMCP27/fmcp27-mcp

   For the Claude desktop app, open Settings > Developer > Edit Config and add
   this server, with your own user name in the path:

     "mcpServers": {
       "fmcp27": { "command": "/Users/YOUR-NAME/FMCP27/fmcp27-mcp" }
     }

   Any other assistant: the server is the command ~/FMCP27/fmcp27-mcp, with no
   arguments.

4. Start Football Manager 27 from Steam as usual, load your save, and ask your
   assistant a question about it.


Why Terminal
------------

FMCP 27's programs are signed by Turf Terrace Ltd and notarized by Apple.
The installer is a Terminal script, so run it from Terminal as shown above; it
works without changing any security setting. The installer clears the download
mark from its own copy so that the game can load it.


Check that it works
-------------------

With the game running, in Terminal:

     ~/FMCP27/fmcp27-doctor

It says whether the game was started with the launch line.

The first question on a save takes longer than later ones, because FMCP 27
reads the whole save once. After a game update the first read can take about
25 minutes.


Update
------

Quit the game. Download the new package, unzip it and run its install.sh the
same way.


Remove
------

1. In Steam, delete the line from Launch Options.
2. Remove FMCP 27 from your assistant (for example: claude mcp remove fmcp27).
3. Delete the folder FMCP27 in your home folder, and the folder
   Library/Caches/FMCP27 in your home folder if it exists.

FMCP 27 changes nothing in the game's files or in Steam.


What it does on your Mac
------------------------

The launch line starts the game with one small library loaded. The library
only answers read requests from the FMCP 27 programs in this folder, on this
Mac, for your user. It writes nothing to the game or to your save, and it
sends nothing over the network. Reading your save is free.

FMCP 27 is an unofficial tool. It is not affiliated with or endorsed by
Sports Interactive or SEGA. Football Manager is a trademark of its owners.

fmcp27.com
