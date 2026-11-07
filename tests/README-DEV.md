# memfo developer notes

This repository releases through the shared gate, [`bless`](../bless), which
is emitted from `~/Projects/blessd/bless` by that repository's `build.py` and
is never edited here.  `./bless` reads this tree's identity from
[`pyproject.toml`](../pyproject.toml) at start-up: the distribution name, the
package holding `__version__`, the first console script and
`[tool.bless] branches`.

## Layout

| Path | What it is |
| --- | --- |
| `memfo/` | the package; `memfo/__init__.py:__version__` is the only copy of the release number |
| `memfo/main.py` | the `memfo` console script (`memfo.main:run`) |
| `memfo/memfod.py` | the `memfod` tmux launcher (`memfo.memfod:main`) |
| `tests/test_timememory.py` | behaviour of the history buffer and slicer |
| `tests/test_bless.py` | the identity the vendored gate derives from this tree, and the inspector it runs |
| `tests/inspect_dist.py` | the shared inspector: asserts a built wheel and sdist against this tree |
| `runner` | runs the source under `.venv/bin/python` without installing anything or touching `~/.local/bin` |
| `bless` | the release gate, emitted from `~/Projects/blessd/bless`; never edited here |
| `~/Projects/blessd/docs/release-strategy.md` | the release strategy every project shares |

## Development environment

The checkout's virtualenv is the editable/debug environment, and it is the
interpreter VS Code selects.  It holds `-e '.[dev]'`, not a built copy, so
breakpoints land in the tree.

    bt penv            # rebuilds .venv around the tree and the gate toolchain
    bt edit            # when ~/.local/bin/memfo should follow the tree

`runner` remains the non-invasive way to run or debug the source: it does not
touch `~/.local/bin`.

* VS Code interpreter: `.venv/bin/python`
* Run the source: `./runner`
* Run the suite: `.venv/bin/python -m pytest -q`

The same three gates CI runs are what `./bless` runs:

    .venv/bin/python -m ruff check .
    .venv/bin/python -m compileall -q memfo tests
    .venv/bin/python -m pytest -q --cov=memfo --cov-report=term-missing

## Releasing

`./bless` is the only path to an upload.  It takes no argument and no flag:
every run runs the whole gate, prints what it is holding, and only then asks

    ====> Enter test or publish or quit:

* `test` builds a throwaway `X.Y.Z.99.N` from a copy of the tree and uploads
  it to TestPyPI; no tag, no branch, no push.
* `publish` tags `vX.Y.Z`, uploads the two inspected files to PyPI and pushes
  `main` and the tag.
* anything else stops with nothing tagged, uploaded or pushed.

Credentials are looked up per index: `TWINE_TESTPYPI_PASSWORD` for TestPyPI
and `TWINE_PASSWORD` for PyPI, each overruling a matching `~/.pypirc` section.

The branch model is `[tool.bless] branches = ["main"]`: this project releases
from the trunk alone.  With one branch the gate cannot warn that a development
branch was left behind, so keeping any `dev` branch merged remains the
maintainer's job.

## Adoption note

This project adopted the shared gate at version **2.0.9**.

The vendored gate is byte for byte the build:

    sha256  3ef60e9e806ca58a3d900dd6622bb8be0052210da1ef26f9918bf0a1deb1e3b2
    origin  ~/Projects/blessd/bless
    command python3 ~/Projects/blessd/build.py --into . --force

Verify it with:

    cmp ~/Projects/blessd/bless bless && echo "the gate is this build"
    sha256sum bless                     # equals `build.py --sha`

What the project had to add to satisfy the gate:

* `memfo/__init__.py:__version__` as the single version location, with
  `[project] dynamic = ["version"]` instead of a second copy in
  `pyproject.toml`;
* a `dev` extra holding the toolchain the gate runs (`ruff`, `pytest`,
  `pytest-cov`, `build`, `twine>=7`, `packaging>=26`);
* `memfo --version`, because the smoke stage runs the first console script in
  a throwaway venv and requires the release number back;
* `tests/inspect_dist.py`, because the gate never uploads a distribution it
  has not inspected;
* `[tool.bless] branches = ["main"]`, matching this project's trunk-only
  release model;
* a deterministic `[tool.ruff]` policy and a `[tool.coverage.report]` floor,
  so the gate CI runs and the gate `./bless` runs agree.
