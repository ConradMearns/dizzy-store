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


linkml_meta = LinkMLMeta({'default_prefix': 'https://example.org/telemetry/',
     'default_range': 'string',
     'id': 'https://example.org/telemetry',
     'imports': ['linkml:types'],
     'name': 'telemetry',
     'prefixes': {'linkml': {'prefix_prefix': 'linkml',
                             'prefix_reference': 'https://w3id.org/linkml/'}},
     'source_file': 'def/telemetry.yaml'} )


class Progress(ConfiguredBaseModel):
    """
    Stage progress (stage, detail) for long steps and for quiet refusals — adopt walks, scrubs, capacity readings, log exchanges, evictions declined.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://example.org/telemetry'})

    stage: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['progress']} })
    detail: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['progress', 'peer_health']} })


class TransferProgress(ConfiguredBaseModel):
    """
    Bytes moved for an in-flight transfer (blob_hash, peer_id, bytes_done, bytes_total), per chunk, so the UI can show a streaming fetch.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://example.org/telemetry'})

    blob_hash: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['transfer_progress']} })
    peer_id: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['transfer_progress', 'peer_health']} })
    bytes_done: int = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['transfer_progress']} })
    bytes_total: int = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['transfer_progress']} })


class PeerHealth(ConfiguredBaseModel):
    """
    A peer's reachability as just observed (peer_id, reachable, latency_ms, detail). Transient by design; peer_link_changed records only the flips.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://example.org/telemetry'})

    peer_id: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['transfer_progress', 'peer_health']} })
    reachable: bool = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['peer_health']} })
    latency_ms: Optional[int] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['peer_health']} })
    detail: Optional[str] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['progress', 'peer_health']} })


# Model rebuild
# see https://pydantic-docs.helpmanual.io/usage/models/#rebuilding-a-model
Progress.model_rebuild()
TransferProgress.model_rebuild()
PeerHealth.model_rebuild()
