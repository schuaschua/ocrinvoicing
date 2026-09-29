variables {
  environment         = "prod"
  number_base         = 11
  owner               = "test-owner"
  cost_centre         = "test-cc"
  application         = "test-app"
  data_classification = "test-class"
}

run "shared_range" {
  command = plan

  variables {
    environment = "shared"
    number_base = 21
  }

  assert {
    condition     = output.identity_names == {}
    error_message = "shared has no app identities: id-21..23 are the bootstrap's deploy identities."
  }
  assert {
    condition     = output.names.resource_group == "babaloo-sea-lng-rg-21"
    error_message = "the shared stack's resource group must be rg-21 (rg-22 is bootstrap-only)."
  }
}

run "private_key_vault_names" {
  command = plan

  variables {
    environment = "dev"
    number_base = 1
  }

  assert {
    condition     = output.private_key_vault_name == "babaloo-sea-lng-kv-22"
    error_message = "the dev private-key vault must be kv-22 (OCR-129, infra/bootstrap/lib.sh)."
  }
}

run "private_key_vault_names_prod_and_shared" {
  command = plan

  assert {
    condition     = output.private_key_vault_name == "babaloo-sea-lng-kv-23" && length(output.private_key_vault_name) <= 24
    error_message = "the prod private-key vault must be kv-23 (OCR-129, infra/bootstrap/lib.sh)."
  }
}

run "no_private_key_vault_for_shared" {
  command = plan

  variables {
    environment = "shared"
    number_base = 21
  }

  assert {
    condition     = output.private_key_vault_name == null
    error_message = "shared has no private-key vault."
  }
}
