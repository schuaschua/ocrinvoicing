#!/usr/bin/env bash
#
# AD-17 step 4b (operator, once per environment, after <env>/foundation is applied):
# generate the bank-detail PGP key pair offline with gpg (RSA 3072, ASCII-armoured,
# no passphrase, so pgp_pub_decrypt needs none), store it in the environment's Key
# Vault as pgp-public-key and pgp-private-key, then delete every local copy.
# Terraform never manages these two secrets.
#
# Idempotent: if both secrets already exist nothing is generated (a new pair would
# make existing ciphertext unreadable). If only one exists the script stops.
# Precondition: the operator holds Key Vault Secrets Officer on the vault.

# shellcheck source-path=SCRIPTDIR source=lib.sh
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

usage() {
  cat <<'EOF'
Usage: pgp-step4b.sh [--dry-run]

Required environment variables:
  ARM_SUBSCRIPTION_ID   target subscription
  ENVIRONMENT           dev or prod
EOF
}

parse_common_args "$@"
require_env ARM_SUBSCRIPTION_ID
require_env_choice ENVIRONMENT dev prod
require_tools az gpg gpgconf
select_subscription

vault="$(key_vault_name "$ENVIRONMENT")"
readonly PUBLIC_SECRET="pgp-public-key"
readonly PRIVATE_SECRET="pgp-private-key"

secret_exists() {
  exists az keyvault secret show --vault-name "$vault" --name "$1"
}

step "Check existing secrets in $vault"
public_present=0
private_present=0
if secret_exists "$PUBLIC_SECRET"; then public_present=1; fi
if secret_exists "$PRIVATE_SECRET"; then private_present=1; fi
if ((public_present && private_present)); then
  log "exists: $PUBLIC_SECRET and $PRIVATE_SECRET in $vault; nothing to do."
  exit 0
fi
if ((public_present || private_present)); then
  die "only one of $PUBLIC_SECRET / $PRIVATE_SECRET exists in $vault; fix by hand (never regenerate over live ciphertext)"
fi

gnupg_home=""
cleanup() {
  if [[ -n "$gnupg_home" && -d "$gnupg_home" ]]; then
    GNUPGHOME="$gnupg_home" gpgconf --kill gpg-agent >/dev/null 2>&1 || true
    rm -rf "$gnupg_home"
  fi
}
trap cleanup EXIT

step "Generate the key pair offline (throwaway GNUPGHOME)"
uid_email="invoicing-$ENVIRONMENT@babaloo.invalid"
key_params="$(
  cat <<EOF
%no-protection
Key-Type: RSA
Key-Length: 3072
Key-Usage: sign
Subkey-Type: RSA
Subkey-Length: 3072
Subkey-Usage: encrypt
Name-Real: Babaloo invoicing bank details ($ENVIRONMENT)
Name-Email: $uid_email
Expire-Date: 0
%commit
EOF
)"
if ((DRY_RUN)); then
  gnupg_home="<scratch-gnupg-home>"
  log "$key_params"
  run gpg --homedir "$gnupg_home" --batch --gen-key "$gnupg_home/params"
  run gpg --homedir "$gnupg_home" --armor --export "$uid_email"
  run gpg --homedir "$gnupg_home" --armor --export-secret-keys "$uid_email"
  fingerprint="<key-fingerprint>"
else
  gnupg_home="$(scratch_dir)"
  printf '%s\n' "$key_params" >"$gnupg_home/params"
  GNUPGHOME="$gnupg_home" gpg --batch --quiet --gen-key "$gnupg_home/params"
  GNUPGHOME="$gnupg_home" gpg --armor --export "$uid_email" >"$gnupg_home/public.asc"
  GNUPGHOME="$gnupg_home" gpg --armor --export-secret-keys "$uid_email" >"$gnupg_home/private.asc"
  grep -q 'BEGIN PGP PUBLIC KEY BLOCK' "$gnupg_home/public.asc" || die "public key export failed"
  grep -q 'BEGIN PGP PRIVATE KEY BLOCK' "$gnupg_home/private.asc" || die "private key export failed"
  fingerprint="$(GNUPGHOME="$gnupg_home" gpg --with-colons --list-keys "$uid_email" | awk -F: '/^fpr:/ { print $10; exit }')"
  [[ -n "$fingerprint" ]] || die "could not read the key fingerprint"
fi

# Private key first: if the run stops between the two writes, no public key exists
# that could encrypt data nobody can decrypt. Both carry the key fingerprint.
step "Store the key pair in $vault (fingerprint $fingerprint)"
run az keyvault secret set --vault-name "$vault" --name "$PRIVATE_SECRET" \
  --file "$gnupg_home/private.asc" --content-type "application/pgp-keys" \
  --tags "fingerprint=$fingerprint" --output none
run az keyvault secret set --vault-name "$vault" --name "$PUBLIC_SECRET" \
  --file "$gnupg_home/public.asc" --content-type "application/pgp-keys" \
  --tags "fingerprint=$fingerprint" --output none

step "Delete local copies"
cleanup
gnupg_home=""
log "Local key material removed. Done."
log "Next: database-step5.sh for $ENVIRONMENT (see README.md)."
