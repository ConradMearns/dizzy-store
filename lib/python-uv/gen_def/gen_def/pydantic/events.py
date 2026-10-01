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


linkml_meta = LinkMLMeta({'default_prefix': 'https://example.org/events/',
     'default_range': 'string',
     'id': 'https://example.org/events',
     'imports': ['linkml:types'],
     'name': 'events',
     'prefixes': {'linkml': {'prefix_prefix': 'linkml',
                             'prefix_reference': 'https://w3id.org/linkml/'}},
     'source_file': 'def/events.yaml'} )


class ClusterCreated(ConfiguredBaseModel):
    """
    [cluster] The cluster was founded (cluster_id, created_by — node_id, occurred_at). The log is self-describing: a surviving log alone names the cluster.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://example.org/events'})

    cluster_id: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['cluster_created', 'node_announced']} })
    created_by: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['cluster_created']} })
    occurred_at: datetime  = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['cluster_created',
                       'node_announced',
                       'collection_policy_set',
                       'blob_registered',
                       'blob_stored',
                       'blob_evicted',
                       'blob_pin_set',
                       'blob_access_recorded',
                       'blob_corrupt',
                       'blob_replication_failed',
                       'space_pressure_detected',
                       'scrub_completed',
                       'peer_link_changed']} })


class NodeAnnounced(ConfiguredBaseModel):
    """
    [cluster] A node's public card (node_id, cluster_id, epoch, role, site, location_note, endpoints, wants, draining, occurred_at). Latest occurred_at per node_id wins (ties: payload digest); its epoch is the node's CURRENT life — locations claimed under any other epoch stop counting.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://example.org/events'})

    node_id: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['node_announced',
                       'blob_stored',
                       'blob_evicted',
                       'blob_pin_set',
                       'blob_access_recorded',
                       'blob_corrupt',
                       'blob_replication_failed',
                       'space_pressure_detected',
                       'scrub_completed',
                       'peer_link_changed']} })
    cluster_id: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['cluster_created', 'node_announced']} })
    epoch: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['node_announced',
                       'blob_stored',
                       'blob_evicted',
                       'blob_pin_set',
                       'blob_access_recorded',
                       'blob_corrupt',
                       'scrub_completed']} })
    role: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['node_announced']} })
    site: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['node_announced']} })
    location_note: Optional[str] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['node_announced']} })
    endpoints: Optional[list[str]] = Field(default=[], json_schema_extra = { "linkml_meta": {'domain_of': ['node_announced']} })
    wants: Optional[list[str]] = Field(default=[], json_schema_extra = { "linkml_meta": {'domain_of': ['node_announced']} })
    draining: Optional[bool] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['node_announced']} })
    occurred_at: datetime  = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['cluster_created',
                       'node_announced',
                       'collection_policy_set',
                       'blob_registered',
                       'blob_stored',
                       'blob_evicted',
                       'blob_pin_set',
                       'blob_access_recorded',
                       'blob_corrupt',
                       'blob_replication_failed',
                       'space_pressure_detected',
                       'scrub_completed',
                       'peer_link_changed']} })


