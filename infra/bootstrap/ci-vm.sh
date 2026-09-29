#!/usr/bin/env bash
#
# AD-17 step 1c (Story 1.2): the CI VM that runs Jenkins for all CI/CD (Dj, 2026-09-29).
# Creates or updates, in the tagged resource group rg-23:
#   - a VNet and subnet, an NSG whose only inbound rule allows SSH from the operator's
#     IP (no web port), a static public IP and a NIC;
#   - an Ubuntu LTS B2s VM (2 vCPU, 4 GB; no auto-shutdown for now), SSH key only;
#     cloud-init (ci-vm-cloud-init.yaml) installs Docker;
#   - the shared and Dev deploy identities (id-21, id-22) attached as user-assigned
#     managed identities. Never Prod's: nothing on the VM can reach Prod. An identity
#     that does not exist yet is skipped with a warning; a re-run attaches it;
#   - over SSH: Jenkins (ci/jenkins) built and started in Docker on 127.0.0.1:8080, with
#     the Azure DevOps token from .work/ado-pat as its only stored secret
#     (ci-vm-remote.sh on the VM).
# No Terraform, migrations or app resources. Idempotent: a re-run skips what exists and
# re-applies the settings, tags and identities, starts a deallocated VM, and recreates the
# Jenkins container only when its image or settings changed.

# shellcheck source-path=SCRIPTDIR source=lib.sh
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

usage() {
  cat <<'EOF'
Usage: ci-vm.sh [--dry-run]

Required environment variables:
  ARM_SUBSCRIPTION_ID     target subscription
  TAG_OWNER, TAG_COST_CENTRE, TAG_APPLICATION, TAG_DATA_CLASSIFICATION
                          P-17 tag values (environment is "shared")
  CI_SSH_SOURCE_IP        the operator's public IPv4 address: the only SSH source
  CI_SSH_PUBLIC_KEY_FILE  the operator's SSH public key (the private key is the same
                          path without .pub, or the ssh agent's)
  ADO_ORG, ADO_PROJECT    Azure DevOps organisation and project (the repository URL)
Optional:
  ADO_REPO                Azure Repos repository (default ADO_PROJECT)
  ADO_PAT_FILE            the Azure DevOps token file (default .work/ado-pat); the token
                          needs Code Read and Code Status
EOF
}

parse_common_args "$@"
require_env ARM_SUBSCRIPTION_ID CI_SSH_SOURCE_IP CI_SSH_PUBLIC_KEY_FILE ADO_ORG ADO_PROJECT
require_tag_inputs
ADO_REPO="${ADO_REPO:-$ADO_PROJECT}"
ADO_PAT_FILE="${ADO_PAT_FILE:-$REPO_ROOT/.work/ado-pat}"

# Every input is checked before any change.
[[ "$CI_SSH_SOURCE_IP" =~ ^([0-9]{1,3})\.([0-9]{1,3})\.([0-9]{1,3})\.([0-9]{1,3})$ ]] ||
  die "CI_SSH_SOURCE_IP must be one IPv4 address (no range), got '$CI_SSH_SOURCE_IP'"
