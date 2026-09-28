"""`GET /api/me`: who the staff app is signed in as (AD-14, Story 2.7).

The staff app builds its sidebar and landing page from the roles. Only the display
name and the app roles are returned: no object id, email or other claim."""

from uuid import UUID

import azure.functions as func

from invoicing.adapters.http import Endpoint, json_response
from invoicing.adapters.principal import staff_endpoint
from invoicing.domain.roles import StaffPrincipal


def me_endpoint(*, platform_auth_trusted: bool = True) -> Endpoint:
    """200 `{name, roles}` for any signed-in user, `roles` in landing order (empty when
    they hold no app role: the staff app shows its no-access page); 401 otherwise."""

    async def me(
        req: func.HttpRequest, correlation_id: UUID, principal: StaffPrincipal
    ) -> func.HttpResponse:
        return json_response(
            {
                "name": principal.name,
                "roles": [role.value for role in principal.roles],
            },
            status=200,
            correlation_id=correlation_id,
        )

    return staff_endpoint(me, surface=None, platform_auth_trusted=platform_auth_trusted)
