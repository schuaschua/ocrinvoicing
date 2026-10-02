locals {
  environment = "prod"
  number_base = 11

  # The one naming and tagging block for this root (P-16, P-17).
  app_names = module.naming.app_names
  tags      = module.naming.tags

  foundation = data.terraform_remote_state.foundation.outputs

  # Story 5.2: shared ACS Email through <env>/foundation; all null until shared has it
  # (and while an older foundation state has no `email` output).
  email = merge(
    { communication_service_id = null, acs_endpoint = null, sender_address = null },
    try(local.foundation.email, {}),
  )

  # AD-8: this environment's share of F0's 500 pages a month (Dev 100, Prod 400).
  di_monthly_page_cap = 400
}
