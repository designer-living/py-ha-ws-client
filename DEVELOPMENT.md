# Development

Some extra details for developers

## Running the tests

```bash
pip install -e ".[test]"
pytest
```

The suite runs against a fake Home Assistant websocket server
(`tests/fake_ha_server.py`); no real Home Assistant instance is needed.
GitHub Actions runs it on every push and PR (`.github/workflows/ci.yml`).

## Publish to pypi from github action (Preferred)

* Ensure you have updated the version number in `pyproject.toml` and that you have updated the change log in `CHANGELOG.md`
* In github go to "Releases" and "Draft a new Release" 
* Set Release Title as the version number e.g "v0.7"
* In choose a tag type the version number e.g. "v0.7" and select "Create new tag"
* In Description enter details from the change log.
* Tick "Set as latest release"
* Click publish "Release"
* Watch GitHub Action to ensure it builds and publishes

## Publish to pypi manually

### Requirements

```bash
pip install build twine
```

### Upload

Ensure you have updated the version number in `pyproject.toml`
and that you have updated the change log in `CHANGELOG.md`

Then run the following.

```bash
python -m build
twine upload dist/*
```

Finally create a release in github and upload the tar.gz file

```bash
git tag v[version]
e.g.
git tag v0.6
```
