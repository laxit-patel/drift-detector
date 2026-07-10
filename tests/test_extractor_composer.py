import pytest
from agent.lib.extractors import composer, extractor_for

COMPOSER = '''{
  "require": {"php": "^8.1", "laravel/framework": "^10.0", "ext-json": "*", "stripe/stripe-php": "13.0.0"},
  "require-dev": {"phpunit/phpunit": "^10.0"}
}'''

def test_composer_extracts_require_and_php_runtime():
    recs = composer.extract("clients/b", "composer.json", COMPOSER)
    keys = {r.tech_key for r in recs}
    assert "lib:composer/laravel/framework" in keys
    assert "lib:composer/stripe/stripe-php" in keys
    assert "runtime:php" in keys
    assert not any("ext-json" in k for k in keys)                 # platform req skipped
    assert not any("phpunit" in k for k in keys)                  # require-dev skipped
    php = next(r for r in recs if r.tech_key == "runtime:php")
    assert php.kind == "runtime" and php.version_hint == "^8.1"

def test_composer_invalid_json_raises():
    with pytest.raises(ValueError):
        composer.extract("clients/b", "composer.json", "nope")

def test_composer_registered():
    assert extractor_for("x/composer.json") is composer.extract
