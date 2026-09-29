# Prod environment values. No secrets, subscription ids or tenant ids here.
#
# Dj fills the required inputs below before the first apply (plan Decisions):
owner               = "dj"
cost_centre         = "poc"
application         = "ocrinvoicing"
data_classification = "synthetic"
alert_email         = "alerts@example.test"

# [ASSUMPTION] Prod's share of the ~$11-12/month solution (AD-12); calibrate after a month.
budget_amount = 2
