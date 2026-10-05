"""Route metadata shared by operations and contract-drift checks."""

from anis_partners.operations.groups import (
    AsyncCatalogueOperations,
    AsyncDiagnosticsOperations,
    AsyncOrderOperations,
    AsyncOwnedCardOperations,
    AsyncProfileOperations,
    AsyncWalletOperations,
    SyncCatalogueOperations,
    SyncDiagnosticsOperations,
    SyncOrderOperations,
    SyncOwnedCardOperations,
    SyncProfileOperations,
    SyncWalletOperations,
)
from anis_partners.operations.routes import PARTNER_ROUTES, PartnerRoute

__all__ = [
    "PARTNER_ROUTES",
    "AsyncCatalogueOperations",
    "AsyncDiagnosticsOperations",
    "AsyncOrderOperations",
    "AsyncOwnedCardOperations",
    "AsyncProfileOperations",
    "AsyncWalletOperations",
    "PartnerRoute",
    "SyncCatalogueOperations",
    "SyncDiagnosticsOperations",
    "SyncOrderOperations",
    "SyncOwnedCardOperations",
    "SyncProfileOperations",
    "SyncWalletOperations",
]
