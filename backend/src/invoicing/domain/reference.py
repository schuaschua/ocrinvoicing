"""The supplier reference shown on the Received screen (EXPERIENCE.md "Supplier
reference"): `R-` and 8 Crockford base32 characters, for example `R-7Q4KXM2D`.

It is taken from the random part (`rand_b`) of the invoice's UUIDv7, never from its
timestamp, so references don't reveal when or in what order invoices arrived. It is
derived, never stored: the same `invoice_id` always gives the same reference.

References are not unique: 8 characters hold 40 random bits, so two invoices share one
with a chance of about n^2 / 2^41 among n invoices, which becomes likely at around a
million invoices. Staff search by reference therefore also narrows by supplier and
date.
"""

from uuid import UUID

# Crockford's alphabet: no I, L, O or U, so a reference read aloud or typed can't be
# mistaken for another.
ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
PREFIX = "R-"
LENGTH = 8
_BITS_PER_CHAR = 5
# rand_b is the low 62 bits of a UUIDv7 (RFC 9562); 8 characters use its low 40.
_USED_BITS_MASK = (1 << (_BITS_PER_CHAR * LENGTH)) - 1


def supplier_reference(invoice_id: UUID) -> str:
    """The reference of `invoice_id`, which must be a UUIDv7."""
    if invoice_id.version != 7:
        raise ValueError("a supplier reference needs a UUIDv7 invoice id")
    bits = invoice_id.int & _USED_BITS_MASK
    chars = [
        ALPHABET[(bits >> (_BITS_PER_CHAR * i)) & 0b11111]
        for i in reversed(range(LENGTH))
    ]
    return PREFIX + "".join(chars)