class CollectionPolicySet(ConfiguredBaseModel):
    """
    [cluster] A collection's policy (collection, min_sites, verify_max_age_days, evictable, occurred_at). Latest occurred_at per collection wins (ties: payload digest).
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://example.org/events'})

    collection: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['collection_policy_set', 'blob_registered', 'scrub_completed']} })
    min_sites: int = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['collection_policy_set']} })
    verify_max_age_days: int = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['collection_policy_set']} })
    evictable: bool = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['collection_policy_set']} })
    occurred_at: datetime  = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['cluster_created',
                       'node_announced',
                       'collection_policy_set',
                       'blob_registered',
                       'blob_stored',
                       'blob_evicted',
                       'blob_pin_set',
                       'blob_access_recorded',
                       'blob_corrupt',
                       'blob_replication_failed',
                       'space_pressure_detected',
                       'scrub_completed',
                       'peer_link_changed']} })


class BlobRegistered(ConfiguredBaseModel):
    """
    [cluster] A blob EXISTS in the cluster (blob_hash, byte_size, collection, occurred_at — and, for a large file only, chunk_size and the ordered chunk_hashes, the recipe peers fetch it by), whoever holds it. Recorded by whichever device first puts or adopts it; a set — the first wins, a later one carrying chunking may fill it in if absent.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://example.org/events'})

    blob_hash: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['blob_registered',
                       'blob_stored',
                       'blob_evicted',
                       'blob_pin_set',
                       'blob_corrupt',
                       'blob_replication_failed']} })
    byte_size: int = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['blob_registered']} })
    collection: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['collection_policy_set', 'blob_registered', 'scrub_completed']} })
    chunk_size: Optional[int] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['blob_registered']} })
    chunk_hashes: Optional[list[str]] = Field(default=[], json_schema_extra = { "linkml_meta": {'domain_of': ['blob_registered']} })
    occurred_at: datetime  = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['cluster_created',
                       'node_announced',
                       'collection_policy_set',
                       'blob_registered',
                       'blob_stored',
                       'blob_evicted',
                       'blob_pin_set',
                       'blob_access_recorded',
                       'blob_corrupt',
                       'blob_replication_failed',
                       'space_pressure_detected',
                       'scrub_completed',
                       'peer_link_changed']} })


class BlobStored(ConfiguredBaseModel):
    """
    [device] A node holds the COMPLETE, verified blob (node_id, epoch, blob_hash, source — 'upload' | 'adopted' | 'replica' | 'backfill' | 'read_through', occurred_at). For a chunked file, recorded only once it is assembled. Also the replication request: peers' policies react to it. Size and collection come from blob_registered.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://example.org/events'})

    node_id: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['node_announced',
                       'blob_stored',
                       'blob_evicted',
                       'blob_pin_set',
                       'blob_access_recorded',
                       'blob_corrupt',
                       'blob_replication_failed',
                       'space_pressure_detected',
                       'scrub_completed',
                       'peer_link_changed']} })
    epoch: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['node_announced',
                       'blob_stored',
                       'blob_evicted',
                       'blob_pin_set',
                       'blob_access_recorded',
                       'blob_corrupt',
                       'scrub_completed']} })
    blob_hash: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['blob_registered',
                       'blob_stored',
                       'blob_evicted',
                       'blob_pin_set',
                       'blob_corrupt',
                       'blob_replication_failed']} })
    source: str = Field(default=..., description="""'upload' | 'adopted' | 'replica' | 'backfill' | 'read_through'""", json_schema_extra = { "linkml_meta": {'domain_of': ['blob_stored']} })
    occurred_at: datetime  = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['cluster_created',
                       'node_announced',
                       'collection_policy_set',
                       'blob_registered',
                       'blob_stored',
                       'blob_evicted',
                       'blob_pin_set',
                       'blob_access_recorded',
                       'blob_corrupt',
                       'blob_replication_failed',
                       'space_pressure_detected',
                       'scrub_completed',
                       'peer_link_changed']} })


class BlobEvicted(ConfiguredBaseModel):
    """
    [device] A node dropped its bytes (node_id, epoch, blob_hash, reason, confirmed_sites — how many other sites were confirmed holding it, occurred_at). The blob lives on elsewhere.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://example.org/events'})

    node_id: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['node_announced',
                       'blob_stored',
                       'blob_evicted',
                       'blob_pin_set',
                       'blob_access_recorded',
                       'blob_corrupt',
                       'blob_replication_failed',
                       'space_pressure_detected',
                       'scrub_completed',
                       'peer_link_changed']} })
    epoch: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['node_announced',
                       'blob_stored',
                       'blob_evicted',
                       'blob_pin_set',
                       'blob_access_recorded',
                       'blob_corrupt',
                       'scrub_completed']} })
    blob_hash: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['blob_registered',
                       'blob_stored',
                       'blob_evicted',
                       'blob_pin_set',
                       'blob_corrupt',
                       'blob_replication_failed']} })
    reason: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['blob_evicted',
                       'blob_pin_set',
                       'blob_replication_failed',
                       'peer_link_changed']} })
    confirmed_sites: int = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['blob_evicted']} })
    occurred_at: datetime  = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['cluster_created',
                       'node_announced',
                       'collection_policy_set',
                       'blob_registered',
                       'blob_stored',
                       'blob_evicted',
                       'blob_pin_set',
                       'blob_access_recorded',
                       'blob_corrupt',
                       'blob_replication_failed',
                       'space_pressure_detected',
                       'scrub_completed',
                       'peer_link_changed']} })


