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


linkml_meta = LinkMLMeta({'default_prefix': 'https://example.org/queries/get_blobs_held/',
     'default_range': 'string',
     'description': "A node's 'present' locations in hash order, continuing from "
                    'its saved scrub cursor (input: node_id, optional collection, '
                    'limit) — the stable iteration scrub resumes over — with the '
                    'pass_started_at of the pass in progress.',
     'id': 'https://example.org/queries/get_blobs_held',
     'imports': ['linkml:types'],
     'name': 'get_blobs_held',
     'prefixes': {'linkml': {'prefix_prefix': 'linkml',
                             'prefix_reference': 'https://w3id.org/linkml/'}},
     'source_file': 'def/queries/get_blobs_held.yaml'} )


class GetBlobsHeldInput(ConfiguredBaseModel):
    """
    Input for get_blobs_held
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://example.org/queries/get_blobs_held'})

    node_id: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['GetBlobsHeldInput']} })
    collection: Optional[str] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['GetBlobsHeldInput']} })
    limit: Optional[int] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['GetBlobsHeldInput']} })


class GetBlobsHeldOutput(ConfiguredBaseModel):
    """
    Output for get_blobs_held
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://example.org/queries/get_blobs_held'})

    blob_hashes: Optional[list[str]] = Field(default=[], json_schema_extra = { "linkml_meta": {'domain_of': ['GetBlobsHeldOutput']} })
    byte_sizes: Optional[list[int]] = Field(default=[], json_schema_extra = { "linkml_meta": {'domain_of': ['GetBlobsHeldOutput']} })
    collections: Optional[list[str]] = Field(default=[], json_schema_extra = { "linkml_meta": {'domain_of': ['GetBlobsHeldOutput']} })
    pass_started_at: Optional[str] = Field(default=None, description="""ISO 8601; empty when no pass is in progress""", json_schema_extra = { "linkml_meta": {'domain_of': ['GetBlobsHeldOutput']} })


# Model rebuild
# see https://pydantic-docs.helpmanual.io/usage/models/#rebuilding-a-model
GetBlobsHeldInput.model_rebuild()
GetBlobsHeldOutput.model_rebuild()
