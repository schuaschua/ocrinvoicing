#!/usr/bin/env bash
#
# AD-17 step 4b (operator, once per environment, after <env>/foundation is applied):
# generate the bank-detail PGP key pair offline with gpg (RSA 3072, ASCII-armoured,
# no passphrase, so pgp_pub_decrypt needs none), store pgp-private-key in the
# environment's private-key vault (kv-22 Dev, kv-23 Prod, in rg-22) and pgp-public-key
# in the environment's vault, then delete every local copy. Finally give the
# environment's staff-api identity Key Vault Secrets User on pgp-private-key only
# (OCR-129: nobody else may read it). Terraform never manages these two secrets.
#
# Idempotent: if both secrets already exist nothing is generated (a new pair would
# make existing ciphertext unreadable) and only staff-api's role is checked. If only
# one exists the script stops. If pgp-private-key is still in the environment's vault
# (stored there before OCR-129) the script stops: move it by hand (README step 4b).
# Precondition: the operator holds Owner, plus Key Vault Secrets Officer on both
# vaults for this step only (README step 4b).

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
pk_vault="$(private_key_vault_name "$ENVIRONMENT")"
readonly PUBLIC_SECRET="pgp-public-key"
readonly PRIVATE_SECRET="pgp-private-key"
private_secret_scope="$(rg_scope "$STATE_RG")/providers/Microsoft.KeyVault/vaults/$pk_vault/secrets/$PRIVATE_SECRET"

secret_exists() {
  exists az keyvault secret show --vault-name "$1" --name "$2"
}

# The staff-api identity comes from <env>/foundation; without it nobody could read the
# private key, so stop before writing anything.
step "Find the $ENVIRONMENT staff-api identity"
staff_identity="$(app_identity_name "$ENVIRONMENT" staff-api)"
env_rg="$(rg_name "$ENVIRONMENT")"
if ! ((DRY_RUN)) && ! exists az identity show --name "$staff_identity" --resource-group "$env_rg"; then
  die "staff-api identity $staff_identity not found in $env_rg; apply $ENVIRONMENT/foundation (AD-17 step 4) first, then re-run"
fi
staff_principal_id="$(identity_principal_id "$staff_identity" "$env_rg")"

step "Find the private-key vault $pk_vault"
if ! ((DRY_RUN)) && ! exists az keyvault show --name "$pk_vault" --resource-group "$STATE_RG"; then
  die "private-key vault $pk_vault not found in $STATE_RG; run state-backend.sh (AD-17 step 1) first, then re-run"
fi

step "Check existing secrets in $vault and $pk_vault"
if secret_exists "$vault" "$PRIVATE_SECRET"; then
  die "$PRIVATE_SECRET is in $vault, where more than staff-api can read it. Move it to $pk_vault, then delete and purge it from $vault (README step 4b, \"Moving an existing private key\"), then re-run. Nothing was changed."
fi
public_present=0
private_present=0
if secret_exists "$vault" "$PUBLIC_SECRET"; then public_present=1; fi
if secret_exists "$pk_vault" "$PRIVATE_SECRET"; then private_present=1; fi
if ((public_present != private_present)); then
  die "only one of $PUBLIC_SECRET ($vault) / $PRIVATE_SECRET ($pk_vault) exists; fix by hand (never regenerate over live ciphertext)"
fi

grant_staff_api() {
  step "Key Vault Secrets User for $staff_identity on $PRIVATE_SECRET only"
  ensure_role_assignment "$staff_principal_id" ServicePrincipal "$ROLE_KV_SECRETS_USER" "$private_secret_scope"
}

if ((public_present && private_present)); then
  log "exists: $PUBLIC_SECRET in $vault and $PRIVATE_SECRET in $pk_vault; nothing to generate."
  grant_staff_api
  log "Nothing to do beyond the role check."
  exit 0
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
step "Store $PRIVATE_SECRET in $pk_vault and $PUBLIC_SECRET in $vault (fingerprint $fingerprint)"
run az keyvault secret set --vault-name "$pk_vault" --name "$PRIVATE_SECRET" \
  --file "$gnupg_home/private.asc" --content-type "application/pgp-keys" \
  --tags "fingerprint=$fingerprint" --output none
run az keyvault secret set --vault-name "$vault" --name "$PUBLIC_SECRET" \
  --file "$gnupg_home/public.asc" --content-type "application/pgp-keys" \
  --tags "fingerprint=$fingerprint" --output none

step "Delete local copies"
cleanup
gnupg_home=""
log "Local key material removed."

grant_staff_api
log "Done. Now remove your Key Vault Secrets Officer assignments on $pk_vault and $vault (README step 4b)."
log "Next: database-step5.sh for $ENVIRONMENT (see README.md)."
