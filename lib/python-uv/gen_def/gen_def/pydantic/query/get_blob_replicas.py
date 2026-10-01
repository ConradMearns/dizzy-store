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


linkml_meta = LinkMLMeta({'default_prefix': 'https://example.org/queries/get_blob_replicas/',
     'default_range': 'string',
     'description': 'Who holds a blob (input: blob_hash): every location — '
                    'node_id, state, epoch, pinned, stored_at, last_access_at, '
                    'verified_at (stored, or the last full scrub pass if later) — '
                    "with its node's role, site and draining flag. Only locations "
                    "under the node's CURRENT epoch are returned — a superseded "
                    'life\'s claims stop counting. The single answer to "who has '
                    'X?" and the idempotency check for put, adopt, replicate and '
                    'pin.',
     'id': 'https://example.org/queries/get_blob_replicas',
     'imports': ['linkml:types'],
     'name': 'get_blob_replicas',
     'prefixes': {'linkml': {'prefix_prefix': 'linkml',
                             'prefix_reference': 'https://w3id.org/linkml/'}},
     'source_file': 'def/queries/get_blob_replicas.yaml'} )


class GetBlobReplicasInput(ConfiguredBaseModel):
    """
    Input for get_blob_replicas
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://example.org/queries/get_blob_replicas'})

    blob_hash: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['GetBlobReplicasInput']} })


class GetBlobReplicasOutput(ConfiguredBaseModel):
    """
    Output for get_blob_replicas
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://example.org/queries/get_blob_replicas'})

    node_ids: Optional[list[str]] = Field(default=[], json_schema_extra = { "linkml_meta": {'domain_of': ['GetBlobReplicasOutput']} })
    epochs: Optional[list[str]] = Field(default=[], json_schema_extra = { "linkml_meta": {'domain_of': ['GetBlobReplicasOutput']} })
    states: Optional[list[str]] = Field(default=[], json_schema_extra = { "linkml_meta": {'domain_of': ['GetBlobReplicasOutput']} })
    pinneds: Optional[list[bool]] = Field(default=[], json_schema_extra = { "linkml_meta": {'domain_of': ['GetBlobReplicasOutput']} })
    stored_ats: Optional[list[str]] = Field(default=[], description="""ISO 8601""", json_schema_extra = { "linkml_meta": {'domain_of': ['GetBlobReplicasOutput']} })
    last_access_ats: Optional[list[str]] = Field(default=[], description="""ISO 8601, empty when never read""", json_schema_extra = { "linkml_meta": {'domain_of': ['GetBlobReplicasOutput']} })
    roles: Optional[list[str]] = Field(default=[], json_schema_extra = { "linkml_meta": {'domain_of': ['GetBlobReplicasOutput']} })
    sites: Optional[list[str]] = Field(default=[], json_schema_extra = { "linkml_meta": {'domain_of': ['GetBlobReplicasOutput']} })
    drainings: Optional[list[bool]] = Field(default=[], json_schema_extra = { "linkml_meta": {'domain_of': ['GetBlobReplicasOutput']} })
    verified_ats: Optional[list[str]] = Field(default=[], description="""ISO 8601 — stored, or the last full scrub pass if later""", json_schema_extra = { "linkml_meta": {'domain_of': ['GetBlobReplicasOutput']} })


# Model rebuild
# see https://pydantic-docs.helpmanual.io/usage/models/#rebuilding-a-model
GetBlobReplicasInput.model_rebuild()
GetBlobReplicasOutput.model_rebuild()
