#!/usr/bin/env bash
# A rented Apple Silicon Mac with default security settings, for checking the Mac
# download where System Integrity Protection is on (this project's own Mac has a
# custom SIP configuration, so it cannot show that).
#
#   mac.sh check            sign-in, the Mac host quota and its request, what exists
#   mac.sh quota            ask AWS for a quota of one Mac host
#   mac.sh up               rent the host, start the Mac, set the automatic release
#   mac.sh status           host, machine and the scheduled release
#   mac.sh ssh [command]    a shell on the Mac, or one command
#   mac.sh copy <file> <path on the Mac>
#   mac.sh allow-me         point the firewall at this Mac's current public address
#   mac.sh prepare [zip]    after up: run the stand-in check, install Steam and the download
#   mac.sh desktop [--set-password]   the rented Mac's screen, through an SSH tunnel
#   mac.sh signin           if its sign-in screen rejects the password: sign in automatically
#   mac.sh real-game        with the game running there and a save loaded: attach, save, first query
#   mac.sh release          end it now: terminate the machine, release the host when AWS allows
#
# Cost: an EC2 Mac runs on a Dedicated Host that is billed from allocation until
# release, with a 24-hour minimum, whether or not a machine is running on it. After
# the machine is terminated AWS scrubs the host (one to three hours) and it cannot be
# released until that ends. `up` therefore schedules, inside AWS, the termination at
# 20 hours and release attempts from 24 hours on, so the host is given back even if
# no session on this Mac is alive. Every hour past 24 is billed at the hourly rate.
#
#   FMCP_MAC_HOURS  hours after allocation at which the machine is terminated (default 20);
#                   set it higher, with `up` or `guard`, to keep a host past its first day
#   FMCP_MAC_REGION eu-west-1 (Ireland; London offers Intel Macs only)
#   FMCP_MAC_TYPE   mac2.metal (M1)       FMCP_MAC_ZONE  eu-west-1a
#   FMCP_MAC_IMAGE  the newest AWS macOS image for FMCP_MAC_OS (default 27)

set -euo pipefail

REGION="${FMCP_MAC_REGION:-eu-west-1}"
TYPE="${FMCP_MAC_TYPE:-mac2.metal}"
ZONE="${FMCP_MAC_ZONE:-${REGION}a}"
OS_MAJOR="${FMCP_MAC_OS:-27}"
HOURS="${FMCP_MAC_HOURS:-20}"
NAME="fmcp27-mac"
ROLE="fmcp27-mac-release-role"
KEY="${FMCP_MAC_KEY:-$HOME/.ssh/fmcp27_mac_ed25519}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
QUOTA_CODE="${FMCP_MAC_QUOTA:-L-5D8DADF5}"   # Running Dedicated mac2 Hosts
SSH_OPTIONS=(-o StrictHostKeyChecking=accept-new -o UserKnownHostsFile="$HOME/.ssh/fmcp27_mac_known_hosts"
             -o ConnectTimeout=15 -o ServerAliveInterval=30)

export AWS_DEFAULT_REGION="$REGION" AWS_PAGER=""

die() { echo "mac.sh: $*" >&2; exit 1; }
text() { grep -v '^None$' || true; }

host_field() {
  aws ec2 describe-hosts --filter "Name=tag:Name,Values=$NAME" \
    --query "Hosts[?State!='released' && State!='released-permanent-failure'] | [0].$1" --output text 2>/dev/null | text
}
instance_field() {
  aws ec2 describe-instances --filters "Name=tag:Name,Values=$NAME" \
      "Name=instance-state-name,Values=pending,running,stopping,stopped,shutting-down" \
    --query "Reservations[].Instances[] | [0].$1" --output text 2>/dev/null | text
}
security_group() {
  aws ec2 describe-security-groups --filters "Name=group-name,Values=$NAME" \
    --query 'SecurityGroups[0].GroupId' --output text 2>/dev/null | text
}
my_address() {
  local ip; ip="$(dig +short -4 myip.opendns.com @resolver1.opendns.com | tail -1)"
  [[ "$ip" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]] || die "could not find this Mac's public address"
  echo "$ip"
}
schedules() {
  aws scheduler list-schedules --name-prefix "$NAME-" \
    --query 'Schedules[].Name' --output text 2>/dev/null | tr '\t' '\n' | text
}

cmd_check() {
  aws sts get-caller-identity --query 'Arn' --output text | sed -E 's/[0-9]{12}/<account>/'
  echo "Mac host quota ($QUOTA_CODE) in $REGION: $(aws service-quotas get-service-quota --service-code ec2 \
      --quota-code "$QUOTA_CODE" --query 'Quota.Value' --output text)"
  aws service-quotas list-requested-service-quota-change-history-by-quota --service-code ec2 \
    --quota-code "$QUOTA_CODE" --query 'RequestedQuotas[].[Created,DesiredValue,Status,CaseId]' \
    --output text 2>/dev/null | sed 's/^/  request: /' || true
  cmd_status || true
}

