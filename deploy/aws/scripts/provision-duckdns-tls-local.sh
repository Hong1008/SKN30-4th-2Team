#!/usr/bin/env bash
set -euo pipefail
umask 077

usage() {
  cat <<'EOF'
Usage: provision-duckdns-tls-local.sh <acme-email> [--profile <aws-profile>] [--region <aws-region>] [--timeout-seconds <seconds>]

WorkShield EC2 managed node에 DuckDNS DNS-01 Certbot hook과 갱신 timer를 설치하고
workshield.duckdns.org 인증서를 발급합니다. DuckDNS 토큰은 인스턴스 role로
Secrets Manager에서만 조회하며, local shell·SSM 로그·명령 인자에 출력하지 않습니다.
EOF
}

email="${1:-}"
[[ -n "$email" ]] || { usage >&2; exit 2; }
shift
profile="${AWS_PROFILE:-4th-student}"
region="${AWS_REGION:-ap-northeast-2}"
timeout_seconds=360
while (($#)); do
  case "$1" in
    --profile) profile="${2:-}"; shift 2 ;;
    --region) region="${2:-}"; shift 2 ;;
    --timeout-seconds) timeout_seconds="${2:-}"; shift 2 ;;
    --help|-h) usage; exit 0 ;;
    *) usage >&2; exit 2 ;;
  esac
done
[[ "$email" =~ ^[^[:space:]@]+@[^[:space:]@]+\.[^[:space:]@]+$ ]] || { printf '%s\n' 'error: valid ACME email is required.' >&2; exit 2; }
[[ "$region" =~ ^[a-z]{2}-[a-z]+-[0-9]+$ && "$timeout_seconds" =~ ^[1-9][0-9]*$ ]] || { usage >&2; exit 2; }

aws_args=(--profile "$profile" --region "$region" --no-cli-pager)
instance_id="$(aws ssm describe-instance-information "${aws_args[@]}" --filters Key=tag:Project,Values=WorkShield --query 'InstanceInformationList[0].InstanceId' --output text)"
[[ "$instance_id" != "None" && "$instance_id" != "" ]] || { printf '%s\n' 'error: no managed WorkShield instance found.' >&2; exit 1; }

payload="$(mktemp)"
trap 'rm -f "$payload"' EXIT
python3 - "$payload" "$email" "$region" <<'PY'
import base64
import json
import shlex
import sys

