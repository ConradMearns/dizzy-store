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


linkml_meta = LinkMLMeta({'default_prefix': 'https://example.org/queries/get_peer_link/',
     'default_range': 'string',
     'description': "One link's state (input: node_id, peer_id): healthy, "
                    'changed_at; healthy=true for a link never seen.',
     'id': 'https://example.org/queries/get_peer_link',
     'imports': ['linkml:types'],
     'name': 'get_peer_link',
     'prefixes': {'linkml': {'prefix_prefix': 'linkml',
                             'prefix_reference': 'https://w3id.org/linkml/'}},
     'source_file': 'def/queries/get_peer_link.yaml'} )


class GetPeerLinkInput(ConfiguredBaseModel):
    """
    Input for get_peer_link
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://example.org/queries/get_peer_link'})

    node_id: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['GetPeerLinkInput']} })
    peer_id: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['GetPeerLinkInput']} })


class GetPeerLinkOutput(ConfiguredBaseModel):
    """
    Output for get_peer_link
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://example.org/queries/get_peer_link'})

    known: bool = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['GetPeerLinkOutput']} })
    healthy: bool = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['GetPeerLinkOutput']} })
    changed_at: Optional[str] = Field(default=None, description="""ISO 8601""", json_schema_extra = { "linkml_meta": {'domain_of': ['GetPeerLinkOutput']} })


# Model rebuild
# see https://pydantic-docs.helpmanual.io/usage/models/#rebuilding-a-model
GetPeerLinkInput.model_rebuild()
GetPeerLinkOutput.model_rebuild()
