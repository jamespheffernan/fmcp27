#!/bin/sh
# Runs on the rented Mac, in a terminal the person types into (mac.sh signin). For when the Mac's
# sign-in screen rejects a password typed through Screen Sharing: the password is read here with
# echo off, checked against the account, and written as the Mac's automatic sign-in secret
# (/etc/kcpassword, root only), so the desktop opens at the next start-up with nothing typed.
# It is not printed or logged. The check hands it to dscl as an argument, which other processes
# on this Mac could see for an instant; the Mac is rented for this one job and has one user.
# `sysadminctl -autologin` is not used: on macOS 27.2 it echoed the password and failed
# (SACSetAutoLoginPassword error 22). dscl reading the password from a pipe is not used either:
# one try that way was rejected and the next try, with the argument form, was accepted; whether
# the pipe or the typing was at fault that time is not known.
set -u
trap 'stty echo 2>/dev/null' EXIT INT TERM
try=0
while [ "$try" -lt 3 ]; do
  try=$(( try + 1 ))
  printf "Rented Mac's ec2-user password (not shown), try %s of 3: " "$try"
  stty -echo 2>/dev/null
  IFS= read -r pw || exit 1
  stty echo 2>/dev/null
  echo
  if [ -n "$pw" ] && /usr/bin/dscl /Local/Default -authonly ec2-user "$pw" >/dev/null 2>&1; then
    echo "CHECK=accepted"
    printf '%s' "$pw" | sudo /usr/bin/python3 -I -c '
import os, subprocess, sys
pw = sys.stdin.buffer.read()
key = (0x7D, 0x89, 0x52, 0x23, 0xD2, 0xBC, 0xDD, 0xEA, 0xA3, 0xB9, 0x1F)
padded = pw + b"\0" * (12 - len(pw) % 12)
blob = bytes(b ^ key[i % len(key)] for i, b in enumerate(padded))
fd = os.open("/etc/kcpassword", os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
os.write(fd, blob); os.close(fd); os.chown("/etc/kcpassword", 0, 0)
subprocess.run(["/usr/bin/defaults", "write", "/Library/Preferences/com.apple.loginwindow",
                "autoLoginUser", "ec2-user"], check=True)
print("AUTOLOGIN=set  (takes effect when the Mac restarts)")
'
    exit $?
  fi
  echo "CHECK=rejected  (the Mac does not hold the password as typed here)"
done
exit 1
