variables {
  environment         = "prod"
  number_base         = 11
  owner               = "test-owner"
  cost_centre         = "test-cc"
  application         = "test-app"
  data_classification = "test-class"
}

run "prod_range" {
  command = plan

  assert {
    condition     = output.names.resource_group == "babaloo-sea-lng-rg-11" && output.names.storage_account == "babaloosealngst11"
    error_message = "prod names must use 11-19, storage without hyphens."
  }
  assert {
    condition = output.identity_names == {
      supplier_api = "babaloo-sea-lng-id-11"
      staff_api    = "babaloo-sea-lng-id-12"
      pipeline     = "babaloo-sea-lng-id-13"
      accounts_sim = "babaloo-sea-lng-id-14"
    }
    error_message = "prod identities must be id-11..14 in AD-1 order."
  }
  assert {
    condition     = keys(output.tags) == ["application", "costCentre", "dataClassification", "environment", "owner"] && output.tags.environment == "prod"
    error_message = "tags must be exactly the five P-17 keys, with environment set."
  }
  assert {
    condition     = length(output.names.key_vault) <= 24 && length(output.names.storage_account) <= 24
    error_message = "Key Vault and storage names must fit Azure's 24-character limit."
  }
  assert {
    condition     = length(output.names.action_group_shortname) <= 12
    error_message = "the action group short name must be at most 12 characters."
  }
}

run "shared_range" {
  command = plan

  variables {
    environment = "shared"
    number_base = 21
  }

  assert {
    condition     = output.names.postgres_server == "babaloo-sea-lng-psql-21" && output.names.document_intelligence == "babaloo-sea-lng-di-21"
    error_message = "shared names must use 21-29."
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

run "base_must_match_environment" {
  command = plan

  variables {
    environment = "dev"
    number_base = 11
  }

  expect_failures = [var.number_base]
}

run "empty_tag_value_fails" {
  command = plan

  variables {
    cost_centre = " "
  }

  expect_failures = [var.cost_centre]
}

run "app_names" {
  command = plan

  variables {
    environment = "dev"
    number_base = 1
  }

  assert {
    condition = output.app_names == {
      supplier_api = { plan = "babaloo-sea-lng-asp-01", function_app = "babaloo-sea-lng-func-01", deployment_container = "deploy-supplier-api" }
      staff_api    = { plan = "babaloo-sea-lng-asp-02", function_app = "babaloo-sea-lng-func-02", deployment_container = "deploy-staff-api" }
      pipeline     = { plan = "babaloo-sea-lng-asp-03", function_app = "babaloo-sea-lng-func-03", deployment_container = "deploy-pipeline" }
      accounts_sim = { plan = "babaloo-sea-lng-asp-04", function_app = "babaloo-sea-lng-func-04", deployment_container = "deploy-accounts-sim" }
    }
    error_message = "dev Flex apps must be asp/func-01..04 in AD-1 order, each with its deployment container."
  }
}

run "no_apps_in_shared" {
  command = plan

  variables {
    environment = "shared"
    number_base = 21
  }

  assert {
    condition     = output.app_names == {}
    error_message = "shared has no Function apps (AD-1: four per environment)."
  }
}

run "metric_alert_names" {
  command = plan

  variables {
    environment = "dev"
    number_base = 1
  }

  assert {
    condition = output.metric_alert_names == {
      poison_message = "babaloo-sea-lng-ar-01"
      stuck_invoices = "babaloo-sea-lng-ar-02"
    }
    error_message = "dev metric alert rules must be ar-01 (poison_message) and ar-02 (stuck_invoices) (P-16)."
  }
}

run "metric_alert_names_prod_and_shared" {
  command = plan

  assert {
    condition     = output.metric_alert_names == { poison_message = "babaloo-sea-lng-ar-11", stuck_invoices = "babaloo-sea-lng-ar-12" }
    error_message = "prod metric alert rules must be ar-11 and ar-12 (P-16)."
  }
}

run "no_metric_alerts_in_shared" {
  command = plan

  variables {
    environment = "shared"
    number_base = 21
  }

  assert {
    condition     = output.metric_alert_names == {}
    error_message = "shared has no pipeline metrics, so no metric alert rules."
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
