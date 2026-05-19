import os
from types import SimpleNamespace
from unittest.mock import patch

from retrieval.max_results import effective_chat_max_results


def _tenant(**kwargs):
    base = dict(
        source_db_type="wordpress",
        source_mode="wordpress",
        source_db_url=None,
        source_static_urls_json=None,
        chat_max_results=None,
        chat_max_results_catalog=None,
    )
    base.update(kwargs)
    return SimpleNamespace(**base)


@patch.dict(
    os.environ,
    {
        "CHAT_MAX_RESULTS_ABSOLUTE_CEILING": "50",
        "CHAT_MAX_RESULTS_DEFAULT_GENERAL": "5",
        "CHAT_MAX_RESULTS_DEFAULT_CATALOG": "8",
    },
    clear=False,
)
def test_no_tenant_uses_general_default_and_clamps_request():
    assert effective_chat_max_results(tenant=None, request_max=None) == 5
    assert effective_chat_max_results(tenant=None, request_max=3) == 3
    assert effective_chat_max_results(tenant=None, request_max=100) == 5


@patch.dict(
    os.environ,
    {
        "CHAT_MAX_RESULTS_ABSOLUTE_CEILING": "50",
        "CHAT_MAX_RESULTS_DEFAULT_GENERAL": "5",
        "CHAT_MAX_RESULTS_DEFAULT_CATALOG": "8",
    },
    clear=False,
)
def test_wordpress_tenant_respects_row_cap_and_request():
    t = _tenant(source_db_type="wordpress", chat_max_results=12)
    assert effective_chat_max_results(tenant=t, request_max=None) == 12
    assert effective_chat_max_results(tenant=t, request_max=3) == 3
    assert effective_chat_max_results(tenant=t, request_max=50) == 12


@patch.dict(
    os.environ,
    {
        "CHAT_MAX_RESULTS_ABSOLUTE_CEILING": "50",
        "CHAT_MAX_RESULTS_DEFAULT_GENERAL": "5",
        "CHAT_MAX_RESULTS_DEFAULT_CATALOG": "8",
    },
    clear=False,
)
def test_woocommerce_prefers_catalog_column_when_set():
    t = _tenant(source_db_type="woocommerce", chat_max_results=5, chat_max_results_catalog=20)
    assert effective_chat_max_results(tenant=t, request_max=None) == 20
    assert effective_chat_max_results(tenant=t, request_max=15) == 15
    assert effective_chat_max_results(tenant=t, request_max=100) == 20


@patch.dict(
    os.environ,
    {
        "CHAT_MAX_RESULTS_ABSOLUTE_CEILING": "10",
        "CHAT_MAX_RESULTS_DEFAULT_GENERAL": "5",
        "CHAT_MAX_RESULTS_DEFAULT_CATALOG": "8",
    },
    clear=False,
)
def test_absolute_ceiling_clamps_tenant_and_env_defaults():
    t = _tenant(source_db_type="wordpress", chat_max_results=25)
    assert effective_chat_max_results(tenant=t, request_max=None) == 10
    woo = _tenant(source_db_type="woocommerce", chat_max_results_catalog=25)
    assert effective_chat_max_results(tenant=woo, request_max=None) == 10
