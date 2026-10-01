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


linkml_meta = LinkMLMeta({'default_prefix': 'https://example.org/commands/',
     'default_range': 'string',
     'id': 'https://example.org/commands',
     'imports': ['linkml:types'],
     'name': 'commands',
     'prefixes': {'linkml': {'prefix_prefix': 'linkml',
                             'prefix_reference': 'https://w3id.org/linkml/'}},
     'source_file': 'def/commands.yaml'} )


class CreateCluster(ConfiguredBaseModel):
    """
    Found the cluster: carries a generated cluster_id and occurred_at. Issued once by the first device; every other device joins by being configured with the cluster_id and syncing.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://example.org/commands'})

    cluster_id: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['create_cluster']} })
    occurred_at: datetime  = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['create_cluster',
                       'announce_node',
                       'set_collection_policy',
                       'put_blob',
                       'adopt_collection',
                       'replicate_blob',
                       'evict_blob',
                       'set_blob_pin',
                       'record_blob_access',
                       'check_capacity',
                       'sync_peer',
                       'scrub_blobs']} })


class AnnounceNode(ConfiguredBaseModel):
    """
    Declare or update this node's public card (its identity — node_id, cluster_id and epoch, this life's random id — comes from env.store): role ('hot' — small, keeps what is recent or likely read, the only role that evicts under pressure; 'archive' — big, keeps what it wants; 'cold' — a drive only sometimes online, fills when plugged in, never evicts), site, location_note (free text: \"garage shelf, box 3\"), endpoints (urls), wants (collections it wants in full, or ['*']), and draining (being retired: never a replication target or anchor, evicts what is safely elsewhere; re-announce with false to cancel). Issued by the host at startup and on config change; the latest wins.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://example.org/commands'})

    role: str = Field(default=..., description="""'hot' | 'archive' | 'cold'""", json_schema_extra = { "linkml_meta": {'domain_of': ['announce_node']} })
    site: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['announce_node']} })
    location_note: Optional[str] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['announce_node']} })
    endpoints: Optional[list[str]] = Field(default=[], description="""urls peers can reach this node at""", json_schema_extra = { "linkml_meta": {'domain_of': ['announce_node']} })
    wants: Optional[list[str]] = Field(default=[], description="""collections wanted in full, or ['*']""", json_schema_extra = { "linkml_meta": {'domain_of': ['announce_node']} })
    draining: Optional[bool] = Field(default=None, description="""being retired; absent means false""", json_schema_extra = { "linkml_meta": {'domain_of': ['announce_node']} })
    occurred_at: datetime  = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['create_cluster',
                       'announce_node',
                       'set_collection_policy',
                       'put_blob',
                       'adopt_collection',
                       'replicate_blob',
                       'evict_blob',
                       'set_blob_pin',
                       'record_blob_access',
                       'check_capacity',
                       'sync_peer',
                       'scrub_blobs']} })


class SetCollectionPolicy(ConfiguredBaseModel):
    """
    Declare a collection's policy: min_sites (distinct sites that must hold a verified copy), verify_max_age_days, and evictable (whether hot nodes may drop its bytes). Issued by the host (UI/CLI); the latest wins.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://example.org/commands'})

    collection: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['set_collection_policy',
                       'put_blob',
                       'adopt_collection',
                       'scrub_blobs']} })
    min_sites: int = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['set_collection_policy']} })
    verify_max_age_days: int = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['set_collection_policy']} })
    evictable: bool = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['set_collection_policy']} })
    occurred_at: datetime  = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['create_cluster',
                       'announce_node',
                       'set_collection_policy',
                       'put_blob',
                       'adopt_collection',
                       'replicate_blob',
                       'evict_blob',
                       'set_blob_pin',
                       'record_blob_access',
                       'check_capacity',
                       'sync_peer',
                       'scrub_blobs']} })


class PutBlob(ConfiguredBaseModel):
    """
    Record a blob the edge has ALREADY written under this node's root: sha256 blob_hash, byte_size and collection — never the bytes, never metadata — plus, for a large file, chunk_size and the ordered chunk_hashes. The edge hashes while streaming the upload, before dispatching.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://example.org/commands'})

    blob_hash: str = Field(default=..., description="""sha256 hex""", json_schema_extra = { "linkml_meta": {'domain_of': ['put_blob', 'replicate_blob', 'evict_blob', 'set_blob_pin']} })
    byte_size: int = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['put_blob']} })
    collection: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['set_collection_policy',
                       'put_blob',
                       'adopt_collection',
                       'scrub_blobs']} })
    chunk_size: Optional[int] = Field(default=None, description="""large files only""", json_schema_extra = { "linkml_meta": {'domain_of': ['put_blob']} })
    chunk_hashes: Optional[list[str]] = Field(default=[], description="""ordered chunk sha256 hexes; large files only""", json_schema_extra = { "linkml_meta": {'domain_of': ['put_blob']} })
    occurred_at: datetime  = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['create_cluster',
                       'announce_node',
                       'set_collection_policy',
                       'put_blob',
                       'adopt_collection',
                       'replicate_blob',
                       'evict_blob',
                       'set_blob_pin',
                       'record_blob_access',
                       'check_capacity',
                       'sync_peer',
                       'scrub_blobs']} })


