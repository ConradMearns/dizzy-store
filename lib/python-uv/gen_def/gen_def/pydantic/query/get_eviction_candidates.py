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


linkml_meta = LinkMLMeta({'default_prefix': 'https://example.org/queries/get_eviction_candidates/',
     'default_range': 'string',
     'description': 'Blobs a node may drop (input: node_id, bytes_needed, limit, '
                    "min_bytes): its 'present', unpinned locations in evictable "
                    'collections that OTHER non- draining nodes hold fresh and '
                    "'present' across at least min_sites distinct sites, including "
                    "a non-draining archive. A 'hot' node gets them least recently "
                    'TOUCHED first (last read, else when stored), skipping '
                    'collections it WANTS in full and blobs smaller than min_bytes '
                    '(absent or 0 = no exemption; an exempt blob counts toward '
                    'neither bytes_needed nor limit), stopping once bytes_needed '
                    'is covered; a draining node gets all of them, small ones too; '
                    "a 'cold' node gets none. Advisory — evict_blob re-checks "
                    "live. Readers: evict_on_space_pressure and the host's drain "
                    'sweep.',
     'id': 'https://example.org/queries/get_eviction_candidates',
     'imports': ['linkml:types'],
     'name': 'get_eviction_candidates',
     'prefixes': {'linkml': {'prefix_prefix': 'linkml',
                             'prefix_reference': 'https://w3id.org/linkml/'}},
     'source_file': 'def/queries/get_eviction_candidates.yaml'} )


class GetEvictionCandidatesInput(ConfiguredBaseModel):
    """
    Input for get_eviction_candidates
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://example.org/queries/get_eviction_candidates'})

    node_id: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['GetEvictionCandidatesInput']} })
    bytes_needed: Optional[int] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['GetEvictionCandidatesInput']} })
    limit: Optional[int] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['GetEvictionCandidatesInput']} })
    min_bytes: Optional[int] = Field(default=None, description="""blobs smaller than this are never candidates (a draining node ignores it); absent or 0 = none""", json_schema_extra = { "linkml_meta": {'domain_of': ['GetEvictionCandidatesInput']} })


class GetEvictionCandidatesOutput(ConfiguredBaseModel):
    """
    Output for get_eviction_candidates
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://example.org/queries/get_eviction_candidates'})

    blob_hashes: Optional[list[str]] = Field(default=[], json_schema_extra = { "linkml_meta": {'domain_of': ['GetEvictionCandidatesOutput']} })
    byte_sizes: Optional[list[int]] = Field(default=[], json_schema_extra = { "linkml_meta": {'domain_of': ['GetEvictionCandidatesOutput']} })
    collections: Optional[list[str]] = Field(default=[], json_schema_extra = { "linkml_meta": {'domain_of': ['GetEvictionCandidatesOutput']} })


# Model rebuild
# see https://pydantic-docs.helpmanual.io/usage/models/#rebuilding-a-model
GetEvictionCandidatesInput.model_rebuild()
GetEvictionCandidatesOutput.model_rebuild()
