"""Retrieval: query understanding, facet profiles, and search planning."""

from retrieval.profile import (
    apply_retrieval_profile_to_tenant,
    build_retrieval_profile,
    merge_gazetteer_match_flags,
    retrieval_profile_summary,
)

__all__ = [
    "apply_retrieval_profile_to_tenant",
    "build_retrieval_profile",
    "merge_gazetteer_match_flags",
    "retrieval_profile_summary",
]
