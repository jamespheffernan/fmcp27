#!/usr/bin/env bash
# Create and drive the FMCP 27 Windows development machine on AWS EC2, from the Mac.
#
#   vm.sh check            signed-in account, GPU quota, and the machine if it exists
#   vm.sh quota [vcpus]    request the GPU quota (default 8 vCPUs: one g4dn.xlarge or .2xlarge)
#   vm.sh up               create the machine (billing starts); does nothing if it exists
#   vm.sh start | stop     start or stop it (a stopped machine bills for its disk only)
#   vm.sh status           state, type, address
#   vm.sh ssh [command]    ssh in as Administrator, or run one PowerShell command
#   vm.sh run <command>    run PowerShell through AWS Systems Manager (no SSH needed)
#   vm.sh copy <a> <b>     copy a file from the Mac to a path on the machine
#   vm.sh push             bring the machine's repo to the Mac's current commit
#   vm.sh desktop          Remote Desktop window (--set-password first chooses the password)
#   vm.sh idle-stop [h]    stop the machine after h hours under 4% CPU (default 2)
#   vm.sh allow-me         point the firewall at this Mac's current public address
#   vm.sh destroy          terminate the machine and delete its disk (asks first)
#
# Sign in first with `aws login`. Settings (environment):
#   FMCP_VM_REGION  eu-west-2       FMCP_VM_TYPE     g4dn.xlarge
#   FMCP_VM_DISK_GB 200             FMCP_VM_IMAGE    Windows Server 2022 (latest AWS image)

set -euo pipefail

REGION="${FMCP_VM_REGION:-eu-west-2}"
TYPE="${FMCP_VM_TYPE:-g4dn.xlarge}"
DISK_GB="${FMCP_VM_DISK_GB:-200}"
IMAGE_PARAMETER="${FMCP_VM_IMAGE:-/aws/service/ami-windows-latest/Windows_Server-2022-English-Full-Base}"
NAME="fmcp27-windows"
ROLE="fmcp27-windows-role"
KEY="${FMCP_VM_KEY:-$HOME/.ssh/fmcp27_windows_ed25519}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
GPU_QUOTA_NAME="Running On-Demand G and VT instances"
GPU_QUOTA_CODE="L-DB2E81BA"

export AWS_DEFAULT_REGION="$REGION" AWS_PAGER=""

die() { echo "vm.sh: $*" >&2; exit 1; }

instance_field() {  # the machine's value for a JMESPath expression; empty when there is none
  aws ec2 describe-instances \
    --filters "Name=tag:Name,Values=$NAME" \
              "Name=instance-state-name,Values=pending,running,stopping,stopped" \
    --query "Reservations[].Instances[] | [0].$1" --output text 2>/dev/null | grep -v '^None$' || true
}

instance_id() { instance_field InstanceId; }

require_instance() {
  local id; id="$(instance_id)"
  [ -n "$id" ] || die "no machine named $NAME in $REGION; run: vm.sh up"
  echo "$id"
}

my_address() {
  local ip; ip="$(dig +short -4 myip.opendns.com @resolver1.opendns.com | tail -1)"
  [[ "$ip" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]] || die "could not find this Mac's public address"
  echo "$ip"
}

gpu_quota() {  # prints "<code> <value>"
  # By code: with text output a query over the paged list is applied to each page.
  aws service-quotas get-service-quota --service-code ec2 --quota-code "$GPU_QUOTA_CODE" \
    --query 'Quota.[QuotaCode,Value]' --output text
}

security_group() {
  aws ec2 describe-security-groups --filters "Name=group-name,Values=$NAME" \
    --query 'SecurityGroups[0].GroupId' --output text 2>/dev/null | grep -v '^None$' || true
}

cmd_check() {
  aws sts get-caller-identity --query '{account:Account,identity:Arn}' --output table
  read -r code value <<<"$(gpu_quota)"
  echo "GPU quota ($GPU_QUOTA_NAME, $code): ${value%.*} vCPUs in $REGION"
  aws service-quotas list-requested-service-quota-change-history-by-quota \
    --service-code ec2 --quota-code "$code" \
    --query 'RequestedQuotas[].[Created,DesiredValue,Status]' --output text 2>/dev/null \
    | sed 's/^/  request: /' || true
  cmd_status || true
}

