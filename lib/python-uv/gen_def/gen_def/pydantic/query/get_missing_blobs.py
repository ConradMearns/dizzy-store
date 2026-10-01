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


linkml_meta = LinkMLMeta({'default_prefix': 'https://example.org/queries/get_missing_blobs/',
     'default_range': 'string',
     'description': 'Registered blobs a node should hold but does not (input: '
                    "node_id, limit, order 'newest' | 'smallest'): in a collection "
                    "it wants ('*' = all), or pinned on it, with no 'present' "
                    'location on it — so corrupt and evicted copies, and a wiped '
                    "device's old claims, count as missing. Reader: the host's "
                    'paced sweep.',
     'id': 'https://example.org/queries/get_missing_blobs',
     'imports': ['linkml:types'],
     'name': 'get_missing_blobs',
     'prefixes': {'linkml': {'prefix_prefix': 'linkml',
                             'prefix_reference': 'https://w3id.org/linkml/'}},
     'source_file': 'def/queries/get_missing_blobs.yaml'} )


class GetMissingBlobsInput(ConfiguredBaseModel):
    """
    Input for get_missing_blobs
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://example.org/queries/get_missing_blobs'})

    node_id: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['GetMissingBlobsInput']} })
    limit: Optional[int] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['GetMissingBlobsInput']} })
    order: Optional[str] = Field(default=None, description="""'newest' (default) | 'smallest'""", json_schema_extra = { "linkml_meta": {'domain_of': ['GetMissingBlobsInput']} })


class GetMissingBlobsOutput(ConfiguredBaseModel):
    """
    Output for get_missing_blobs
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://example.org/queries/get_missing_blobs'})

    blob_hashes: Optional[list[str]] = Field(default=[], json_schema_extra = { "linkml_meta": {'domain_of': ['GetMissingBlobsOutput']} })
    byte_sizes: Optional[list[int]] = Field(default=[], json_schema_extra = { "linkml_meta": {'domain_of': ['GetMissingBlobsOutput']} })
    collections: Optional[list[str]] = Field(default=[], json_schema_extra = { "linkml_meta": {'domain_of': ['GetMissingBlobsOutput']} })


# Model rebuild
# see https://pydantic-docs.helpmanual.io/usage/models/#rebuilding-a-model
GetMissingBlobsInput.model_rebuild()
GetMissingBlobsOutput.model_rebuild()
