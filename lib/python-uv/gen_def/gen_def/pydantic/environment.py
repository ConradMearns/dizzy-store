from __future__ import annotations

import re
import sys
from datetime import (
    date,
    datetime,
    time
)
from decimal import Decimal
from enum import Enum
from typing import (
    Any,
    ClassVar,
    Literal,
    Optional,
    Union
)

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    RootModel,
    SerializationInfo,
    SerializerFunctionWrapHandler,
    field_validator,
    model_serializer
)


metamodel_version = "None"
version = "None"


class ConfiguredBaseModel(BaseModel):
    model_config = ConfigDict(
        serialize_by_alias = True,
        validate_by_name = True,
        validate_assignment = True,
        validate_default = True,
        extra = "forbid",
        arbitrary_types_allowed = True,
        use_enum_values = True,
        strict = False,
    )

    @model_serializer(mode='wrap', when_used='unless-none')
    def treat_empty_lists_as_none(
            self, handler: SerializerFunctionWrapHandler,
            info: SerializationInfo) -> dict[str, Any]:
        if info.exclude_none:
            _instance = self.model_copy()
            for field, field_info in type(_instance).model_fields.items():
                if getattr(_instance, field) == [] and not(
                        field_info.is_required()):
                    setattr(_instance, field, None)
        else:
            _instance = self
        return handler(_instance, info)



class LinkMLMeta(RootModel):
    root: dict[str, Any] = {}
    model_config = ConfigDict(frozen=True)

    def __getattr__(self, key:str):
        return getattr(self.root, key)

    def __getitem__(self, key:str):
        return self.root[key]

    def __setitem__(self, key:str, value):
        self.root[key] = value

    def __contains__(self, key:str) -> bool:
        return key in self.root


linkml_meta = LinkMLMeta({'default_prefix': 'https://example.org/environment/',
     'default_range': 'string',
     'id': 'https://example.org/environment',
     'imports': ['linkml:types'],
     'name': 'environment',
     'prefixes': {'linkml': {'prefix_prefix': 'linkml',
                             'prefix_reference': 'https://w3id.org/linkml/'}},
     'source_file': 'def/environment.yaml'} )


class Store(ConfiguredBaseModel):
    """
    This node's config: node_id (stable, unique in the pool); cluster_id (unset until it founds or joins one); epoch (random, generated once when the device's state is created — a wiped device gets a new one); root (the sharded <aa>/<bb>/<sha256> blob tree — on the server, the EXISTING cas/); state_dir (<root>/.store/: identity, log, config — what makes the device portable); tmp_dir and quarantine_dir (same filesystem as root, for staging and atomic moves); limit_bytes with high_watermark / low_watermark (fractions of it that start and stop eviction); the pacing knobs of principle 9 (live_window_s, max_dispatch_per_event, max_bytes_per_sec, scrub_bytes_per_sec); and chunk_threshold_bytes / chunk_size for the edge; and min_free_bytes (principle 11; 0 = off). Injected by the host from its layered configuration.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://example.org/environment'})

    node_id: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['store']} })
    cluster_id: Optional[str] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['store']} })
    epoch: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['store']} })
    root: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['store', 'disk']} })
    state_dir: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['store']} })
    tmp_dir: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['store']} })
    quarantine_dir: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['store']} })
    limit_bytes: int = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['store']} })
    high_watermark: float = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['store']} })
    low_watermark: float = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['store']} })
    live_window_s: int = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['store']} })
    max_dispatch_per_event: int = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['store']} })
    max_bytes_per_sec: int = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['store']} })
    scrub_bytes_per_sec: int = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['store']} })
    chunk_threshold_bytes: int = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['store']} })
    chunk_size: int = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['store']} })
    min_free_bytes: Optional[int] = Field(default=None, description="""the filesystem must keep this much free; absent or 0 = off""", json_schema_extra = { "linkml_meta": {'domain_of': ['store']} })


class Disk(ConfiguredBaseModel):
    """
    How much room the filesystem under root has left for an ordinary (non-root) writer: free_bytes() — statvfs f_bavail, which excludes the blocks ext4 reserves for root. Host-implemented, because it is an observation of the machine and not a fact; a simulation supplies its own.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://example.org/environment'})

    root: Optional[str] = Field(default=None, description="""informational: the directory whose filesystem is measured""", json_schema_extra = { "linkml_meta": {'domain_of': ['store', 'disk']} })


class Peers(ConfiguredBaseModel):
    """
    A client for reaching other nodes by node_id over any private link — a Tailscale tailnet (stable names, NAT traversal) or an SSH tunnel. Addresses are the endpoints peers announce (a card's endpoints are plain URLs), bootstrapped by seeds and by the endpoint hint a peer sends when it asks to be pulled; peers authenticate with a shared bearer token (or tailnet identity where available). The transport (HTTP: bucketed anti-entropy, ranged blob streaming) is the host's.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://example.org/environment'})

    seeds: Optional[list[str]] = Field(default=[], description="""bootstrap addresses for first contact""", json_schema_extra = { "linkml_meta": {'domain_of': ['peers']} })


# Model rebuild
# see https://pydantic-docs.helpmanual.io/usage/models/#rebuilding-a-model
Store.model_rebuild()
Disk.model_rebuild()
Peers.model_rebuild()
