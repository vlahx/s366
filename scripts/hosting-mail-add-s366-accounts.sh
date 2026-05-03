#!/usr/bin/env bash
# Adaugă cutiile oficiale @s366.online în docker-mailserver.
# Containerul pe acest host se numește de obicei: hosting_mailserver
#
# Utilizare:
#   export MAIL_PASS='parola-securizată'
#   ./scripts/hosting-mail-add-s366-accounts.sh
#
# Sau o singură dată:
#   MAIL_PASS='...' ./scripts/hosting-mail-add-s366-accounts.sh
#
# --- Porturi publicate (host → container) ---
#   25   SMTP
#   587  SMTP submission (STARTTLS) — recomandat pentru aplicații / newsletter
#   993  IMAPS — SnappyMail / clienți mail
#   4190 ManageSieve
#
# --- Din containerul aplicației (s366), aceeași rețea Docker „s366”) ---
#   SMTP: hosting_mailserver (alias: mail) pe 587 cu STARTTLS
#   IMAP: hosting_mailserver pe 993 SSL
#   Alternativ de pe internet: mail.s366.online (același 587 / 993)
#
# Exemplu .env pentru newsletter (app/utils/blog_newsletter_mail.py):
#   NEWSLETTER_SMTP_HOST=hosting_mailserver
#   NEWSLETTER_SMTP_PORT=587
#   NEWSLETTER_SMTP_USER=no-reply@s366.online
#   NEWSLETTER_SMTP_PASSWORD=...aceeași parolă ca la setup email add...
#   NEWSLETTER_FROM_EMAIL=no-reply@s366.online
#   NEWSLETTER_PUBLIC_ORIGIN=https://s366.online
#   NEWSLETTER_SMTP_TLS_VERIFY=false
#     (necesar dacă Postfix folosește cert intern; altfel STARTTLS poate da „unknown ca” din containerul s366)
#   NEWSLETTER_BATCH_SIZE=15
#   NEWSLETTER_BATCH_PAUSE_SECONDS=4
#     (pauză între loturi la trimiterea automată după publicare articol)
#
set -euo pipefail
CONTAINER="${MAIL_CONTAINER:-hosting_mailserver}"
DOMAIN="${MAIL_DOMAIN:-s366.online}"
PASS="${MAIL_PASS:-}"
if [[ -z "$PASS" ]]; then
  echo "Setează MAIL_PASS (ex: export MAIL_PASS='...')" >&2
  exit 1
fi
for local_part in contact support legal no-reply; do
  email="${local_part}@${DOMAIN}"
  if docker exec "$CONTAINER" setup email list 2>/dev/null | grep -qF "$email"; then
    echo "Există deja: $email (sare peste add; folosește: docker exec $CONTAINER setup email update $email)"
    continue
  fi
  docker exec "$CONTAINER" setup email add "$email" "$PASS"
  echo "Creat: $email"
done
docker exec "$CONTAINER" setup email list
