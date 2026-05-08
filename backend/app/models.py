from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, String, Table, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


bookmark_categories = Table(
    "bookmark_categories",
    Base.metadata,
    Column(
        "bookmark_id",
        Integer,
        ForeignKey("bookmarks.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "category_id",
        Integer,
        ForeignKey("categories.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Index("idx_bookmark_categories_bookmark_id", "bookmark_id"),
    Index("idx_bookmark_categories_category_id", "category_id"),
)


bookmark_tags = Table(
    "bookmark_tags",
    Base.metadata,
    Column(
        "bookmark_id",
        Integer,
        ForeignKey("bookmarks.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "tag_id",
        Integer,
        ForeignKey("tags.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Index("idx_bookmark_tags_bookmark_id", "bookmark_id"),
    Index("idx_bookmark_tags_tag_id", "tag_id"),
)


class Bookmark(Base):
    __tablename__ = "bookmarks"
    __table_args__ = (
        Index("idx_bookmarks_created_at", "created_at"),
        Index("idx_bookmarks_status", "status"),
        Index("idx_bookmarks_media_type", "media_type"),
        Index("idx_bookmarks_visibility", "visibility"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    source_url_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    uploader: Mapped[str | None] = mapped_column(Text)
    duration: Mapped[int | None] = mapped_column(Integer)
    thumbnail_url: Mapped[str | None] = mapped_column(Text)
    local_thumbnail_path: Mapped[str | None] = mapped_column(Text)
    media_filename: Mapped[str | None] = mapped_column(Text)
    media_path: Mapped[str | None] = mapped_column(Text)
    media_type: Mapped[str | None] = mapped_column(Text)
    reclip_job_id: Mapped[str | None] = mapped_column(Text)
    reclip_filename: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="pending")
    visibility: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="public",
        server_default="public",
    )
    error_message: Mapped[str | None] = mapped_column(Text)
    mode: Mapped[str] = mapped_column(Text, nullable=False, default="download_media")
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.current_timestamp(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.current_timestamp(),
        onupdate=func.current_timestamp(),
    )

    categories: Mapped[list["Category"]] = relationship(
        secondary=bookmark_categories,
        back_populates="bookmarks",
    )
    tags: Mapped[list["Tag"]] = relationship(
        secondary=bookmark_tags,
        back_populates="bookmarks",
    )


class Category(Base):
    __tablename__ = "categories"
    __table_args__ = (Index("idx_categories_slug", "slug"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    slug: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.current_timestamp(),
    )

    bookmarks: Mapped[list[Bookmark]] = relationship(
        secondary=bookmark_categories,
        back_populates="categories",
    )


class Tag(Base):
    __tablename__ = "tags"
    __table_args__ = (Index("idx_tags_slug", "slug"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    slug: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.current_timestamp(),
    )

    bookmarks: Mapped[list[Bookmark]] = relationship(
        secondary=bookmark_tags,
        back_populates="tags",
    )
