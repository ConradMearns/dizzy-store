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


linkml_meta = LinkMLMeta({'default_prefix': 'https://example.org/models/pool/',
     'default_range': 'string',
     'description': 'The pool as the replicated logs say it is. Classes: nodes '
                    '(node_id, cluster_id, epoch, role, site, location_note, '
                    'endpoints, wants, draining, announced_at); '
                    'collection_policies (collection, min_sites, '
                    'verify_max_age_days, evictable); blobs (blob_hash, byte_size, '
                    'collection, first_seen_at — all from the earliest '
                    'registration — and for chunked files chunk_size + ordered '
                    'chunk_hashes, from the earliest recipe; what EXISTS, whoever '
                    'holds it); blob_locations ((blob_hash, node_id, epoch): state '
                    "'present' | 'evicted' | 'corrupt', pinned, stored_at, "
                    'last_access_at — one row per LIFE of a node, and only rows '
                    "under the node's current epoch count, so a wiped device's old "
                    'claims never need cleaning up); scrub_state ((node_id, '
                    'collection, epoch): cursor, pass_started_at, '
                    'last_full_pass_at); peer_links ((node_id, peer_id): healthy, '
                    'changed_at). One schema, so a query can join locations with '
                    'policy, scrub state and nodes.',
     'id': 'https://example.org/models/pool',
     'imports': ['linkml:types'],
     'name': 'pool',
     'prefixes': {'linkml': {'prefix_prefix': 'linkml',
                             'prefix_reference': 'https://w3id.org/linkml/'}},
     'source_file': 'def/models/pool.yaml'} )


class Node(ConfiguredBaseModel):
    """
    One row per node_id: its latest public card (latest occurred_at wins).
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://example.org/models/pool'})

    node_id: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['Node', 'BlobLocation', 'ScrubState', 'PeerLink']} })
    cluster_id: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['Node']} })
    epoch: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['Node', 'BlobLocation', 'ScrubState']} })
    role: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['Node']} })
    site: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['Node']} })
    location_note: Optional[str] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['Node']} })
    endpoints_json: Optional[str] = Field(default=None, description="""JSON list""", json_schema_extra = { "linkml_meta": {'domain_of': ['Node']} })
    wants_json: Optional[str] = Field(default=None, description="""JSON list""", json_schema_extra = { "linkml_meta": {'domain_of': ['Node']} })
    draining: bool = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['Node']} })
    announced_at: datetime  = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['Node']} })
    digest: str = Field(default=..., description="""payload digest — the last-writer-wins tie-break""", json_schema_extra = { "linkml_meta": {'domain_of': ['Node', 'CollectionPolicy', 'Blob', 'PeerLink']} })


class CollectionPolicy(ConfiguredBaseModel):
    """
    One row per collection: the latest declared policy.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://example.org/models/pool'})

    collection: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['CollectionPolicy', 'Blob', 'ScrubState']} })
    min_sites: int = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['CollectionPolicy']} })
    verify_max_age_days: int = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['CollectionPolicy']} })
    evictable: bool = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['CollectionPolicy']} })
    declared_at: datetime  = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['CollectionPolicy']} })
    digest: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['Node', 'CollectionPolicy', 'Blob', 'PeerLink']} })


class Blob(ConfiguredBaseModel):
    """
    One row per registered blob — what EXISTS, whoever holds it.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://example.org/models/pool'})

    blob_hash: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['Blob', 'BlobLocation']} })
    byte_size: int = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['Blob']} })
    collection: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['CollectionPolicy', 'Blob', 'ScrubState']} })
    first_seen_at: datetime  = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['Blob']} })
    digest: str = Field(default=..., description="""payload digest of the earliest registration — the tie-break""", json_schema_extra = { "linkml_meta": {'domain_of': ['Node', 'CollectionPolicy', 'Blob', 'PeerLink']} })
    chunk_size: Optional[int] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['Blob']} })
    chunk_hashes_json: Optional[str] = Field(default=None, description="""JSON list; large files only""", json_schema_extra = { "linkml_meta": {'domain_of': ['Blob']} })
    chunk_at: Optional[datetime ] = Field(default=None, description="""when the earliest recipe was registered""", json_schema_extra = { "linkml_meta": {'domain_of': ['Blob']} })
    chunk_digest: Optional[str] = Field(default=None, description="""payload digest of the earliest recipe""", json_schema_extra = { "linkml_meta": {'domain_of': ['Blob']} })


class BlobLocation(ConfiguredBaseModel):
    """
    One row per (blob, node, epoch): a node's claim to hold a blob in one life of it.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://example.org/models/pool'})

    id: str = Field(default=..., description="""node_id|epoch|blob_hash""", json_schema_extra = { "linkml_meta": {'domain_of': ['BlobLocation', 'ScrubState', 'PeerLink']} })
    blob_hash: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['Blob', 'BlobLocation']} })
    node_id: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['Node', 'BlobLocation', 'ScrubState', 'PeerLink']} })
    epoch: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['Node', 'BlobLocation', 'ScrubState']} })
    state: str = Field(default=..., description="""'present' | 'evicted' | 'corrupt'""", json_schema_extra = { "linkml_meta": {'domain_of': ['BlobLocation']} })
    pinned: bool = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['BlobLocation']} })
    stored_at: Optional[datetime ] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['BlobLocation']} })
    last_access_at: Optional[datetime ] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['BlobLocation']} })


class ScrubState(ConfiguredBaseModel):
    """
    One row per (node, epoch, collection): where scrub resumes, and the last full pass.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://example.org/models/pool'})

    id: str = Field(default=..., description="""node_id|epoch|collection ('' = all)""", json_schema_extra = { "linkml_meta": {'domain_of': ['BlobLocation', 'ScrubState', 'PeerLink']} })
    node_id: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['Node', 'BlobLocation', 'ScrubState', 'PeerLink']} })
    epoch: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['Node', 'BlobLocation', 'ScrubState']} })
    collection: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['CollectionPolicy', 'Blob', 'ScrubState']} })
    cursor: Optional[str] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['ScrubState']} })
    pass_started_at: Optional[datetime ] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['ScrubState']} })
    last_full_pass_at: Optional[datetime ] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['ScrubState']} })


class PeerLink(ConfiguredBaseModel):
    """
    One row per (node, peer): the link state as that node last recorded it.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://example.org/models/pool'})

    id: str = Field(default=..., description="""node_id|peer_id""", json_schema_extra = { "linkml_meta": {'domain_of': ['BlobLocation', 'ScrubState', 'PeerLink']} })
    node_id: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['Node', 'BlobLocation', 'ScrubState', 'PeerLink']} })
    peer_id: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['PeerLink']} })
    healthy: bool = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['PeerLink']} })
    changed_at: datetime  = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['PeerLink']} })
    digest: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['Node', 'CollectionPolicy', 'Blob', 'PeerLink']} })


# Model rebuild
# see https://pydantic-docs.helpmanual.io/usage/models/#rebuilding-a-model
Node.model_rebuild()
CollectionPolicy.model_rebuild()
Blob.model_rebuild()
BlobLocation.model_rebuild()
ScrubState.model_rebuild()
PeerLink.model_rebuild()
