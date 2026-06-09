# Rebuild From Scratch — twitter.dethele.com (production)

Goal: recreate the entire production host from nothing and reach the same running state.
Everything in this repo is reproducible IaC; the items under **Not in git** must be supplied
from a secure backup.

## Host facts
- AWS account `209556414107` (wemobilize.dk), region `eu-north-1`.
- EC2 `i-0759ffea3fd2fffba`, `t3.medium`, Elastic IP `13.49.172.180`, root vol `vol-0a46d7a2885811639`.
- DNS `twitter.dethele.com` managed on **one.com** (NOT Route53) → points at the EIP.

## Not in git — supply from backup
- **`.env`** (server `/home/ec2-user/twitter-bookmarks/.env`): `ANTHROPIC_API_KEY`,
  `TWITTER_AUTH_TOKEN`, `TWITTER_CT0`, **`ENCRYPTION_KEY`** (Fernet — required to decrypt stored
  Twitter cookies; without the *same* key, re-add cookies via admin), Google OAuth client
  id/secret, Django `SECRET_KEY`, DB settings.
- **SSH key** `~/.ssh/twitter-bookmarks-key.pem` (the AWS key pair).
- **Root access keys** — the account has no IAM users; recovery/IaC uses root keys. Guard them.
- **Data** (gitignored — restore from backup or regenerate):
  - `master/bookmarks.json` — the dataset (or re-fetch via birdmarks).
  - DB (`db_data` volume): users, `TwitterProfile` (encrypted cookies), sync schedules.
  - `bookmarks-media/`, `bookmarks-articles/`, `birdmarks_cache/` — fetched media/cache (large; regenerable by re-fetch).

## Steps
1. **Infra (terraform):**
   ```bash
   cd terraform
   cp terraform.tfvars.example terraform.tfvars   # set instance_type, key_pair_name, ssh_allowed_cidrs
   terraform init && terraform apply
   ```
   Creates EC2 (AMI pinned via `ignore_changes=[ami]`), Elastic IP, security group
   (22/80/443/8000 + WireGuard 51820/udp), IAM role + instance profile +
   `AmazonSSMManagedInstanceCore` (SSM recovery shell) + CloudWatch session logging.
   `user_data.sh` installs Docker + compose on first boot. Reuse the existing EIP to keep DNS valid.
2. **DNS:** point `twitter.dethele.com` at the EIP on one.com.
3. **Deploy code:** `./scripts/deploy-to-production.sh` (rsync repo → `docker compose -f docker-compose.prod.yml up -d --build`).
4. **Secrets:** place `.env` on the server.
5. **Restore data:** drop `master/`, `bookmarks-media/`, `bookmarks-articles/`, `birdmarks_cache/` and the `db_data` volume from backup (or re-init DB + re-add the Twitter profile cookies + OAuth users).
6. **SSL:** the `edge-nginx`/`edge-certbot` stack issues + auto-renews Let's Encrypt (certbot twice daily; nginx reload cron at 3 AM).
7. **Start sync:** `docker compose -f docker-compose.prod.yml exec qcluster python manage.py start_bookmark_sync` — registers the per-profile schedules **and** the recovery watchdog (every 30 min).
8. **Verify:** site returns `302 → /accounts/google/login`; search works; `aws ssm start-session --target i-0759ffea3fd2fffba` works; a sync runs to completion.

## Recovery channels & hazards
- **SSM Session Manager** = out-of-band root shell over outbound 443 (works even when inbound is blackholed). See `docs/safe-reboot.md`.
- **Reboot hazard:** the co-tenant newblades capture stack can blackhole all inbound on boot — see `docs/safe-reboot.md` before rebooting.
- **Media never goes in git** (gitignored). It lives on the server + backups only.

## Reproducible vs manual
- **In repo (reproducible):** terraform infra, code, container config (`docker-compose.prod.yml`, `Dockerfile`), nginx, SSL automation, this runbook.
- **Manual restore:** `.env` secrets, the dataset + DB (cookies/users), fetched media.