for octet in "${BASH_REMATCH[@]:1}"; do
  ((10#$octet <= 255)) || die "CI_SSH_SOURCE_IP is not a valid IPv4 address: $CI_SSH_SOURCE_IP"
done
[[ "$CI_SSH_SOURCE_IP" != 0.0.0.0 ]] || die "CI_SSH_SOURCE_IP must be the operator's address, not 0.0.0.0"
[[ -s "$CI_SSH_PUBLIC_KEY_FILE" ]] || die "CI_SSH_PUBLIC_KEY_FILE $CI_SSH_PUBLIC_KEY_FILE is missing or empty"
[[ -s "$ADO_PAT_FILE" ]] || die "the Azure DevOps token file $ADO_PAT_FILE is missing or empty (see infra/bootstrap/README.md)"

# rg-23 (shared range) holds only the CI VM and its network; the rest take the first
# number of their type in the shared range.
CI_RG="$(resource_name rg 23)"
VNET="$(resource_name vnet 21)"
SUBNET="$(resource_name snet 21)"
NSG="$(resource_name nsg 21)"
PUBLIC_IP="$(resource_name pip 21)"
NIC="$(resource_name nic 21)"
VM="$(resource_name vm 21)"
OS_DISK="$(resource_name osdisk 21)"
readonly CI_RG VNET SUBNET NSG PUBLIC_IP NIC VM OS_DISK
readonly VM_SIZE="Standard_B2s"
readonly VM_IMAGE="Canonical:ubuntu-24_04-lts:server:latest"
readonly VM_ADMIN="ciadmin"
readonly SSH_RULE="allow-ssh-operator"
readonly REPO_URL="https://dev.azure.com/$ADO_ORG/$ADO_PROJECT/_git/$ADO_REPO"
# The only identities the VM may carry (Dj, 2026-09-29): never Prod's.
readonly ATTACHED_OWNERS=(shared dev)

select_subscription

step "Register resource providers"
for namespace in Microsoft.Compute Microsoft.Network; do
  run az provider register --namespace "$namespace" --wait
done

set_tags shared

step "Resource group $CI_RG"
if exists az group show --name "$CI_RG"; then
  run az group update --name "$CI_RG" --tags "${TAGS[@]}"
else
  run az group create --name "$CI_RG" --location "$LOCATION" --tags "${TAGS[@]}"
fi

step "Virtual network $VNET"
if exists az network vnet show --name "$VNET" --resource-group "$CI_RG"; then
  run az network vnet update --name "$VNET" --resource-group "$CI_RG" --tags "${TAGS[@]}"
else
  run az network vnet create --name "$VNET" --resource-group "$CI_RG" --location "$LOCATION" \
    --address-prefixes 10.23.0.0/24 --subnet-name "$SUBNET" --subnet-prefixes 10.23.0.0/27 \
    --tags "${TAGS[@]}"
fi

# The NSG's only inbound rule: SSH from the operator's IP. Azure's default rules deny all
# other inbound traffic from the internet, so Jenkins has no public port.
step "Network security group $NSG (SSH from $CI_SSH_SOURCE_IP only)"
if exists az network nsg show --name "$NSG" --resource-group "$CI_RG"; then
  run az network nsg update --name "$NSG" --resource-group "$CI_RG" --tags "${TAGS[@]}"
else
  run az network nsg create --name "$NSG" --resource-group "$CI_RG" --location "$LOCATION" \
    --tags "${TAGS[@]}"
fi
ssh_rule=(--nsg-name "$NSG" --resource-group "$CI_RG" --name "$SSH_RULE" --priority 100
  --direction Inbound --access Allow --protocol Tcp
  --source-address-prefixes "$CI_SSH_SOURCE_IP/32" --source-port-ranges '*'
  --destination-address-prefixes '*' --destination-port-ranges 22)
if exists az network nsg rule show --nsg-name "$NSG" --resource-group "$CI_RG" --name "$SSH_RULE"; then
  run az network nsg rule update "${ssh_rule[@]}"
else
  run az network nsg rule create "${ssh_rule[@]}"
fi
step "Subnet $SUBNET uses $NSG"
run az network vnet subnet update --vnet-name "$VNET" --name "$SUBNET" --resource-group "$CI_RG" \
  --network-security-group "$NSG"

step "Public IP $PUBLIC_IP"
if exists az network public-ip show --name "$PUBLIC_IP" --resource-group "$CI_RG"; then
  run az network public-ip update --name "$PUBLIC_IP" --resource-group "$CI_RG" --tags "${TAGS[@]}"
else
  run az network public-ip create --name "$PUBLIC_IP" --resource-group "$CI_RG" --location "$LOCATION" \
    --sku Standard --allocation-method Static --version IPv4 --tags "${TAGS[@]}"
fi

step "Network interface $NIC"
if exists az network nic show --name "$NIC" --resource-group "$CI_RG"; then
  run az network nic update --name "$NIC" --resource-group "$CI_RG" \
    --network-security-group "$NSG" --tags "${TAGS[@]}"
else
  run az network nic create --name "$NIC" --resource-group "$CI_RG" --location "$LOCATION" \
    --vnet-name "$VNET" --subnet "$SUBNET" --network-security-group "$NSG" \
    --public-ip-address "$PUBLIC_IP" --tags "${TAGS[@]}"
fi

step "Virtual machine $VM ($VM_SIZE)"
vm_created=0
if exists az vm show --name "$VM" --resource-group "$CI_RG"; then
  run az resource tag --resource-group "$CI_RG" --name "$VM" \
    --resource-type Microsoft.Compute/virtualMachines --tags "${TAGS[@]}" --output none
  # Dj deallocates the VM when not in use; the SSH steps below need it running.
  power_state="$(value_or_placeholder "" az vm get-instance-view --name "$VM" --resource-group "$CI_RG" \
    --query "instanceView.statuses[?starts_with(code, 'PowerState/')].code | [0]" -o tsv)"
  if [[ "$power_state" != "PowerState/running" ]]; then
    run az vm start --name "$VM" --resource-group "$CI_RG" --output none
  fi
else
  vm_created=1
  run az vm create --name "$VM" --resource-group "$CI_RG" --location "$LOCATION" \
    --size "$VM_SIZE" --image "$VM_IMAGE" --nics "$NIC" \
    --admin-username "$VM_ADMIN" --authentication-type ssh --ssh-key-values "$CI_SSH_PUBLIC_KEY_FILE" \
    --os-disk-name "$OS_DISK" --os-disk-size-gb 64 --storage-sku StandardSSD_LRS \
    --custom-data "$BOOTSTRAP_DIR/ci-vm-cloud-init.yaml" --tags "${TAGS[@]}" --output none
fi

# Deploy identities: attach shared and Dev (re-applied on every run), and take Prod's off
# should it ever have been attached by hand.
client_id_shared=""
client_id_dev=""
for owner in "${ATTACHED_OWNERS[@]}"; do
  identity="$(deploy_identity_name "$owner")"
  step "Attach deploy identity $identity ($owner)"
  if ((!DRY_RUN)) && ! exists az identity show --name "$identity" --resource-group "$STATE_RG"; then
    warn "deploy identity $identity does not exist yet: run state-backend.sh, then re-run ci-vm.sh to attach it"
    continue
  fi
  identity_id="$(value_or_placeholder "<id-of-$identity>" \
    az identity show --name "$identity" --resource-group "$STATE_RG" --query id -o tsv)"
  client_id="$(value_or_placeholder "<clientId-of-$identity>" \
    az identity show --name "$identity" --resource-group "$STATE_RG" --query clientId -o tsv)"
  run az vm identity assign --name "$VM" --resource-group "$CI_RG" --identities "$identity_id" --output none
  case "$owner" in
    shared) client_id_shared="$client_id" ;;
    dev) client_id_dev="$client_id" ;;
  esac
