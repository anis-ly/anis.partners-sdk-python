"""Matchable product outcomes keep unresolved work attached to the caller's saved id."""

from dataclasses import dataclass, field
from datetime import timedelta
from typing import TypeAlias
from uuid import UUID

from anis_partners.errors.base import AnisPartnersError
from anis_partners.models.direct_recharges import DirectRecharge, DirectRechargeAccepted
from anis_partners.models.meter_charges import MeterCharge, MeterChargeAccepted


@dataclass(frozen=True, slots=True)
class MeterChargeProcessing:
    charge: MeterCharge | MeterChargeAccepted = field(repr=False)
    retry_after: timedelta
    location: str | None = None

    @property
    def operation_id(self) -> UUID:
        return self.charge.operation_id


@dataclass(frozen=True, slots=True)
class MeterChargeFinal:
    charge: MeterCharge = field(repr=False)

    @property
    def operation_id(self) -> UUID:
        return self.charge.operation_id


@dataclass(frozen=True, slots=True)
class MeterChargeNotPlaced:
    operation_id: UUID
    refusal: AnisPartnersError = field(repr=False)


@dataclass(frozen=True, slots=True)
class MeterChargeOutcomeUnknown:
    operation_id: UUID
    suggested_delay: timedelta
    cause: Exception = field(repr=False)


MeterChargeResult: TypeAlias = (
    MeterChargeProcessing | MeterChargeFinal | MeterChargeNotPlaced | MeterChargeOutcomeUnknown
)


@dataclass(frozen=True, slots=True)
class DirectRechargeProcessing:
    recharge: DirectRecharge | DirectRechargeAccepted = field(repr=False)
    retry_after: timedelta
    location: str | None = None

    @property
    def operation_id(self) -> UUID:
        return self.recharge.operation_id


@dataclass(frozen=True, slots=True)
class DirectRechargeFinal:
    recharge: DirectRecharge = field(repr=False)

    @property
    def operation_id(self) -> UUID:
        return self.recharge.operation_id


@dataclass(frozen=True, slots=True)
class DirectRechargeNotPlaced:
    operation_id: UUID
    refusal: AnisPartnersError = field(repr=False)


@dataclass(frozen=True, slots=True)
class DirectRechargeOutcomeUnknown:
    operation_id: UUID
    suggested_delay: timedelta
    cause: Exception = field(repr=False)


DirectRechargeResult: TypeAlias = (
    DirectRechargeProcessing | DirectRechargeFinal | DirectRechargeNotPlaced | DirectRechargeOutcomeUnknown
)
