"""knowledge_core — the shared Knowledge Core (see package README)."""
from .core import (  # noqa: F401
    KnowledgeQueryRequest,
    KnowledgeQueryResult,
    ResolvedScope,
    SourceSummary,
    MISS_SENTENCE,
    authorized_search,
    file_store_items,
    grouped_items,
    item_root,
    output_root,
    resolve_scope,
    scope_allows_item,
    scope_from_grants,
    scoped_items_for_scope,
    validate_request,
)
from .evidence import (  # noqa: F401
    FRESHNESS_WINDOW_DAYS,
    SCHEMA_VERSION,
    evidence_from_blocks,
    freshness_from_date,
    freshness_of,
)
