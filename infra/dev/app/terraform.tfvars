# Dev environment values. No secrets, subscription ids or tenant ids here.
#
# Dj fills the P-17 tag values below before the first apply (same values as
# dev/foundation):
owner               = "dj"
cost_centre         = "poc"
application         = "ocrinvoicing"
data_classification = "synthetic"
#
# Story 2.7: the client id of babaloo-sea-lng-staff-api-dev, which
# infra/bootstrap/app-registrations.sh prints (not a secret):
staff_api_client_id = "03943d18-836f-4685-abf7-39334e0c041b"
#
# Story 3.1: the client id of babaloo-sea-lng-accounts-sim-dev, which
# infra/bootstrap/app-registrations.sh prints (not a secret):
accounts_sim_client_id = "5ab1d364-f5e2-4b82-911b-9b359855781f"
