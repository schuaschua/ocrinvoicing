locals {
  environment = "prod"
  number_base = 11

  # The one naming and tagging block for this root (P-16, P-17).
  app_names = module.naming.app_names
  tags      = module.naming.tags

  foundation = data.terraform_remote_state.foundation.outputs
}