class BlobPinSet(ConfiguredBaseModel):
    """
    [device] A node pinned or unpinned a blob (node_id, epoch, blob_hash, pinned, reason, occurred_at).
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://example.org/events'})

    node_id: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['node_announced',
                       'blob_stored',
                       'blob_evicted',
                       'blob_pin_set',
                       'blob_access_recorded',
                       'blob_corrupt',
                       'blob_replication_failed',
                       'space_pressure_detected',
                       'scrub_completed',
                       'peer_link_changed']} })
    epoch: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['node_announced',
                       'blob_stored',
                       'blob_evicted',
                       'blob_pin_set',
                       'blob_access_recorded',
                       'blob_corrupt',
                       'scrub_completed']} })
    blob_hash: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['blob_registered',
                       'blob_stored',
                       'blob_evicted',
                       'blob_pin_set',
                       'blob_corrupt',
                       'blob_replication_failed']} })
    pinned: bool = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['blob_pin_set']} })
    reason: Optional[str] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['blob_evicted',
                       'blob_pin_set',
                       'blob_replication_failed',
                       'peer_link_changed']} })
    occurred_at: datetime  = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['cluster_created',
                       'node_announced',
                       'collection_policy_set',
                       'blob_registered',
                       'blob_stored',
                       'blob_evicted',
                       'blob_pin_set',
                       'blob_access_recorded',
                       'blob_corrupt',
                       'blob_replication_failed',
                       'space_pressure_detected',
                       'scrub_completed',
                       'peer_link_changed']} })


class BlobAccessRecorded(ConfiguredBaseModel):
    """
    [device] A batch of read times (node_id, epoch, accesses — list of blob_hash / last_access_at, occurred_at). The only access fact.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://example.org/events'})

    node_id: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['node_announced',
                       'blob_stored',
                       'blob_evicted',
                       'blob_pin_set',
                       'blob_access_recorded',
                       'blob_corrupt',
                       'blob_replication_failed',
                       'space_pressure_detected',
                       'scrub_completed',
                       'peer_link_changed']} })
    epoch: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['node_announced',
                       'blob_stored',
                       'blob_evicted',
                       'blob_pin_set',
                       'blob_access_recorded',
                       'blob_corrupt',
                       'scrub_completed']} })
    blob_hashes: list[str] = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['blob_access_recorded']} })
    last_access_ats: list[datetime ] = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['blob_access_recorded']} })
    occurred_at: datetime  = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['cluster_created',
                       'node_announced',
                       'collection_policy_set',
                       'blob_registered',
                       'blob_stored',
                       'blob_evicted',
                       'blob_pin_set',
                       'blob_access_recorded',
                       'blob_corrupt',
                       'blob_replication_failed',
                       'space_pressure_detected',
                       'scrub_completed',
                       'peer_link_changed']} })


