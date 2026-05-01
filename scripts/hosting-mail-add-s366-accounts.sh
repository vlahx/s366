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
set -euo pipefail
CONTAINER="${MAIL_CONTAINER:-hosting_mailserver}"
DOMAIN="${MAIL_DOMAIN:-s366.online}"
PASS="${MAIL_PASS:-}"
if [[ -z "$PASS" ]]; then
  echo "Setează MAIL_PASS (ex: export MAIL_PASS='...')" >&2
  exit 1
fi
for local_part in contact support legal; do
  email="${local_part}@${DOMAIN}"
  if docker exec "$CONTAINER" setup email list 2>/dev/null | grep -qF "$email"; then
    echo "Există deja: $email (sare peste add; folosește: docker exec $CONTAINER setup email update $email)"
    continue
  fi
  docker exec "$CONTAINER" setup email add "$email" "$PASS"
  echo "Creat: $email"
done
docker exec "$CONTAINER" setup email list
