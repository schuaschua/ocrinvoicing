locals {
  environment = "dev"
  number_base = 1

  # The one naming and tagging block for this root (P-16, P-17).
  names          = module.naming.names
  identity_names = module.naming.identity_names
  tags           = module.naming.tags
}
