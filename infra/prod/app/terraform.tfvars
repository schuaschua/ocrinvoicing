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
staff_api_client_id = "62418322-4d3b-4d76-8f9f-8ed23446bfa3"
#
# Story 3.1: the client id of babaloo-sea-lng-accounts-sim-prod, which
# infra/bootstrap/app-registrations.sh prints (not a secret):
accounts_sim_client_id = "d52636e8-616e-4ac8-baff-9870d1e81f86"
#
# Story 5.2: who gets the staff alert emails, per role (empty: nobody). They go out
# only once shared/foundation has a linked email domain (infra/bootstrap/README.md).
# alert_recipients_finance     = ["finance@example.com"]
# alert_recipients_procurement = ["procurement@example.com"]
# alert_recipients_management  = ["management@example.com"]
