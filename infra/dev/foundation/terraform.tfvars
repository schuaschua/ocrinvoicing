# Dev environment values. No secrets, subscription ids or tenant ids here.
#
# Dj fills the required inputs below before the first apply (plan Decisions):
# owner               = ""
# cost_centre         = ""
# application         = ""
# data_classification = ""
# alert_email         = ""

# [ASSUMPTION] Dev's share of the ~$11-12/month solution (AD-12); calibrate after a month.
budget_amount = 2

# [ASSUMPTION] Sampling on (AD-17); the percentage is not fixed by the architecture.
app_insights_sampling_percentage = 50
