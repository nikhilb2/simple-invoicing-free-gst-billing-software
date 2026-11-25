from src.core.utm import MAX_UTM_KEYS, clean_utm, utm_event_properties


def test_clean_utm_keeps_only_well_formed_utm_keys():
    assert clean_utm({"UTM_Source": " a ", "gclid": "x", "utm_": "y", "utm_medium": "  ", "utm_n": 3}) == {
        "utm_source": "a",
    }


def test_clean_utm_caps_values_and_key_count():
    cleaned = clean_utm({f"utm_k{i}": "v" for i in range(MAX_UTM_KEYS + 5)})
    assert len(cleaned) == MAX_UTM_KEYS
    assert clean_utm({"utm_source": "x" * 999}) == {"utm_source": "x" * 200}
    assert len(clean_utm({f"utm_k{i}": "v" for i in range(9)}, max_keys=5)) == 5


def test_clean_utm_tolerates_none():
    assert clean_utm(None) == {}


def test_event_properties_add_set_once_initial_keys():
    assert utm_event_properties({"utm_source": "a", "utm_id": "7"}) == {
        "utm_source": "a",
        "utm_id": "7",
        "$set_once": {"$initial_utm_source": "a", "$initial_utm_id": "7"},
    }


def test_event_properties_are_empty_without_tags():
    assert utm_event_properties({}) == {}
