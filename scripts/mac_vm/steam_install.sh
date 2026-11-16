#!/bin/sh
# Runs on the rented Mac: put Steam in /Applications from Valve's own installer image
# and turn on Screen Sharing (reached only through the SSH tunnel; the firewall leaves
# port 5900 closed). Signing in to Steam and the account password are the person's.
set -eu
# Steam's Mac app is Intel-only (14 November 2026), and a new EC2 Mac has no Rosetta: Steam then
# fails to open with error -10669. FMCP_ROSETTA=1 installs it, which accepts Apple's Rosetta
# licence, so the person has to have said yes to that.
if ! /usr/bin/arch -x86_64 /usr/bin/true 2>/dev/null; then
    if [ "${FMCP_ROSETTA:-0}" = 1 ]; then
        sudo /usr/sbin/softwareupdate --install-rosetta --agree-to-license 2>&1 | tail -n 1
    else
        echo "Rosetta: not installed; Steam will not open until it is (FMCP_ROSETTA=1 after the person agrees)"
    fi
fi
if [ ! -d /Applications/Steam.app ]; then
    image="$(mktemp -d)/steam.dmg"
    /usr/bin/curl -fsSL -o "$image" https://cdn.cloudflare.steamstatic.com/client/installer/steam.dmg
    mount="$(/usr/bin/hdiutil attach -nobrowse -readonly "$image" | /usr/bin/awk -F'\t' '/\/Volumes\//{print $NF}' | tail -1)"
    /usr/bin/codesign --verify --deep --strict "$mount/Steam.app"
    /usr/bin/codesign -dvv "$mount/Steam.app" 2>&1 | /usr/bin/grep -E '^(Authority=Developer ID|TeamIdentifier)'
    /usr/bin/ditto "$mount/Steam.app" /Applications/Steam.app
    /usr/bin/hdiutil detach -quiet "$mount"
fi
echo "Steam: $(/usr/bin/defaults read /Applications/Steam.app/Contents/Info CFBundleShortVersionString 2>/dev/null || echo installed)"
sudo /bin/launchctl enable system/com.apple.screensharing
sudo /bin/launchctl load -w /System/Library/LaunchDaemons/com.apple.screensharing.plist 2>/dev/null || true
echo "Screen Sharing: $(sudo /bin/launchctl print system/com.apple.screensharing >/dev/null 2>&1 && echo on || echo off)"
/usr/bin/csrutil status
