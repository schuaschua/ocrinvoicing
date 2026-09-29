locals {
  environment = "dev"
  number_base = 1

  # The one naming and tagging block for this root (P-16, P-17).
  app_names = module.naming.app_names
  tags      = module.naming.tags

  foundation = data.terraform_remote_state.foundation.outputs

  # AD-8: this environment's share of F0's 500 pages a month (Dev 100, Prod 400).
  di_monthly_page_cap = 100
}
