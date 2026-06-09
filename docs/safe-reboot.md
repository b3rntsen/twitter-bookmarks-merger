# Safe Reboot Runbook — twitter-bookmarks EC2 host

**Host:** `i-0759ffea3fd2fffba` @ `13.49.172.180` (eu-north-1), Amazon Linux 2023, t3.medium.
**Root volume:** `vol-0a46d7a2885811639`, device `/dev/xvda`.
The Elastic IP and the EBS volume **persist across reboot/stop-start — a reboot never destroys data.**

## ⚠️ Why this box needs a runbook
It co-hosts the **newblades** capture stack (WireGuard `wg0` + transparent mitmproxy).
On **2026-06-07** a reboot blackholed **all inbound TCP** (22/80/443/8000) for ~15 min;
a second reboot cleared it. During a blackhole there is **no remote shell** — SSM has no
IAM role, and port 22 (incl. EC2 Instance Connect) is dropped. Until newblades is hardened
(see findings), treat every reboot as risky.

## Best mitigation — out-of-band shell (SSM) ✅ ENABLED
**SSM Session Manager** uses *outbound* 443 to AWS, so it works even when all inbound is
dropped. Enabled and verified 2026-06-07 — `aws_iam_role_policy_attachment.ssm_core`
attaches `AmazonSSMManagedInstanceCore`; registration + a live command round-trip confirmed.

Get a shell even during an inbound blackhole:
- Interactive: `aws ssm start-session --target i-0759ffea3fd2fffba`
- One-off: `aws ssm send-command --region eu-north-1 --instance-ids i-0759ffea3fd2fffba --document-name AWS-RunShellScript --parameters 'commands=["<cmd>"]'`

This is the **first-line recovery** for a blackhole (see step 1 below). SSM only fails if
newblades also breaks *outbound* 443/routing — then fall back to reboot / rescue-volume.

### Using the non-root operator (preferred over root)
`start-session` above works as root, but prefer the dedicated, MFA-scoped IAM user
`twitter-bookmarks-ssm-operator` — it can *only* start a session on this instance, and only
with MFA. One-time setup (as root, in the console): IAM → Users → that user → Security
credentials → **assign an MFA device** and **create an access key**. Then:
```
aws configure --profile ssm-op            # operator key id + secret, region eu-north-1
aws sts get-session-token --profile ssm-op \
    --serial-number <operator-mfa-arn> --token-code <6-digit>   # policy REQUIRES mfa
# export the returned AccessKeyId/SecretAccessKey/SessionToken, then:
aws ssm start-session --region eu-north-1 --target i-0759ffea3fd2fffba   # needs session-manager-plugin
```
Every session is recorded to CloudWatch `/ssm/twitter-bookmarks/session-logs`.

## Pre-reboot checklist
1. (Optional, belt-and-suspenders) snapshot the root volume:
   `aws ec2 create-snapshot --volume-id vol-0a46d7a2885811639 --description "pre-reboot" --region eu-north-1`
2. Capture the current healthy network state for comparison, on the box:
   `sudo iptables-save > /tmp/ipt.good; ip rule > /tmp/iprule.good; ip route > /tmp/iproute.good`
3. Containers are `restart: always` and docker is enabled, so they auto-recover on a healthy boot.

## Reboot
```
aws ec2 reboot-instances --instance-ids i-0759ffea3fd2fffba --region eu-north-1
```

## Verify — do NOT assume (ping is useless: the SG has no ICMP rule)
Poll from your laptop until ports return, then check the app:
```
for p in 22 80 443; do nc -z -G4 -w5 13.49.172.180 $p && echo "$p OPEN"; done
curl -sS -o /dev/null -w "%{http_code}\n" https://twitter.dethele.com   # expect 302 -> Google login
```
On the box: `nproc; free -h; docker ps`

## If it comes back blackholed (instance "running" + 2/2 checks, but every port times out)
First confirm the OS is actually up (rules out fsck/panic — both were ruled out on 06-07):
```
aws ec2 get-console-screenshot --instance-id i-0759ffea3fd2fffba --region eu-north-1 --query ImageData --output text | base64 -D > /tmp/console.png
aws ec2 get-console-output    --instance-id i-0759ffea3fd2fffba --region eu-north-1 --latest --output text | tail -40
```
Recovery, in order of preference:
1. **SSM** (enabled 2026-06-07) — `aws ssm start-session --target i-0759ffea3fd2fffba`, then flush
   the rogue rules and stop the newblades capture units:
   ```
   sudo iptables -t nat -F; sudo iptables -t mangle -F; sudo iptables -F
   sudo ip rule flush
   sudo ip rule add pref 0     from all lookup local
   sudo ip rule add pref 32766 from all lookup main
   sudo ip rule add pref 32767 from all lookup default
   ```
   Re-verify ports.
2. **Second reboot** (cleared it on 06-07): `aws ec2 reboot-instances ...`, then poll again.
3. **Rescue-volume** (reliable, ~20–30 min) if still dead:
   1. `aws ec2 stop-instances --instance-ids i-0759ffea3fd2fffba` (wait for `stopped`)
   2. `aws ec2 detach-volume --volume-id vol-0a46d7a2885811639`
   3. Launch a temp AL2023 rescue instance in the **same AZ**; attach the volume as `/dev/sdf`
   4. On the rescue box: mount it, then neutralize the boot breakage — disable the newblades
      capture/WireGuard systemd units (remove their `*.wants` symlinks under the mounted
      `etc/systemd/system/`) and/or clear persisted rules (`etc/sysconfig/iptables`,
      `etc/nftables`, any `wg-quick` PostUp scripts)
   5. Unmount, detach from rescue, reattach to `i-0759ffea3fd2fffba` as `/dev/xvda`
   6. `aws ec2 start-instances --instance-ids i-0759ffea3fd2fffba`, then poll

## After recovery
- Re-verify the site (302) and that the bookmark sync resumed (self-heals via
  `start_bookmark_sync` on container startup).
- The durable fix lives in **newblades** — until that lands, this risk remains on every reboot.