class AdoptCollection(ConfiguredBaseModel):
    """
    Bring an existing directory under management WITHOUT touching it: record every file as a blob this node holds. Carries collection, root and layout ('cas' — a sharded <aa>/<bb>/<sha256> tree whose names are CLAIMED to be the hashes; 'tree' — arbitrary files; paths are not kept) and, optionally, link: true. Every new file is HASHED on the way in: one whose bytes do not match its name is skipped and reported, never recorded. By default each file is COPIED into this node's root, so the original can be edited or deleted without touching the store; link: true hard-links instead (same filesystem only, falling back to a copy) for a tree that nothing edits in place — it costs no extra space, and frees none when the store evicts. Issued by the host.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://example.org/commands'})

    collection: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['set_collection_policy',
                       'put_blob',
                       'adopt_collection',
                       'scrub_blobs']} })
    root: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['adopt_collection']} })
    layout: str = Field(default=..., description="""'cas' | 'tree'""", json_schema_extra = { "linkml_meta": {'domain_of': ['adopt_collection']} })
    link: Optional[bool] = Field(default=None, description="""hard-link instead of copy (same filesystem; for trees nothing edits in place)""", json_schema_extra = { "linkml_meta": {'domain_of': ['adopt_collection']} })
    occurred_at: datetime  = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['create_cluster',
                       'announce_node',
                       'set_collection_policy',
                       'put_blob',
                       'adopt_collection',
                       'replicate_blob',
                       'evict_blob',
                       'set_blob_pin',
                       'record_blob_access',
                       'check_capacity',
                       'sync_peer',
                       'scrub_blobs']} })


class ReplicateBlob(ConfiguredBaseModel):
    """
    Fetch one blob (a whole file, however chunked) from peers. Carries blob_hash, an OPTIONAL from_node, and a reason: 'replica' (a policy reacted to a fresh blob_stored), 'backfill' (the host sweep — this also repairs corrupt or missing copies) or 'read_through' (an edge miss).
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://example.org/commands'})

    blob_hash: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['put_blob', 'replicate_blob', 'evict_blob', 'set_blob_pin']} })
    from_node: Optional[str] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['replicate_blob']} })
    reason: str = Field(default=..., description="""'replica' | 'backfill' | 'read_through'""", json_schema_extra = { "linkml_meta": {'domain_of': ['replicate_blob', 'evict_blob', 'set_blob_pin']} })
    occurred_at: datetime  = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['create_cluster',
                       'announce_node',
                       'set_collection_policy',
                       'put_blob',
                       'adopt_collection',
                       'replicate_blob',
                       'evict_blob',
                       'set_blob_pin',
                       'record_blob_access',
                       'check_capacity',
                       'sync_peer',
                       'scrub_blobs']} })


class EvictBlob(ConfiguredBaseModel):
    """
    Drop this node's bytes for one blob; it stays registered and held elsewhere. Carries blob_hash and a reason ('pressure' | 'drain').
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://example.org/commands'})

    blob_hash: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['put_blob', 'replicate_blob', 'evict_blob', 'set_blob_pin']} })
    reason: str = Field(default=..., description="""'pressure' | 'drain'""", json_schema_extra = { "linkml_meta": {'domain_of': ['replicate_blob', 'evict_blob', 'set_blob_pin']} })
    occurred_at: datetime  = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['create_cluster',
                       'announce_node',
                       'set_collection_policy',
                       'put_blob',
                       'adopt_collection',
                       'replicate_blob',
                       'evict_blob',
                       'set_blob_pin',
                       'record_blob_access',
                       'check_capacity',
                       'sync_peer',
                       'scrub_blobs']} })


class SetBlobPin(ConfiguredBaseModel):
    """
    Keep (or release) this node's bytes for a blob regardless of pressure — a favorite, a book being read. Carries blob_hash, pinned, optional reason. Issued by the host.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://example.org/commands'})

    blob_hash: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['put_blob', 'replicate_blob', 'evict_blob', 'set_blob_pin']} })
    pinned: bool = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['set_blob_pin']} })
    reason: Optional[str] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['replicate_blob', 'evict_blob', 'set_blob_pin']} })
    occurred_at: datetime  = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['create_cluster',
                       'announce_node',
                       'set_collection_policy',
                       'put_blob',
                       'adopt_collection',
                       'replicate_blob',
                       'evict_blob',
                       'set_blob_pin',
                       'record_blob_access',
                       'check_capacity',
                       'sync_peer',
                       'scrub_blobs']} })