class BlobCorrupt(ConfiguredBaseModel):
    """
    [device] A node's copy is bad (node_id, epoch, blob_hash, found_hash — absent when the file is missing or unreadable, occurred_at). The file is quarantined; repair is the sweep's job.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://example.org/events'})

    node_id: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['node_announced',
                       'blob_stored',
                       'blob_evicted',
                       'blob_pin_set',
                       'blob_access_recorded',
                       'blob_corrupt',
                       'blob_replication_failed',
                       'space_pressure_detected',
                       'scrub_completed',
                       'peer_link_changed']} })
    epoch: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['node_announced',
                       'blob_stored',
                       'blob_evicted',
                       'blob_pin_set',
                       'blob_access_recorded',
                       'blob_corrupt',
                       'scrub_completed']} })
    blob_hash: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['blob_registered',
                       'blob_stored',
                       'blob_evicted',
                       'blob_pin_set',
                       'blob_corrupt',
                       'blob_replication_failed']} })
    found_hash: Optional[str] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['blob_corrupt']} })
    occurred_at: datetime  = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['cluster_created',
                       'node_announced',
                       'collection_policy_set',
                       'blob_registered',
                       'blob_stored',
                       'blob_evicted',
                       'blob_pin_set',
                       'blob_access_recorded',
                       'blob_corrupt',
                       'blob_replication_failed',
                       'space_pressure_detected',
                       'scrub_completed',
                       'peer_link_changed']} })


class BlobReplicationFailed(ConfiguredBaseModel):
    """
    [device] A fetch did not yield a verified blob (node_id, blob_hash, from_node, reason — 'not_held' | 'hash_mismatch' | 'out_of_space', occurred_at). Unreachable peers are peer_link_changed, not this. A hash_mismatch is also a signal about the SOURCE node.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://example.org/events'})

    node_id: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['node_announced',
                       'blob_stored',
                       'blob_evicted',
                       'blob_pin_set',
                       'blob_access_recorded',
                       'blob_corrupt',
                       'blob_replication_failed',
                       'space_pressure_detected',
                       'scrub_completed',
                       'peer_link_changed']} })
    blob_hash: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['blob_registered',
                       'blob_stored',
                       'blob_evicted',
                       'blob_pin_set',
                       'blob_corrupt',
                       'blob_replication_failed']} })
    from_node: Optional[str] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['blob_replication_failed']} })
    reason: str = Field(default=..., description="""'not_held' | 'hash_mismatch' | 'out_of_space'""", json_schema_extra = { "linkml_meta": {'domain_of': ['blob_evicted',
                       'blob_pin_set',
                       'blob_replication_failed',
                       'peer_link_changed']} })
    occurred_at: datetime  = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['cluster_created',
                       'node_announced',
                       'collection_policy_set',
                       'blob_registered',
                       'blob_stored',
                       'blob_evicted',
                       'blob_pin_set',
                       'blob_access_recorded',
                       'blob_corrupt',
                       'blob_replication_failed',
                       'space_pressure_detected',
                       'scrub_completed',
                       'peer_link_changed']} })


class SpacePressureDetected(ConfiguredBaseModel):
    """
    [device] A node is over its high watermark or under its free-space floor (node_id, used_bytes — held blobs, limit_bytes, free_bytes — the filesystem's room left, bytes_to_free — to reach the low watermark and to restore the floor with a quarter of it to spare, whichever is more, occurred_at). Emitted only when under pressure.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://example.org/events'})

    node_id: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['node_announced',
                       'blob_stored',
                       'blob_evicted',
                       'blob_pin_set',
                       'blob_access_recorded',
                       'blob_corrupt',
                       'blob_replication_failed',
                       'space_pressure_detected',
                       'scrub_completed',
                       'peer_link_changed']} })
    used_bytes: int = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['space_pressure_detected']} })
    limit_bytes: int = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['space_pressure_detected']} })
    free_bytes: Optional[int] = Field(default=None, description="""the filesystem's room left when it was read""", json_schema_extra = { "linkml_meta": {'domain_of': ['space_pressure_detected']} })
    bytes_to_free: int = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['space_pressure_detected']} })
    occurred_at: datetime  = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['cluster_created',
                       'node_announced',
                       'collection_policy_set',
                       'blob_registered',
                       'blob_stored',
                       'blob_evicted',
                       'blob_pin_set',
                       'blob_access_recorded',
                       'blob_corrupt',
                       'blob_replication_failed',
                       'space_pressure_detected',
                       'scrub_completed',
                       'peer_link_changed']} })


