import uuid

from pydantic import BaseModel


class GroupOut(BaseModel):
    """A group with what it resolved to (D-001); names are current, identifiers stable."""

    group_id: uuid.UUID
    name: str
    tally_guid: str
    parent_group_id: uuid.UUID | None
    is_predefined: bool
    reserved_name: str | None
    predefined_group: str | None  # nearest predefined group, including itself
    anchor: str | None  # the classification anchor
    primary_group: str | None
    nature: str | None
    resolution_status: str
    status: str


class VoucherTypeOut(BaseModel):
    voucher_type_id: uuid.UUID
    name: str
    tally_guid: str
    parent_voucher_type_id: uuid.UUID | None
    reserved_name: str | None
    base_voucher_type: str
    resolution_status: str
    status: str
