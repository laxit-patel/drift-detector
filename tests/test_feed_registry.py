import pytest
from agent.lib import feeds

def test_register_and_get():
    @feeds.register("dummy-test")
    def fetch(spec, **kw):
        return []
    assert feeds.get_adapter("dummy-test") is fetch
    assert "dummy-test" in feeds.adapter_names()

def test_get_unknown_raises():
    with pytest.raises(KeyError, match="no feed adapter"):
        feeds.get_adapter("does-not-exist")