class ScrubCompleted(ConfiguredBaseModel):
    """
    [device] A scrub run finished (node_id, epoch, collection, checked, corrupt, bytes_checked, cursor — where the next run resumes (empty after a finished pass), pass_complete — the end was reached, so every held blob was verified at some point since pass_started_at, pass_started_at — when this pass began, occurred_at). Each bad blob also gets its own blob_corrupt.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://example.org/events'})

    node_id: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['node_announced',
                       'blob_stored',
                       'blob_evicted',
                       'blob_pin_set',
                       'blob_access_recorded',
                       'blob_corrupt',
                       'blob_replication_failed',
                       'space_pressure_detected',
                       'scrub_completed',
                       'peer_link_changed']} })
    epoch: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['node_announced',
                       'blob_stored',
                       'blob_evicted',
                       'blob_pin_set',
                       'blob_access_recorded',
                       'blob_corrupt',
                       'scrub_completed']} })
    collection: Optional[str] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['collection_policy_set', 'blob_registered', 'scrub_completed']} })
    checked: int = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['scrub_completed']} })
    corrupt: int = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['scrub_completed']} })
    bytes_checked: int = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['scrub_completed']} })
    cursor: Optional[str] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['scrub_completed']} })
    pass_complete: bool = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['scrub_completed']} })
    pass_started_at: Optional[datetime ] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['scrub_completed']} })
    occurred_at: datetime  = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['cluster_created',
                       'node_announced',
                       'collection_policy_set',
                       'blob_registered',
                       'blob_stored',
                       'blob_evicted',
                       'blob_pin_set',
                       'blob_access_recorded',
                       'blob_corrupt',
                       'blob_replication_failed',
                       'space_pressure_detected',
                       'scrub_completed',
                       'peer_link_changed']} })


class PeerLinkChanged(ConfiguredBaseModel):
    """
    [device] A node's link to a peer flipped (node_id, peer_id, healthy, reason, occurred_at). Recorded on transitions only; an unknown link counts as healthy, so the first failure is a transition.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://example.org/events'})

    node_id: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['node_announced',
                       'blob_stored',
                       'blob_evicted',
                       'blob_pin_set',
                       'blob_access_recorded',
                       'blob_corrupt',
                       'blob_replication_failed',
                       'space_pressure_detected',
                       'scrub_completed',
                       'peer_link_changed']} })
    peer_id: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['peer_link_changed']} })
    healthy: bool = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['peer_link_changed']} })
    reason: Optional[str] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['blob_evicted',
                       'blob_pin_set',
                       'blob_replication_failed',
                       'peer_link_changed']} })
    occurred_at: datetime  = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['cluster_created',
                       'node_announced',
                       'collection_policy_set',
                       'blob_registered',
                       'blob_stored',
                       'blob_evicted',
                       'blob_pin_set',
                       'blob_access_recorded',
                       'blob_corrupt',
                       'blob_replication_failed',
                       'space_pressure_detected',
                       'scrub_completed',
                       'peer_link_changed']} })


# Model rebuild
# see https://pydantic-docs.helpmanual.io/usage/models/#rebuilding-a-model
ClusterCreated.model_rebuild()
NodeAnnounced.model_rebuild()
CollectionPolicySet.model_rebuild()
BlobRegistered.model_rebuild()
BlobStored.model_rebuild()
BlobEvicted.model_rebuild()
BlobPinSet.model_rebuild()
BlobAccessRecorded.model_rebuild()
BlobCorrupt.model_rebuild()
BlobReplicationFailed.model_rebuild()
SpacePressureDetected.model_rebuild()
ScrubCompleted.model_rebuild()
PeerLinkChanged.model_rebuild()
