# Prod environment values. No secrets, subscription ids or tenant ids here.
#
# Dj fills the P-17 tag values below before the first apply (same values as
# prod/foundation):
owner               = "dj"
cost_centre         = "poc"
application         = "ocrinvoicing"
data_classification = "synthetic"
#
# Story 2.7: the client id of babaloo-sea-lng-staff-api-prod, which
# infra/bootstrap/app-registrations.sh prints (not a secret):
# staff_api_client_id = ""
#
# Story 3.1: the client id of babaloo-sea-lng-accounts-sim-prod, which
# infra/bootstrap/app-registrations.sh prints (not a secret):
# accounts_sim_client_id = ""
#
# Story 5.2: who gets the staff alert emails, per role (empty: nobody). They go out
# only once shared/foundation has a linked email domain (infra/bootstrap/README.md).
# alert_recipients_finance     = ["finance@example.com"]
# alert_recipients_procurement = ["procurement@example.com"]
# alert_recipients_management  = ["management@example.com"]
