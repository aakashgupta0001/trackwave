import math
from typing import Generic, TypeVar

from fastapi import Query
from pydantic import BaseModel

T = TypeVar("T")

MAX_PAGE_SIZE = 100
DEFAULT_PAGE_SIZE = 20


class Page(BaseModel, Generic[T]):
    """Standard paginated list envelope used across every list endpoint."""

    items: list[T]
    page: int
    page_size: int
    total: int
    total_pages: int


def build_page(items: list[T], *, page: int, page_size: int, total: int) -> Page[T]:
    total_pages = math.ceil(total / page_size) if total > 0 else 0
    return Page[T](items=items, page=page, page_size=page_size, total=total, total_pages=total_pages)


class PaginationParams(BaseModel):
    page: int
    page_size: int

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.page_size


def get_pagination(
    page: int = Query(default=1, ge=1, description="1-indexed page number"),
    page_size: int = Query(default=DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE, description="Items per page"),
) -> PaginationParams:
    return PaginationParams(page=page, page_size=page_size)
