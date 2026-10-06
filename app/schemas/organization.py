import re
from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

OrganizationRole = Literal["owner", "admin", "member"]
AssignableOrganizationRole = Literal["admin", "member"]


class OrganizationCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    slug: str = Field(min_length=1, max_length=100)

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("name must not be blank")
        return value

    @field_validator("slug")
    @classmethod
    def normalize_slug(cls, value: str) -> str:
        value = value.strip().lower()
        if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", value):
            raise ValueError(
                "slug must contain lowercase letters, numbers, and single hyphens"
            )
        return value


class OrganizationResponse(BaseModel):
    id: UUID
    name: str
    slug: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class OrganizationMemberAdd(BaseModel):
    email: EmailStr
    role: AssignableOrganizationRole = "member"


class OrganizationMemberResponse(BaseModel):
    organization_id: UUID
    user_id: UUID
    email: EmailStr
    display_name: str
    role: OrganizationRole
