#!/bin/bash
# Baseline SSH hardening for the production EC2 host. Idempotent — safe to re-run.
# Run on the instance: sudo bash harden-host.sh
#
# - No root SSH login, no X11 forwarding, fewer auth attempts per connection.
#   (ec2-user and nbdeploy log in with keys; root never does.)
# - fail2ban sshd jail. Port 22 stays open to the world because GitHub Actions
#   deploys (nbdeploy) come from rotating Azure IPs.

set -euo pipefail

cat > /etc/ssh/sshd_config.d/10-hardening.conf <<'EOF'
PermitRootLogin no
X11Forwarding no
MaxAuthTries 3
EOF
chmod 600 /etc/ssh/sshd_config.d/10-hardening.conf
sshd -t
systemctl reload sshd

dnf -y -q install fail2ban
# The package defaults to firewalld actions, but firewalld is not running here.
cat > /etc/fail2ban/jail.d/sshd.local <<'EOF'
[sshd]
enabled   = true
banaction = nftables-multiport
backend  = systemd
maxretry = 5
findtime = 10m
bantime  = 1h
EOF
systemctl enable --now fail2ban
systemctl restart fail2ban
sleep 2

sshd -T | grep -E '^(permitrootlogin|x11forwarding|maxauthtries) '
fail2ban-client status sshd | grep -E 'Currently|Total'
