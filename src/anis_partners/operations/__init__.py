"""Route metadata shared by operations and contract-drift checks."""

from anis_partners.operations.groups import (
    AsyncAccessOperations,
    AsyncCatalogueOperations,
    AsyncDiagnosticsOperations,
    AsyncOrderOperations,
    AsyncOwnedCardOperations,
    AsyncProfileOperations,
    AsyncWalletOperations,
    SyncAccessOperations,
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
    "AsyncAccessOperations",
    "AsyncCatalogueOperations",
    "AsyncDiagnosticsOperations",
    "AsyncOrderOperations",
    "AsyncOwnedCardOperations",
    "AsyncProfileOperations",
    "AsyncWalletOperations",
    "PartnerRoute",
    "SyncAccessOperations",
    "SyncCatalogueOperations",
    "SyncDiagnosticsOperations",
    "SyncOrderOperations",
    "SyncOwnedCardOperations",
    "SyncProfileOperations",
    "SyncWalletOperations",
]
