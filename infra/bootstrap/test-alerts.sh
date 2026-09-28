#!/usr/bin/env bash
#
# Story 1.5 (AD-17 Alerts): proves an alert reaches Dj. Sends one test notification
# through each action group (ag-21 shared, ag-01 dev, ag-11 prod) to the email
# receivers stored on that group, so it tests what the stacks actually configured.
# Every group is checked before anything is sent. Run after the stacks are applied;
# then check that each receiver got one test email per group (README.md). Sends only
# test notifications and changes nothing.

# shellcheck source-path=SCRIPTDIR source=lib.sh
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

usage() {
  cat <<'EOF'
Usage: test-alerts.sh [--dry-run]

Required environment variables:
  ARM_SUBSCRIPTION_ID   target subscription

Optional:
  STACKS                which action groups to test, from "shared dev prod" (the default;
                        repeats are ignored), e.g. STACKS="shared dev" before
                        prod/foundation is applied
EOF
}

parse_common_args "$@"
require_env ARM_SUBSCRIPTION_ID
stacks=()
for stack in ${STACKS:-shared dev prod}; do
  case "$stack" in
    shared | dev | prod) ;;
    *) die "STACKS must list only shared, dev or prod (got '$stack')" ;;
  esac
  case " ${stacks[*]:-} " in
    *" $stack "*) ;;
    *) stacks+=("$stack") ;;
  esac
done
((${#stacks[@]})) || die "STACKS must name at least one of shared, dev or prod"
select_subscription

# alert_type STACK - the alert kind each group exists for: budgets for shared, and for
# the environments the metric alerts of Stories 2.2 and 2.3 (their budgets use it too).
alert_type() {
  case "$1" in
    shared) echo actualcostbudget ;;
    *) echo metricstaticthreshold ;;
  esac
}

# First every group: it must exist and have at least one email receiver, so a missing
# group stops the script before any notification is sent.
receivers=()
for stack in "${stacks[@]}"; do
  group="$(action_group_name "$stack")"
  rg="$(rg_name "$stack")"
  step "Check $group ($stack)"
  if ! ((DRY_RUN)) && ! exists az monitor action-group show --name "$group" --resource-group "$rg" --output none; then
    die "action group $group does not exist in $rg; apply infra/$stack/foundation first, or leave $stack out of STACKS"
  fi
  # One "<name><TAB><address>" line per email receiver.
  found="$(value_or_placeholder "$(printf 'owner\t<email-receiver-of-%s>' "$group")" \
    az monitor action-group show --name "$group" --resource-group "$rg" \
    --query 'emailReceivers[].[name, emailAddress]' --output tsv)"
  [[ -n "$found" ]] || die "action group $group has no email receiver, so its alerts reach nobody"
  receivers+=("$found")
done

sent=()
index=0
for stack in "${stacks[@]}"; do
  group="$(action_group_name "$stack")"
  step "Test notification through $group ($stack)"
  args=(az monitor action-group test-notifications create
    --action-group-name "$group"
    --resource-group "$(rg_name "$stack")"
    --alert-type "$(alert_type "$stack")")
  addresses=""
  while IFS=$'\t' read -r name address; do
    [[ -n "$name" && -n "$address" ]] || continue
    args+=(--add-action email "$name" "$address" usecommonalertschema)
    addresses="$addresses $address"
  done <<<"${receivers[$index]}"
  [[ -n "$addresses" ]] || die "action group $group has no email receiver, so its alerts reach nobody"
  run "${args[@]}" --output none
  sent+=("$group ->$addresses")
  index=$((index + 1))
done

step "Done"
if ((DRY_RUN)); then
  log "Would send ${#sent[@]} test notification(s):"
else
  log "Sent ${#sent[@]} test notification(s):"
fi
for line in "${sent[@]}"; do log "  $line"; done
log "Now check that each address received one test email per action group (the subject names the group)."
log "A missing email means that group's alerts do not reach Dj: check its email receiver and spam folder."