cmd_quota() {
  local want="${1:-8}" code value
  read -r code value <<<"$(gpu_quota)"
  if [ "${value%.*}" -ge "$want" ]; then echo "quota is already ${value%.*} vCPUs"; return; fi
  aws service-quotas request-service-quota-increase --service-code ec2 --quota-code "$code" \
    --desired-value "$want" --query 'RequestedQuota.[Id,Status,DesiredValue]' --output text
}

ensure_key() {
  [ -f "$KEY" ] || ssh-keygen -q -t ed25519 -N '' -C "$NAME" -f "$KEY"
}

ensure_role() {
  if ! aws iam get-role --role-name "$ROLE" >/dev/null 2>&1; then
    aws iam create-role --role-name "$ROLE" --assume-role-policy-document '{
      "Version":"2012-10-17","Statement":[{"Effect":"Allow",
      "Principal":{"Service":"ec2.amazonaws.com"},"Action":"sts:AssumeRole"}]}' >/dev/null
    # Systems Manager for remote commands; S3 read for the NVIDIA driver AWS publishes.
    aws iam attach-role-policy --role-name "$ROLE" \
      --policy-arn arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore
    aws iam attach-role-policy --role-name "$ROLE" \
      --policy-arn arn:aws:iam::aws:policy/AmazonS3ReadOnlyAccess
  fi
  if ! aws iam get-instance-profile --instance-profile-name "$ROLE" >/dev/null 2>&1; then
    aws iam create-instance-profile --instance-profile-name "$ROLE" >/dev/null
    aws iam add-role-to-instance-profile --instance-profile-name "$ROLE" --role-name "$ROLE"
    sleep 10  # a new profile is not usable by run-instances straight away
  fi
}

ensure_security_group() {
  local group; group="$(security_group)"
  if [ -z "$group" ]; then
    local vpc
    vpc="$(aws ec2 describe-vpcs --filters Name=is-default,Values=true \
           --query 'Vpcs[0].VpcId' --output text)"
    [ "$vpc" != "None" ] || die "no default VPC in $REGION"
    group="$(aws ec2 create-security-group --group-name "$NAME" --vpc-id "$vpc" \
             --description 'FMCP 27 Windows development machine' --query GroupId --output text)"
  fi
  echo "$group"
}

cmd_allow_me() {  # SSH and Remote Desktop from this Mac's address only
  local group ip; group="$(ensure_security_group)"; ip="$(my_address)"
  local old
  old="$(aws ec2 describe-security-groups --group-ids "$group" \
         --query 'SecurityGroups[0].IpPermissions' --output json)"
  [ "$old" = "[]" ] || aws ec2 revoke-security-group-ingress --group-id "$group" \
    --ip-permissions "$old" >/dev/null
  for port in 22 3389; do
    aws ec2 authorize-security-group-ingress --group-id "$group" --protocol tcp \
      --port "$port" --cidr "$ip/32" >/dev/null
  done
  echo "ports 22 and 3389 open to $ip only"
}

