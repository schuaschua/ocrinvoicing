locals {
  environment = "prod"
  number_base = 11

  # The one naming and tagging block for this root (P-16, P-17).
  names          = module.naming.names
  identity_names = module.naming.identity_names
  tags           = module.naming.tags
}
