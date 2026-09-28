module "naming" {
  source = "../../modules/naming"

  environment         = local.environment
  number_base         = local.number_base
  owner               = var.owner
  cost_centre         = var.cost_centre
  application         = var.application
  data_classification = var.data_classification
}

# The resource group is created by infra/bootstrap/state-backend.sh (AD-17 step 1)
# and adopted here (azure.md rule 31), so its tags are managed with everything else.
import {
  to = azurerm_resource_group.this
  id = "/subscriptions/${data.azurerm_client_config.current.subscription_id}/resourceGroups/${local.names.resource_group}"
}

resource "azurerm_resource_group" "this" {
  name     = local.names.resource_group
  location = var.location
  tags     = local.tags
}

module "foundation" {
  source = "../../modules/env-foundation"

  location                         = var.location
  resource_group_name              = azurerm_resource_group.this.name
  resource_group_id                = azurerm_resource_group.this.id
  names                            = local.names
  identity_names                   = local.identity_names
  tags                             = local.tags
  tenant_id                        = data.azurerm_client_config.current.tenant_id
  deploy_principal_id              = data.azurerm_client_config.current.object_id
  alert_email                      = var.alert_email
  budget_amount                    = var.budget_amount
  app_insights_sampling_percentage = var.app_insights_sampling_percentage
}