cmd_quota() {
  aws service-quotas request-service-quota-increase --service-code ec2 --quota-code "$QUOTA_CODE" \
    --desired-value 1 --query 'RequestedQuota.[Id,Status,DesiredValue]' --output text
}

ensure_security_group() {
  local group; group="$(security_group)"
  if [ -z "$group" ]; then
    local vpc
    vpc="$(aws ec2 describe-vpcs --filters Name=is-default,Values=true --query 'Vpcs[0].VpcId' --output text)"
    [ "$vpc" != "None" ] || die "no default VPC in $REGION"
    group="$(aws ec2 create-security-group --group-name "$NAME" --vpc-id "$vpc" \
             --description 'FMCP 27 default-SIP Mac check' --query GroupId --output text)"
  fi
  echo "$group"
}

cmd_allow_me() {  # SSH from this Mac's address only; Screen Sharing goes through the SSH tunnel
  local group ip old; group="$(ensure_security_group)"; ip="$(my_address)"
  old="$(aws ec2 describe-security-groups --group-ids "$group" --query 'SecurityGroups[0].IpPermissions' --output json)"
  [ "$old" = "[]" ] || aws ec2 revoke-security-group-ingress --group-id "$group" --ip-permissions "$old" >/dev/null
  aws ec2 authorize-security-group-ingress --group-id "$group" --protocol tcp --port 22 --cidr "$ip/32" >/dev/null
  echo "port 22 open to $ip only"
}

ensure_release_role() {  # lets the AWS scheduler end this one machine and give back this one host
  if ! aws iam get-role --role-name "$ROLE" >/dev/null 2>&1; then
    aws iam create-role --role-name "$ROLE" --assume-role-policy-document '{
      "Version":"2012-10-17","Statement":[{"Effect":"Allow",
      "Principal":{"Service":"scheduler.amazonaws.com"},"Action":"sts:AssumeRole"}]}' >/dev/null
    sleep 10  # a new role is not assumable straight away
  fi
  aws iam get-role --role-name "$ROLE" --query Role.Arn --output text
}

cmd_guard() {  # (re)create the scheduled termination and release attempts from the host's allocation time
  local host id allocated role account; host="$(host_field HostId)"; id="$(instance_field InstanceId)"
  [ -n "$host" ] || die "no host named $NAME"
  allocated="$(host_field AllocationTime)"; role="$(ensure_release_role)"
  account="$(aws sts get-caller-identity --query Account --output text)"
  # The role may act on this host and this machine only, named by identifier.
  aws iam put-role-policy --role-name "$ROLE" --policy-name release --policy-document "{
    \"Version\":\"2012-10-17\",\"Statement\":[{\"Effect\":\"Allow\",
    \"Action\":[\"ec2:TerminateInstances\",\"ec2:ReleaseHosts\"],
    \"Resource\":[\"arn:aws:ec2:$REGION:$account:dedicated-host/$host\"${id:+,\"arn:aws:ec2:$REGION:$account:instance/$id\"}]}]}"
  for name in $(schedules); do aws scheduler delete-schedule --name "$name" >/dev/null; done
  python3 - "$allocated" "$host" "${id:-}" "$role" "$NAME" "$HOURS" <<'PY' | while IFS=$'\t' read -r name when target input; do
import json, sys
from datetime import datetime, timedelta, timezone
allocated, host, instance, role, name = sys.argv[1:6]
keep = float(sys.argv[6])   # hours after allocation at which the machine is terminated
start = datetime.fromisoformat(allocated.replace('Z', '+00:00')).astimezone(timezone.utc)
rows = []
if instance:
    rows.append((f'{name}-terminate', keep, 'terminateInstances', {'InstanceIds': [instance]}))
# A release cannot succeed before 24 hours, nor while AWS scrubs the host after the termination.
tries = {h for h in (24.1, 24.5, 25, 26, 28, 32, 40, 48) if h >= keep + 1}
tries |= {keep + d for d in (1.5, 2, 3, 4, 6, 12, 24) if keep + d > 24.1}
for hours in sorted(tries):
    rows.append((f'{name}-release-{str(hours).replace(".", "h")}', hours, 'releaseHosts', {'HostIds': [host]}))
now = datetime.now(timezone.utc)
for label, hours, action, body in rows:
    when = start + timedelta(hours=hours)
    if when <= now + timedelta(minutes=2):
        continue
    print(label, when.strftime('%Y-%m-%dT%H:%M:%S'), f'arn:aws:scheduler:::aws-sdk:ec2:{action}', json.dumps(body), sep='\t')
PY
    aws scheduler create-schedule --name "$name" --schedule-expression "at($when)" \
      --schedule-expression-timezone UTC --flexible-time-window Mode=OFF --action-after-completion DELETE \
      --target "$(python3 -c 'import json,sys; print(json.dumps({"Arn":sys.argv[1],"RoleArn":sys.argv[2],"Input":sys.argv[3]}))' "$target" "$role" "$input")" \
      >/dev/null
    echo "scheduled $name at ${when}Z"
  done
}

