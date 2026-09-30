"""Goods-in scan (Story 4.1, CAP-2, AD-5, AD-6): a goods-in worker picks a delivery and
sends the paper invoice that came with it.

- `GET api/goods-in/deliveries`: without `q`, the deliveries dated today (Singapore);
  with `q` (2 to 64 characters after trimming), those of the last 60 days whose PO
  number starts with it or whose supplier's master name contains it, both in any case,
  newest first, at most 50. Each with its PO, supplier name and delivery number.
- `POST api/goods-in/deliveries/{delivery_id}/upload`: the raw file, as the supplier
  upload takes it (4 MB, JPEG/PNG/PDF by content, `Idempotency-Key`, optional
  `X-Device-Check`). The delivery is looked up first, so an unknown one is 404
  `DELIVERY_NOT_FOUND` and a stopped database 503 `DB_OFFLINE`, both with nothing
  written. The supplier is always the delivery's (`PurchasingPort.get_delivery`),
  never one the worker chose or the invoice names (AD-5). Then the shared intake
  (`apps/intake_upload.py`): key, blob, `q-quality`. Answers `{invoice_id, po_number,
  supplier_name}`.

`Surface.GOODS_IN_SCAN` (goods_in only): 401 signed out, 403 for any other role, and
403 for a POST without `X-Requested-With`, before anything is read. No value sent or
read (a search text, a name, the file) is ever logged.
"""

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from uuid import UUID

import azure.functions as func

from invoicing.adapters.http import Endpoint, json_response
from invoicing.adapters.principal import staff_endpoint
from invoicing.apps.intake_upload import UploadOwner, accept_upload, checked_upload
from invoicing.domain.dates import singapore_date
from invoicing.domain.errors import DeliveryNotFoundError, ValidationFailedError
from invoicing.domain.ids import parse_uuid
from invoicing.domain.roles import StaffPrincipal, Surface
from invoicing.ports.blobs import ImageStore
from invoicing.ports.intake import IntakeSource
from invoicing.ports.purchasing import Delivery, PurchasingPort
from invoicing.ports.queue import QueueSender
from invoicing.ports.suppliers import SupplierDirectory
from invoicing.ports.upload_keys import UploadKeyStore

MIN_QUERY = 2
MAX_QUERY = 64
SEARCH_DAYS = 60
MAX_RESULTS = 50
QUERY_MESSAGE = "Search with 2 to 64 characters of a PO number or supplier name."


def _now() -> datetime:
    return datetime.now(UTC)


def _newest_first(delivery: Delivery) -> tuple[int, str, int]:
    return (
        -delivery.delivery_date.toordinal(),
        delivery.po_number,
        delivery.delivery_no,
    )


def goods_in_endpoints(
    purchasing: PurchasingPort,
    suppliers: SupplierDirectory,
    keys: Callable[[], UploadKeyStore],
    images: Callable[[], ImageStore],
    queue: Callable[[], QueueSender],
    *,
    platform_auth_trusted: bool,
    clock: Callable[[], datetime] | None = None,
) -> tuple[Endpoint, Endpoint]:
    """(deliveries, upload). `platform_auth_trusted` has no default: the wiring must
    always pass the setting (AD-14: fail closed). `clock` defaults to the current UTC
    time."""

    def now() -> datetime:
        return (clock or _now)()

    async def deliveries(
        req: func.HttpRequest, correlation_id: UUID, principal: StaffPrincipal
    ) -> func.HttpResponse:
        today = singapore_date(now())
        text = req.params.get("q")
        if text is None:
            found = list(await purchasing.list_deliveries(today))
        else:
            text = text.strip()
            if not MIN_QUERY <= len(text) <= MAX_QUERY:
                raise ValidationFailedError(QUERY_MESSAGE)
            since = today - timedelta(days=SEARCH_DAYS)
            by_id = {
                d.delivery_id: d
                for d in await purchasing.search_deliveries(text, since)
            }
            # Purchasing has no supplier names: a name match is the master's, then
            # those suppliers' recent deliveries.
            named = await suppliers.matching(text)
            if named:
                for delivery in await purchasing.search_deliveries("", since):
                    if delivery.supplier_id in named:
                        by_id.setdefault(delivery.delivery_id, delivery)
            found = sorted(by_id.values(), key=_newest_first)[:MAX_RESULTS]
        names = await suppliers.names({d.supplier_id for d in found})
        return json_response(
            {
                "today": today.isoformat(),
                "items": [
                    {
                        "delivery_id": str(d.delivery_id),
                        "po_number": d.po_number,
                        "delivery_no": d.delivery_no,
                        "delivery_date": d.delivery_date.isoformat(),
                        "supplier_name": names.get(d.supplier_id),
                    }
                    for d in found
                ],
            },
            status=200,
            correlation_id=correlation_id,
        )

    async def goods_in_upload(
        req: func.HttpRequest, correlation_id: UUID, principal: StaffPrincipal
    ) -> func.HttpResponse:
        # The delivery first (404 or 503), then the file; nothing is written before
        # both. A stopped database writes nothing.
        delivery_id = parse_uuid(req.route_params.get("delivery_id"))
        delivery = (
            None if delivery_id is None else await purchasing.get_delivery(delivery_id)
        )
        if delivery is None:
            raise DeliveryNotFoundError()
        names = await suppliers.names([delivery.supplier_id])
        upload = checked_upload(req)
        stored = await accept_upload(
            upload,
            # AD-5: the delivery's supplier, never the invoice's or the worker's.
            UploadOwner(
                supplier_id=delivery.supplier_id,
                source=IntakeSource.GOODS_IN,
                delivery_id=delivery.delivery_id,
            ),
            correlation_id=correlation_id,
            now=now(),
            keys=keys(),
            images=images(),
            queue=queue(),
        )
        return json_response(
            {
                "invoice_id": str(stored.invoice_id),
                "po_number": delivery.po_number,
                "supplier_name": names.get(delivery.supplier_id),
            },
            status=200,
            correlation_id=correlation_id,
        )

    return (
        staff_endpoint(
            deliveries,
            surface=Surface.GOODS_IN_SCAN,
            platform_auth_trusted=platform_auth_trusted,
        ),
        staff_endpoint(
            goods_in_upload,
            surface=Surface.GOODS_IN_SCAN,
            platform_auth_trusted=platform_auth_trusted,
        ),
    )