cmd_up() {
  local id; id="$(instance_id)"
  if [ -n "$id" ]; then echo "machine exists: $id"; cmd_status; return; fi
  ensure_key; ensure_role
  local group image userdata
  group="$(ensure_security_group)"; cmd_allow_me
  image="$(aws ssm get-parameter --name "$IMAGE_PARAMETER" --query Parameter.Value --output text)"
  userdata="$(mktemp)"
  python3 - "$HERE/first_boot.ps1" "$KEY.pub" >"$userdata" <<'PY'
import sys
script = open(sys.argv[1], encoding='utf-8').read()
key = open(sys.argv[2], encoding='utf-8').read().strip()
assert '__FMCP_PUBLIC_KEY__' in script
print('<powershell>\n' + script.replace('__FMCP_PUBLIC_KEY__', key) + '\n</powershell>')
PY
  id="$(aws ec2 run-instances --image-id "$image" --instance-type "$TYPE" \
        --iam-instance-profile "Name=$ROLE" --security-group-ids "$group" \
        --block-device-mappings "[{\"DeviceName\":\"/dev/sda1\",\"Ebs\":{\"VolumeSize\":$DISK_GB,\"VolumeType\":\"gp3\",\"DeleteOnTermination\":true}}]" \
        --metadata-options 'HttpTokens=required' \
        --tag-specifications "ResourceType=instance,Tags=[{Key=Name,Value=$NAME}]" \
                             "ResourceType=volume,Tags=[{Key=Name,Value=$NAME}]" \
        --user-data "file://$userdata" --query 'Instances[0].InstanceId' --output text)"
  rm -f "$userdata"
  echo "created $id ($TYPE, $image); waiting for it to run"
  aws ec2 wait instance-running --instance-ids "$id"
  cmd_status
  echo "first boot takes several minutes; follow it with: vm.sh run 'Get-Content C:\\fmcp\\first_boot.log'"
}

cmd_status() {
  local id; id="$(instance_id)"
  [ -n "$id" ] || { echo "no machine named $NAME in $REGION"; return 1; }
  aws ec2 describe-instances --instance-ids "$id" --output table \
    --query 'Reservations[].Instances[].{id:InstanceId,state:State.Name,type:InstanceType,address:PublicIpAddress,launched:LaunchTime}'
}

cmd_start() {
  local id; id="$(require_instance)"
  aws ec2 start-instances --instance-ids "$id" >/dev/null
  aws ec2 wait instance-running --instance-ids "$id"
  cmd_status
}

cmd_stop() {
  local id; id="$(require_instance)"
  aws ec2 stop-instances --instance-ids "$id" >/dev/null
  aws ec2 wait instance-stopped --instance-ids "$id"
  cmd_status
}

address() {
  local address; address="$(instance_field PublicIpAddress)"
  [ -n "$address" ] || die "the machine has no public address (is it running?)"
  echo "$address"
}

# The address changes on every start, so host keys are kept per machine in their own file.
SSH_OPTIONS=(-o IdentitiesOnly=yes -o StrictHostKeyChecking=accept-new
             -o "UserKnownHostsFile=$HOME/.ssh/fmcp27_windows_known_hosts"
             -o "HostKeyAlias=$NAME" -o LogLevel=ERROR)

cmd_ssh() {  # a leading -t asks for a terminal (for a command that prompts)
  local tty=()
  if [ "${1:-}" = "-t" ]; then tty=(-t); shift; fi
  ssh -i "$KEY" "${SSH_OPTIONS[@]}" ${tty[@]+"${tty[@]}"} "Administrator@$(address)" "$@"
}

cmd_copy() {  # vm.sh copy <file on the Mac> <path on the machine, forward slashes>
  [ $# -eq 2 ] || die "usage: vm.sh copy <local file> <remote path>"
  scp -q -i "$KEY" "${SSH_OPTIONS[@]}" "$1" "Administrator@$(address):$2"
}

cmd_push() {  # bring C:\fmcp\repo to the Mac's current commit (committed work only; the repo has no remote)
  local repo work base head range
  repo="$(git -C "$HERE" rev-parse --show-toplevel)"
  head="$(git -C "$repo" rev-parse HEAD)"
  base="$(cmd_ssh 'git -C C:/fmcp/repo rev-parse HEAD' | tr -d '\r\n')"
  if [ "$base" = "$head" ]; then
    cmd_ssh 'cd C:\fmcp\repo; git reset -q --hard HEAD; git log --oneline -1'
    return
  fi
  # Send only the new commits when the machine's commit is one the Mac has.
  if git -C "$repo" merge-base --is-ancestor "$base" "$head" 2>/dev/null; then range="$base..HEAD"; else range="HEAD"; fi
  work="$(mktemp -d)"
  git -C "$repo" bundle create -q "$work/push.bundle" $range
  cmd_copy "$work/push.bundle" C:/fmcp/downloads/push.bundle
  rm -r "$work"
  cmd_ssh 'cd C:\fmcp\repo; git fetch -q --force C:\fmcp\downloads\push.bundle HEAD:refs/remotes/mac/head; git reset -q --hard refs/remotes/mac/head; git log --oneline -1'
}

cmd_desktop() {  # Remote Desktop window on this Mac. Passwords are typed by the person, never stored.
  command -v sdl-freerdp >/dev/null || die "install the client first: brew install freerdp"
  local target; target="$(address)"
  if [ "${1:-}" = "--set-password" ]; then
    echo "Choose a Windows password for Administrator. Windows wants 8 or more characters with"
    echo "upper case, lower case and a digit. It is typed twice and not shown."
    cmd_ssh -t 'net user Administrator *' || die "the password was not set; run this again"
  fi
  # The password is asked for here in the terminal, before connecting. The client's own
  # sign-in window has three fields and sends an empty password if Return is pressed early.
  # The account is a local one, so its domain is the machine's own name. A refused logon is
  # asked for again, up to three times.
  local machine attempt log="$HOME/.ssh/fmcp27_windows_desktop.log"
  machine="$(cmd_ssh hostname | tr -d '\r\n')"
  [ -n "$machine" ] || die "the machine did not give its name over SSH"
  for attempt in 1 2 3; do
    echo "Opening the desktop of $target. Type the Windows password for Administrator (not shown), then Return."
    sdl-freerdp "/v:$target" /u:Administrator "/d:$machine" /from-stdin:force /cert:tofu \
      /dynamic-resolution /size:1600x1000 /scale-desktop:100 +clipboard >"$log" 2>&1 || true
    # The client's exit status does not tell a refused logon from a closed session; its log does.
    grep -q LOGON_FAILURE "$log" || return 0
    echo "Windows refused that password (attempt $attempt of 3). If an error window is open, close it."
  done
  die "three refused passwords; set a new one with: vm.sh desktop --set-password"
}

cmd_idle_stop() {  # stop the machine when its CPU has averaged under 4% for N hours (default 2)
  local id hours="${1:-2}"; id="$(require_instance)"
  aws iam create-service-linked-role --aws-service-name events.amazonaws.com >/dev/null 2>&1 || true
  aws cloudwatch put-metric-alarm --alarm-name "$NAME-idle-stop" \
    --alarm-description "Stop $NAME after $hours idle hours" \
    --namespace AWS/EC2 --metric-name CPUUtilization --dimensions "Name=InstanceId,Value=$id" \
    --statistic Average --period 900 --evaluation-periods "$((hours * 4))" \
    --threshold 4 --comparison-operator LessThanThreshold --treat-missing-data notBreaching \
    --alarm-actions "arn:aws:automate:$REGION:ec2:stop"
  aws cloudwatch describe-alarms --alarm-names "$NAME-idle-stop" \
    --query 'MetricAlarms[0].[AlarmName,StateValue,EvaluationPeriods,Threshold]' --output text
}

cmd_run() {  # PowerShell through Systems Manager; prints stdout, then stderr, exits with its status
  [ $# -ge 1 ] || die "usage: vm.sh run <powershell command>"
  local id parameters command status
  id="$(require_instance)"
  parameters="$(python3 -c 'import json,sys; print(json.dumps({"commands":[sys.argv[1]]}))' "$*")"
  command="$(aws ssm send-command --instance-ids "$id" --document-name AWS-RunPowerShellScript \
             --parameters "$parameters" --query Command.CommandId --output text)"
  for _ in $(seq 1 180); do
    status="$(aws ssm get-command-invocation --command-id "$command" --instance-id "$id" \
              --query Status --output text 2>/dev/null || echo Pending)"
    case "$status" in Pending|InProgress|Delayed) sleep 2 ;; *) break ;; esac
  done
  aws ssm get-command-invocation --command-id "$command" --instance-id "$id" \
    --query StandardOutputContent --output text
  aws ssm get-command-invocation --command-id "$command" --instance-id "$id" \
    --query StandardErrorContent --output text >&2
  [ "$status" = "Success" ] || die "command ended as $status"
}

cmd_destroy() {
  local id answer; id="$(require_instance)"
  read -r -p "Terminate $id and delete its disk? Type the machine name to confirm: " answer
  [ "$answer" = "$NAME" ] || die "not confirmed"
  aws ec2 terminate-instances --instance-ids "$id" >/dev/null
  aws ec2 wait instance-terminated --instance-ids "$id"
  echo "terminated $id"
}

action="${1:-}"; [ $# -gt 0 ] && shift
case "$action" in
  check) cmd_check ;;
  quota) cmd_quota "$@" ;;
  up) cmd_up ;;
  start) cmd_start ;;
  stop) cmd_stop ;;
  status) cmd_status ;;
  ssh) cmd_ssh "$@" ;;
  copy) cmd_copy "$@" ;;
  push) cmd_push ;;
  desktop) cmd_desktop "$@" ;;
  idle-stop) cmd_idle_stop "$@" ;;
  run) cmd_run "$@" ;;
  allow-me) cmd_allow_me ;;
  destroy) cmd_destroy ;;
  *) sed -n '2,17p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 2 ;;
esac