cmd_up() {
  local host id group image
  [ -f "$KEY" ] || ssh-keygen -q -t ed25519 -N '' -C "$NAME" -f "$KEY"
  aws ec2 describe-key-pairs --key-names "$NAME" >/dev/null 2>&1 \
    || aws ec2 import-key-pair --key-name "$NAME" --public-key-material "fileb://$KEY.pub" >/dev/null
  group="$(ensure_security_group)"; cmd_allow_me
  host="$(host_field HostId)"
  if [ -z "$host" ]; then
    host="$(aws ec2 allocate-hosts --instance-type "$TYPE" --availability-zone "$ZONE" --quantity 1 \
            --auto-placement off --tag-specifications "ResourceType=dedicated-host,Tags=[{Key=Name,Value=$NAME}]" \
            --query 'HostIds[0]' --output text)"
    echo "allocated host $host ($TYPE, $ZONE); billing runs from now for at least 24 hours"
  fi
  cmd_guard   # release attempts exist before anything else can go wrong
  id="$(instance_field InstanceId)"
  if [ -z "$id" ]; then
    image="${FMCP_MAC_IMAGE:-$(aws ec2 describe-images --owners amazon \
      --filters "Name=name,Values=amzn-ec2-macos-$OS_MAJOR.*" Name=architecture,Values=arm64_mac Name=state,Values=available \
      --query 'sort_by(Images,&CreationDate)[-1].ImageId' --output text)}"
    [ "$image" != "None" ] || die "no macOS $OS_MAJOR image in $REGION"
    id="$(aws ec2 run-instances --image-id "$image" --instance-type "$TYPE" --key-name "$NAME" \
          --security-group-ids "$group" --placement "Tenancy=host,HostId=$host" \
          --metadata-options 'HttpTokens=required' \
          --tag-specifications "ResourceType=instance,Tags=[{Key=Name,Value=$NAME}]" \
                               "ResourceType=volume,Tags=[{Key=Name,Value=$NAME}]" \
          --query 'Instances[0].InstanceId' --output text)"
    echo "started $id from $image; a Mac takes 6 to 15 minutes before SSH answers"
    cmd_guard   # now with the machine's termination
  fi
  aws ec2 wait instance-running --instance-ids "$id"
  cmd_status
}

cmd_status() {
  local host; host="$(host_field HostId)"
  if [ -z "$host" ]; then echo "no host named $NAME in $REGION"; else
    echo "host $host: $(host_field State), allocated $(host_field AllocationTime)"; fi
  local id; id="$(instance_field InstanceId)"
  if [ -z "$id" ]; then echo "no machine named $NAME"; else
    echo "machine $id: $(instance_field State.Name), address $(instance_field PublicIpAddress)"; fi
  local name
  for name in $(schedules); do
    echo "  $(aws scheduler get-schedule --name "$name" --query '[Name,ScheduleExpression]' --output text)"
  done
  [ -n "$host$id" ]
}

address() {
  local ip; ip="$(instance_field PublicIpAddress)"
  [ -n "$ip" ] || die "the machine has no public address (not running?)"
  echo "$ip"
}

cmd_ssh() {
  local tty=(); if [ "${1:-}" = "-t" ]; then tty=(-t); shift; fi
  ssh -i "$KEY" "${SSH_OPTIONS[@]}" ${tty[@]+"${tty[@]}"} "ec2-user@$(address)" "$@"
}

