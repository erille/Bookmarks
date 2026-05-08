from datetime import datetime
from typing import Literal
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, field_validator


BookmarkMode = Literal["bookmark_only", "download_media"]
BookmarkVisibility = Literal["public", "private"]


def clean_label_names(values: list[str]) -> list[str]:
    cleaned: list[str] = []
    seen: set[str] = set()
    for value in values:
        name = " ".join(value.strip().split())
        key = name.lower()
        if name and key not in seen:
            cleaned.append(name)
            seen.add(key)
    return cleaned


def clean_category_names(values: list[str]) -> list[str]:
    return clean_label_names(values)


class CategoryCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)

    @field_validator("name")
    @classmethod
    def clean_name(cls, value: str) -> str:
        value = " ".join(value.strip().split())
        if not value:
            raise ValueError("Category name is required")
        return value


class CategoryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    slug: str
    bookmark_count: int = 0


class CategoryListResponse(BaseModel):
    items: list[CategoryResponse]


class TagCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)

    @field_validator("name")
    @classmethod
    def clean_name(cls, value: str) -> str:
        value = " ".join(value.strip().split())
        if not value:
            raise ValueError("Tag name is required")
        return value


class TagResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    slug: str
    bookmark_count: int = 0


class TagListResponse(BaseModel):
    items: list[TagResponse]


class BookmarkCreate(BaseModel):
    source_url: str = Field(min_length=1, max_length=4096)
    title: str | None = Field(default=None, max_length=500)
    categories: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    create_missing_categories: bool = True
    mode: BookmarkMode = "download_media"
    visibility: BookmarkVisibility = "public"

    @field_validator("source_url")
    @classmethod
    def validate_source_url(cls, value: str) -> str:
        value = value.strip()
        parsed = urlparse(value)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("Only http and https URLs are supported")
        return value

    @field_validator("title")
    @classmethod
    def clean_title(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = " ".join(value.strip().split())
        return value or None

    @field_validator("categories")
    @classmethod
    def clean_categories(cls, values: list[str]) -> list[str]:
        return clean_label_names(values)

    @field_validator("tags")
    @classmethod
    def clean_tags(cls, values: list[str]) -> list[str]:
        return clean_label_names(values)


class BookmarkResponse(BaseModel):
    id: int
    title: str
    source_url: str
    uploader: str | None = None
    duration: int | None = None
    thumbnail_url: str | None = None
    media_url: str | None = None
    media_type: str | None = None
    source_platform: str | None = None
    status: str
    visibility: BookmarkVisibility
    mode: str
    categories: list[str]
    tags: list[str]
    created_at: datetime
    updated_at: datetime


class BookmarkUpdate(BaseModel):
    title: str | None = Field(default=None, max_length=500)
    notes: str | None = Field(default=None, max_length=2000)
    categories: list[str] | None = None
    tags: list[str] | None = None
    create_missing_categories: bool = True
    visibility: BookmarkVisibility | None = None

    @field_validator("title")
    @classmethod
    def clean_title(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = " ".join(value.strip().split())
        return value or None

    @field_validator("notes")
    @classmethod
    def clean_notes(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        return value or None

    @field_validator("categories")
    @classmethod
    def clean_categories(cls, values: list[str] | None) -> list[str] | None:
        if values is None:
            return None
        return clean_label_names(values)

    @field_validator("tags")
    @classmethod
    def clean_tags(cls, values: list[str] | None) -> list[str] | None:
        if values is None:
            return None
        return clean_label_names(values)


class BookmarkCreateResponse(BaseModel):
    created: bool
    duplicate: bool
    bookmark: BookmarkResponse


class BookmarkListResponse(BaseModel):
    items: list[BookmarkResponse]
    limit: int
    offset: int
    total: int