payload_path, email, region = sys.argv[1:]
remote_script = r'''#!/usr/bin/env bash
set -euo pipefail

email="${1:?ACME email is required}"
region="${2:?AWS region is required}"
domain="workshield.duckdns.org"
duckdns_domain="workshield"

dnf install -y certbot
command -v curl >/dev/null
command -v python3 >/dev/null
command -v aws >/dev/null
install -d -m 0700 /opt/workshield/certificates

cat >/usr/local/sbin/workshield-duckdns-auth <<'HOOK'
#!/usr/bin/env bash
set -euo pipefail
token="$(aws secretsmanager get-secret-value --region ap-northeast-2 --secret-id /workshield/prod/duckdns --query SecretString --output text | python3 -c 'import json, sys; print(json.load(sys.stdin)["DUCKDNS_TOKEN"])')"
[[ -n "$token" && -n "${CERTBOT_VALIDATION:-}" ]] || exit 1
response="$(curl --fail --silent --show-error --get 'https://www.duckdns.org/update' --data-urlencode 'domains=workshield' --data-urlencode "token=${token}" --data-urlencode "txt=${CERTBOT_VALIDATION}" --data-urlencode 'verbose=true')"
[[ "$response" == OK* ]] || { printf '%s\n' 'DuckDNS TXT update was rejected.' >&2; exit 1; }
# DuckDNS authoritative update and recursive resolver propagation 시간을 보수적으로 기다린다.
sleep 75
HOOK
chmod 0700 /usr/local/sbin/workshield-duckdns-auth

cat >/usr/local/sbin/workshield-duckdns-cleanup <<'HOOK'
#!/usr/bin/env bash
set -euo pipefail
token="$(aws secretsmanager get-secret-value --region ap-northeast-2 --secret-id /workshield/prod/duckdns --query SecretString --output text | python3 -c 'import json, sys; print(json.load(sys.stdin)["DUCKDNS_TOKEN"])')"
curl --fail --silent --show-error --get 'https://www.duckdns.org/update' --data-urlencode 'domains=workshield' --data-urlencode "token=${token}" --data-urlencode 'clear=true' >/dev/null
HOOK
chmod 0700 /usr/local/sbin/workshield-duckdns-cleanup

cat >/usr/local/sbin/workshield-install-origin-certificate <<'HOOK'
#!/usr/bin/env bash
set -euo pipefail
install -d -m 0700 /opt/workshield/certificates
install -m 0600 /etc/letsencrypt/live/workshield.duckdns.org/fullchain.pem /opt/workshield/certificates/fullchain.pem
install -m 0600 /etc/letsencrypt/live/workshield.duckdns.org/privkey.pem /opt/workshield/certificates/privkey.pem
if command -v docker >/dev/null && docker ps --format '{{.Names}}' | grep -qx 'workshield-prod-nginx-1'; then
  docker kill --signal=HUP workshield-prod-nginx-1
fi
HOOK
chmod 0700 /usr/local/sbin/workshield-install-origin-certificate

certbot certonly --manual --preferred-challenges dns \
  --manual-auth-hook /usr/local/sbin/workshield-duckdns-auth \
  --manual-cleanup-hook /usr/local/sbin/workshield-duckdns-cleanup \
  --deploy-hook /usr/local/sbin/workshield-install-origin-certificate \
  --manual-public-ip-logging-ok --non-interactive --agree-tos \
  --keep-until-expiring -m "$email" -d "$domain"
/usr/local/sbin/workshield-install-origin-certificate

cat >/etc/systemd/system/workshield-certbot-renew.service <<'UNIT'
[Unit]
Description=Renew WorkShield origin TLS certificate

[Service]
Type=oneshot
ExecStart=/usr/bin/certbot renew --quiet --deploy-hook /usr/local/sbin/workshield-install-origin-certificate
UNIT
cat >/etc/systemd/system/workshield-certbot-renew.timer <<'UNIT'
[Unit]
Description=Daily WorkShield origin TLS certificate renewal check

[Timer]
OnCalendar=*-*-* 03:17:00
Persistent=true
RandomizedDelaySec=30m

[Install]
WantedBy=timers.target
UNIT
systemctl daemon-reload
systemctl enable --now workshield-certbot-renew.timer
'''
encoded = base64.b64encode(remote_script.encode()).decode()
commands = [
    'set -euo pipefail',
    "install -d -m 0700 /opt/workshield/bootstrap",
    f"printf '%s' {shlex.quote(encoded)} | base64 -d > /opt/workshield/bootstrap/provision-duckdns-tls.sh",
    'chmod 0700 /opt/workshield/bootstrap/provision-duckdns-tls.sh',
    f"/opt/workshield/bootstrap/provision-duckdns-tls.sh {shlex.quote(email)} {shlex.quote(region)}",
]
with open(payload_path, 'w', encoding='utf-8') as out:
    json.dump({'commands': commands}, out)
PY

command_id="$(aws ssm send-command "${aws_args[@]}" \
  --document-name AWS-RunShellScript \
  --targets "Key=instanceids,Values=${instance_id}" \
  --parameters "file://${payload}" \
  --comment 'Provision WorkShield DuckDNS origin TLS' \
  --query 'Command.CommandId' --output text)"
printf 'TLS provisioning command submitted: %s\n' "$command_id"

deadline=$((SECONDS + timeout_seconds))
while (( SECONDS < deadline )); do
  status="$(aws ssm get-command-invocation "${aws_args[@]}" --command-id "$command_id" --instance-id "$instance_id" --query Status --output text 2>/dev/null || true)"
  case "$status" in
    Success) printf 'origin TLS certificate provisioned: %s\n' "$command_id"; exit 0 ;;
    Failed|Cancelled|TimedOut|Cancelling)
      aws ssm get-command-invocation "${aws_args[@]}" --command-id "$command_id" --instance-id "$instance_id" --query '{status:Status,error:StandardErrorContent}' --output json >&2 || true
      exit 1 ;;
    *) sleep 5 ;;
  esac
done
printf 'error: TLS provisioning timed out; inspect SSM command %s.\n' "$command_id" >&2
exit 1