cmd_copy() {
  [ $# -eq 2 ] || die "usage: mac.sh copy <file on this Mac> <path on the rented Mac>"
  scp -q -i "$KEY" "${SSH_OPTIONS[@]}" "$1" "ec2-user@$(address):$2"
}

cmd_prepare() {  # after `up`: everything the real-game stage needs except the person's Steam sign-in
  local root zip end; root="$(cd "$HERE/../.." && pwd)"; zip="${1:-$root/site/public/download/FMCP27-mac.zip}"
  [ -f "$zip" ] || die "no package at $zip; run: sh scripts/package_mac.sh"
  end=$(( $(date +%s) + 1500 ))
  until cmd_ssh true 2>/dev/null; do   # a new Mac takes 6 to 15 minutes before SSH answers
    [ "$(date +%s)" -lt "$end" ] || die "the Mac did not answer SSH in 25 minutes"
    sleep 30
  done
  cmd_ssh 'mkdir -p check/scripts check/native Downloads'
  cmd_copy "$zip" check/FMCP27-mac.zip
  cmd_copy "$root/scripts/test_package_mac.py" check/scripts/test_package_mac.py
  cmd_copy "$root/native/fmcp_attach_target.c" check/native/fmcp_attach_target.c
  cmd_copy "$root/native/fmcp_attach_target.entitlements" check/native/fmcp_attach_target.entitlements
  cmd_copy "$HERE/steam_install.sh" check/steam_install.sh
  cmd_copy "$HERE/real_game_check.py" check/real_game_check.py
  # The stand-in check first: it fails unless SIP is at its default and task_for_pid is refused.
  cmd_ssh 'cd check && FMCP27_TEST_REQUIRE_SIP=1 FMCP27_TEST_DIR=$HOME/check /usr/bin/python3 scripts/test_package_mac.py FMCP27-mac.zip'
  cmd_ssh 'sh check/steam_install.sh && /usr/bin/ditto -x -k check/FMCP27-mac.zip Downloads && FMCP27_NO_CLIPBOARD=1 /bin/sh Downloads/FMCP27/install.sh | tail -3'
  echo "ready for the person: mac.sh desktop --set-password, then Steam sign-in, the game, the launch option"
}

cmd_signin() {  # when the Mac's sign-in screen rejects the password typed through Screen Sharing
  # Run it in a terminal the person types into. Seen 14 November 2026 on macOS 27.2: a password
  # that Screen Sharing's own prompt and dscl both accepted was rejected at the sign-in screen,
  # cause not found. The helper makes the Mac sign in by itself; then restart and reconnect.
  cmd_copy "$HERE/desktop_signin.sh" check/desktop_signin.sh
  cmd_ssh -t 'sh check/desktop_signin.sh' || die "the password was not accepted"
  cmd_ssh 'sudo shutdown -r now' || true
  echo "restarting; in a minute run: mac.sh desktop"
}

cmd_real_game() {  # with the game running on the rented Mac and a save loaded
  # The in-game library registers its Mach service in the desktop session, which a plain SSH
  # shell cannot look up, so the check is run in that session's bootstrap context.
  cmd_ssh 'sudo launchctl asuser "$(id -u)" sudo -u ec2-user "$HOME/FMCP27/.venv/bin/python" -W ignore "$HOME/check/real_game_check.py"'
}

cmd_desktop() {  # the Mac's screen in Screen Sharing on this Mac. Passwords are typed by the person, never stored.
  if [ "${1:-}" = "--set-password" ]; then
    echo "Choose a password for the rented Mac's ec2-user account (asked twice). Screen Sharing asks for it next."
    cmd_ssh -t 'sudo passwd ec2-user'
  fi
  local port=5927
  pkill -f "ssh .*-L $port:localhost:5900" 2>/dev/null || true
  ssh -f -N -i "$KEY" "${SSH_OPTIONS[@]}" -o ExitOnForwardFailure=yes -L "$port:localhost:5900" "ec2-user@$(address)"
  echo "Screen Sharing opens on localhost:$port; sign in as ec2-user with the password you chose"
  open "vnc://ec2-user@localhost:$port"
}

cmd_release() {
  local id host; id="$(instance_field InstanceId)"; host="$(host_field HostId)"
  if [ -n "$id" ]; then
    aws ec2 terminate-instances --instance-ids "$id" --query 'TerminatingInstances[0].CurrentState.Name' --output text
  fi
  [ -n "$host" ] || { echo "no host to release"; return; }
  local out
  out="$(aws ec2 release-hosts --host-ids "$host" --query '[Successful[0],Unsuccessful[0].Error.Message]' --output text)"
  echo "release $host: $out"
  case "$out" in
    "$host"*) for name in $(schedules); do aws scheduler delete-schedule --name "$name" >/dev/null; done
              echo "released; scheduled attempts removed" ;;
    *) echo "not released yet (24-hour minimum, or the host is still being scrubbed); the scheduled attempts stay in place" ;;
  esac
}

case "${1:-}" in
  check) cmd_check ;;
  quota) cmd_quota ;;
  up) cmd_up ;;
  guard) cmd_guard ;;
  status) cmd_status ;;
  ssh) shift; cmd_ssh "$@" ;;
  copy) shift; cmd_copy "$@" ;;
  allow-me) cmd_allow_me ;;
  prepare) shift; cmd_prepare "$@" ;;
  real-game) cmd_real_game ;;
  desktop) shift; cmd_desktop "$@" ;;
  signin) cmd_signin ;;
  release) cmd_release ;;
  *) sed -n '2,27p' "$0" | sed 's/^# \{0,1\}//'; exit 2 ;;
esac
