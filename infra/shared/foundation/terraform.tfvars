# Shared stack values. No secrets, subscription ids or tenant ids here.
#
# Dj fills the required inputs below before the first apply (plan Decisions):
owner               = "dj"
cost_centre         = "poc"
application         = "ocrinvoicing"
data_classification = "synthetic"
alert_email         = "alerts@example.test"
# email_custom_domain                 = ""   # e.g. mail.example.com
# The PostgreSQL Entra admin is the pg-admins group (Dj, 2026-09-29): app-registrations.sh
# creates it and prints its object id.
postgres_entra_admin_object_id      = "fc185dcb-7f15-4190-b91e-bf5116bc8190" # the pg-admins group (app-registrations.sh)
postgres_entra_admin_principal_name = "babaloo-sea-lng-grp-21"
postgres_entra_admin_principal_type = "Group"

# Set to true and re-apply once the email domain's DNS records are verified.
email_domain_link_enabled = false

# [ASSUMPTION] The shared group holds the ~$10-11/month PostgreSQL server (AD-12).
budget_amount = 12
