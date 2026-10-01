module "naming" {
  source = "../../modules/naming"

  environment         = local.environment
  number_base         = local.number_base
  owner               = var.owner
  cost_centre         = var.cost_centre
  application         = var.application
  data_classification = var.data_classification
}

# AD-17 step 7: the four Flex apps, their settings and runtime roles.
module "app" {
  source = "../../modules/env-app"

  environment       = local.environment
  location          = var.location
  resource_group_id = local.foundation.resource_group_id
  app_names         = local.app_names
  # Story 2.7: staff-api's built-in auth signs in through this app registration.
  staff_api_client_id = var.staff_api_client_id
  # Story 3.1: accounts-sim's built-in auth accepts tokens for this app registration.
  accounts_sim_client_id = var.accounts_sim_client_id
  identities = {
    for app, identity in local.foundation.identities : app => {
      name         = identity.name
      resource_id  = identity.resource_id
      principal_id = identity.principal_id
      client_id    = identity.client_id
    }
  }
  storage_account = {
    name        = local.foundation.storage_account.name
    resource_id = local.foundation.storage_account.resource_id
  }
  database = {
    name = local.foundation.database.name
    fqdn = local.foundation.database.fqdn
  }
  key_vault = {
    resource_id = local.foundation.key_vault.resource_id
    uri         = local.foundation.key_vault.uri
  }
  # OCR-129: the private-key vault in rg-22 is made by the bootstrap scripts, so its
  # URI comes from the naming convention, not from a stack's state.
  private_key_vault_uri   = "https://${module.naming.private_key_vault_name}.vault.azure.net/"
  application_insights_id = local.foundation.application_insights.resource_id
  # Story 2.3: the shared DI resource, through <env>/foundation, and this env's cap.
  document_intelligence_id       = local.foundation.document_intelligence_id
  document_intelligence_endpoint = local.foundation.document_intelligence_endpoint
  di_monthly_page_cap            = local.di_monthly_page_cap
  # Stories 2.2 and 2.3: the pipeline metric alerts go to the env action group.
  action_group_id                        = local.foundation.action_group_id
  metric_alert_names                     = module.naming.metric_alert_names
  application_insights_connection_string = local.foundation.application_insights_connection_string
  # Story 5.2 (AD-16): the pipeline's ACS Email Sender role and alert email settings,
  # only once shared/foundation has ACS Email with a linked domain (null keeps both
  # off). The role waits for the link, so the deploy chain that first creates ACS
  # never assigns it before rbac-step3.sh has given this env's deploy identity the
  # right to (infra/bootstrap/README.md "Email domain").
  communication_service_id = local.email.sender_address == null ? null : local.email.communication_service_id
  email_acs_endpoint       = local.email.acs_endpoint
  email_sender_address     = local.email.sender_address
  alert_recipients = {
    finance     = var.alert_recipients_finance
    procurement = var.alert_recipients_procurement
    management  = var.alert_recipients_management
  }
  # The only sampling (Application Insights samples nothing at ingestion).
  telemetry_sampling_ratio = var.telemetry_sampling_ratio
  tags                     = local.tags
}
