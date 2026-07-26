"""Fixed official-source adapters."""

from breachgazette.clients.base import AdapterResult, SourceClientError
from breachgazette.clients.california import CaliforniaAdapter
from breachgazette.clients.france_cnil import CnilAdapter
from breachgazette.clients.ipc_nsw import NswAggregateAdapter, NswPublicNotificationsAdapter
from breachgazette.clients.massachusetts import MassachusettsAdapter
from breachgazette.clients.netherlands_ap import NetherlandsApAdapter
from breachgazette.clients.oaic import OaicNdbAdapter
from breachgazette.clients.oaic_regulatory import OaicRegulatoryAdapter
from breachgazette.clients.uk_ico import UnitedKingdomIcoAdapter
from breachgazette.clients.washington import WashingtonAdapter

__all__ = [
    "AdapterResult",
    "CaliforniaAdapter",
    "CnilAdapter",
    "MassachusettsAdapter",
    "NetherlandsApAdapter",
    "NswAggregateAdapter",
    "NswPublicNotificationsAdapter",
    "OaicNdbAdapter",
    "OaicRegulatoryAdapter",
    "SourceClientError",
    "UnitedKingdomIcoAdapter",
    "WashingtonAdapter",
]