done

prod_identity="$(deploy_identity_name prod)"
step "Prod's deploy identity $prod_identity is not attached"
attached="$(value_or_placeholder "" az vm identity show --name "$VM" --resource-group "$CI_RG" \
  --query "keys(userAssignedIdentities || \`{}\`)" -o tsv)"
while IFS= read -r attached_id; do
  # Resource ids differ in case between APIs (and macOS's bash 3.2 has no ${x,,}).
  if [[ "$(tr '[:upper:]' '[:lower:]' <<<"$attached_id")" == */userassignedidentities/"$prod_identity" ]]; then
    run az vm identity remove --name "$VM" --resource-group "$CI_RG" --identities "$attached_id" --output none
  fi
done <<<"$attached"

# Jenkins over SSH: the build context and the remote step go to the VM, then
# ci-vm-remote.sh builds the image and (re)starts the container. The token travels on
# ssh's standard input only, never on a command line or in the log.
step "Jenkins on $VM"
host_ip="$(value_or_placeholder "<public-ip-of-$VM>" \
  az network public-ip show --name "$PUBLIC_IP" --resource-group "$CI_RG" --query ipAddress -o tsv)"
host="$VM_ADMIN@$host_ip"
mkdir -p "$REPO_ROOT/.work/ci-vm"
known_hosts="$REPO_ROOT/.work/ci-vm/known_hosts"
# A new VM has a new host key; forget any old one recorded for this IP.
if ((vm_created)) && [[ -f "$known_hosts" ]]; then
  run ssh-keygen -R "$host_ip" -f "$known_hosts"
fi
ssh_opts=(-o StrictHostKeyChecking=accept-new -o UserKnownHostsFile="$known_hosts"
  -o ConnectTimeout=30)
private_key="${CI_SSH_PUBLIC_KEY_FILE%.pub}"
if [[ "$private_key" != "$CI_SSH_PUBLIC_KEY_FILE" && -f "$private_key" ]]; then
  ssh_opts+=(-i "$private_key")
fi
remote_dir="/home/$VM_ADMIN/jenkins-build"

# cloud-init exits 2 for "done, with recoverable errors"; Docker is checked on the VM anyway.
run ssh "${ssh_opts[@]}" "$host" "cloud-init status --wait >/dev/null; rc=\$?; [ \$rc -eq 0 ] || [ \$rc -eq 2 ] || exit \$rc; rm -rf $remote_dir"
run scp "${ssh_opts[@]}" -r "$REPO_ROOT/ci/jenkins" "$host:$remote_dir"
run scp "${ssh_opts[@]}" "$BOOTSTRAP_DIR/ci-vm-remote.sh" "$host:$remote_dir/ci-vm-remote.sh"
remote_args="$(printf '%q ' "$ADO_ORG" "$ADO_PROJECT" "$ADO_REPO" "${client_id_shared:-none}" "${client_id_dev:-none}")"
run ssh "${ssh_opts[@]}" "$host" "sudo bash $remote_dir/ci-vm-remote.sh ${remote_args% }" <"$ADO_PAT_FILE"

step "Done"
log "CI VM: $VM ($VM_SIZE) in $CI_RG, SSH from $CI_SSH_SOURCE_IP only; Jenkins polls $REPO_URL."
log "Jenkins UI: ssh -N -L 8080:127.0.0.1:8080 $host, then open http://127.0.0.1:8080 (user dj)."
log "Password: ssh $host sudo cat /opt/jenkins/secrets/admin-password"
log "Deallocate when not in use: az vm deallocate --name $VM --resource-group $CI_RG"