class RecordBlobAccess(ConfiguredBaseModel):
    """
    Flush the edge's coalesced read times (one event per read would flood the log): a batch of (blob_hash, last_access_at). Issued by the host periodically; drives LRU eviction.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://example.org/commands'})

    blob_hashes: list[str] = Field(default=..., description="""parallel with last_access_ats""", json_schema_extra = { "linkml_meta": {'domain_of': ['record_blob_access']} })
    last_access_ats: list[datetime ] = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['record_blob_access']} })
    occurred_at: datetime  = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['create_cluster',
                       'announce_node',
                       'set_collection_policy',
                       'put_blob',
                       'adopt_collection',
                       'replicate_blob',
                       'evict_blob',
                       'set_blob_pin',
                       'record_blob_access',
                       'check_capacity',
                       'sync_peer',
                       'scrub_blobs']} })


class CheckCapacity(ConfiguredBaseModel):
    """
    Measure this node's storage use against its limit and watermarks. Carries nothing. Issued by the host on a cron tick and after large puts.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://example.org/commands'})

    occurred_at: datetime  = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['create_cluster',
                       'announce_node',
                       'set_collection_policy',
                       'put_blob',
                       'adopt_collection',
                       'replicate_blob',
                       'evict_blob',
                       'set_blob_pin',
                       'record_blob_access',
                       'check_capacity',
                       'sync_peer',
                       'scrub_blobs']} })


class SyncPeer(ConfiguredBaseModel):
    """
    Exchange logs with one peer. Carries peer_id and direction ('pull' | 'push' — ask the peer to pull from this node | 'both'). Issued by the host (cron) and by policy when a peer announces.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://example.org/commands'})

    peer_id: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['sync_peer']} })
    direction: str = Field(default=..., description="""'pull' | 'push' | 'both'""", json_schema_extra = { "linkml_meta": {'domain_of': ['sync_peer']} })
    occurred_at: datetime  = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['create_cluster',
                       'announce_node',
                       'set_collection_policy',
                       'put_blob',
                       'adopt_collection',
                       'replicate_blob',
                       'evict_blob',
                       'set_blob_pin',
                       'record_blob_access',
                       'check_capacity',
                       'sync_peer',
                       'scrub_blobs']} })


class ScrubBlobs(ConfiguredBaseModel):
    """
    Integrity sweep over this node's held blobs. Carries an optional collection and max_bytes (this run's budget). Issued by the host on a slow cron.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://example.org/commands'})

    collection: Optional[str] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['set_collection_policy',
                       'put_blob',
                       'adopt_collection',
                       'scrub_blobs']} })
    max_bytes: int = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['scrub_blobs']} })
    occurred_at: datetime  = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['create_cluster',
                       'announce_node',
                       'set_collection_policy',
                       'put_blob',
                       'adopt_collection',
                       'replicate_blob',
                       'evict_blob',
                       'set_blob_pin',
                       'record_blob_access',
                       'check_capacity',
                       'sync_peer',
                       'scrub_blobs']} })


# Model rebuild
# see https://pydantic-docs.helpmanual.io/usage/models/#rebuilding-a-model
CreateCluster.model_rebuild()
AnnounceNode.model_rebuild()
SetCollectionPolicy.model_rebuild()
PutBlob.model_rebuild()
AdoptCollection.model_rebuild()
ReplicateBlob.model_rebuild()
EvictBlob.model_rebuild()
SetBlobPin.model_rebuild()
RecordBlobAccess.model_rebuild()
CheckCapacity.model_rebuild()
SyncPeer.model_rebuild()
ScrubBlobs.model_rebuild()
