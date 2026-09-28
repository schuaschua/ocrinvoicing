locals {
  environment = "shared"
  number_base = 21

  # The one naming and tagging block for this root (P-16, P-17).
  names = module.naming.names
  tags  = module.naming.tags

  # AD-12: one B1ms server for both environments, PostgreSQL 18, 32 GB,
  # 7-day locally redundant backup, no geo-backup, no HA, no zone.
  postgres = {
    sku_name                     = "B_Standard_B1ms"
    server_version               = "18"
    storage_mb                   = 32768
    backup_retention_days        = 7
    geo_redundant_backup_enabled = false
    auto_grow_enabled            = false
  }

  # AD-11: Entra-only authentication, and the operator as the server's Entra admin.
  postgres_authentication = {
    active_directory_auth_enabled = true
    password_auth_enabled         = false
    tenant_id                     = data.azurerm_client_config.current.tenant_id
  }
  postgres_ad_administrator = {
    operator = {
      tenant_id      = data.azurerm_client_config.current.tenant_id
      object_id      = var.postgres_entra_admin_object_id
      principal_name = var.postgres_entra_admin_principal_name
      principal_type = var.postgres_entra_admin_principal_type
    }
  }

  # AD-11/AD-12: one database per environment.
  databases = {
    dev  = "invoicing_dev"
    prod = "invoicing_prod"
  }

  # AD-17 step 2: open to all public IPv4 addresses, the accepted exception to
  # azure.md rule 13 (TLS required, Entra-only auth, per-database CONNECT).
  postgres_firewall_rules = {
    all_ipv4 = {
      name             = "allow-all-public-ipv4"
      start_ip_address = "0.0.0.0"
      end_ip_address   = "255.255.255.255"
    }
  }

  # AD-11: pgcrypto allow-listed. TLS is required through a separate
  # configuration resource (see main.tf).
  postgres_extensions = "PGCRYPTO"

  # AD-16: ACS Email stores data in Asia Pacific (Open Question in the spine).
  communication_data_location = "Asia Pacific"

  # azure.md rule 17.
  budget_thresholds = [
    { threshold = 90, threshold_type = "Actual" },
    { threshold = 100, threshold_type = "Actual" },
    { threshold = 110, threshold_type = "Actual" },
    { threshold = 110, threshold_type = "Forecasted" },
  ]
}
