# Shared stack values. No secrets, subscription ids or tenant ids here.
#
# Dj fills the required inputs below before the first apply (plan Decisions):
owner               = "dj"
cost_centre         = "poc"
application         = "ocrinvoicing"
data_classification = "synthetic"
alert_email         = "alerts@example.test"
# email_custom_domain                 = ""   # e.g. mail.example.com
# postgres_entra_admin_object_id      = ""   # the operator's Entra object id
# postgres_entra_admin_principal_name = ""   # the operator's UPN

# Set to true and re-apply once the email domain's DNS records are verified.
email_domain_link_enabled = false

# [ASSUMPTION] The shared group holds the ~$10-11/month PostgreSQL server (AD-12).
budget_amount = 12
