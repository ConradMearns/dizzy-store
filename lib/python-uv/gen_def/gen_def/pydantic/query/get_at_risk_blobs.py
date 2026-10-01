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


linkml_meta = LinkMLMeta({'default_prefix': 'https://example.org/queries/get_at_risk_blobs/',
     'default_range': 'string',
     'description': 'Registered blobs held by fewer distinct sites than their '
                    "collection's min_sites (input: limit, optional collection): "
                    'blob_hash, byte_size, collection, first_seen_at, '
                    "sites_holding, sites_needed. A copy counts when 'present', on "
                    "a non-draining node, and fresh — stored, or its node's "
                    'last_full_pass_at, within verify_max_age_days. sites_holding '
                    '= 0 is LOSS. The first cut of the safety measure; surfaced in '
                    'the UI.',
     'id': 'https://example.org/queries/get_at_risk_blobs',
     'imports': ['linkml:types'],
     'name': 'get_at_risk_blobs',
     'prefixes': {'linkml': {'prefix_prefix': 'linkml',
                             'prefix_reference': 'https://w3id.org/linkml/'}},
     'source_file': 'def/queries/get_at_risk_blobs.yaml'} )


class GetAtRiskBlobsInput(ConfiguredBaseModel):
    """
    Input for get_at_risk_blobs
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://example.org/queries/get_at_risk_blobs'})

    limit: Optional[int] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['GetAtRiskBlobsInput']} })
    collection: Optional[str] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['GetAtRiskBlobsInput']} })


class GetAtRiskBlobsOutput(ConfiguredBaseModel):
    """
    Output for get_at_risk_blobs
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://example.org/queries/get_at_risk_blobs'})

    blob_hashes: Optional[list[str]] = Field(default=[], json_schema_extra = { "linkml_meta": {'domain_of': ['GetAtRiskBlobsOutput']} })
    byte_sizes: Optional[list[int]] = Field(default=[], json_schema_extra = { "linkml_meta": {'domain_of': ['GetAtRiskBlobsOutput']} })
    collections: Optional[list[str]] = Field(default=[], json_schema_extra = { "linkml_meta": {'domain_of': ['GetAtRiskBlobsOutput']} })
    first_seen_ats: Optional[list[str]] = Field(default=[], description="""ISO 8601""", json_schema_extra = { "linkml_meta": {'domain_of': ['GetAtRiskBlobsOutput']} })
    sites_holding: Optional[list[int]] = Field(default=[], json_schema_extra = { "linkml_meta": {'domain_of': ['GetAtRiskBlobsOutput']} })
    sites_needed: Optional[list[int]] = Field(default=[], json_schema_extra = { "linkml_meta": {'domain_of': ['GetAtRiskBlobsOutput']} })


# Model rebuild
# see https://pydantic-docs.helpmanual.io/usage/models/#rebuilding-a-model
GetAtRiskBlobsInput.model_rebuild()
GetAtRiskBlobsOutput.model_rebuild()
