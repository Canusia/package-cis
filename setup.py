"""Self-rooted packaging for the `cis` app.

The repository root IS the `cis` package: `models/`, `views/`, `migrations/`
and friends sit at top level next to this file. That layout is required, not
stylistic -- 187 distinct `cis.*` module paths are imported 1,374 times across
28 apps, including packages shipped to every tenant, so `cis` must import as
plain `cis` whether it is mounted as a submodule or pip-installed.

`find_packages()` here returns bare names (`models`, `views`, ...), which would
install them as top-level packages and collide with the world. They are
remapped onto the `cis.` prefix, and `package_dir` points that prefix at the
repo root.
"""
import os

from setuptools import setup, find_packages


def asset_patterns(*dirs):
    """package_data globs for non-package asset trees.

    `include_package_data=True` + MANIFEST.in does NOT work in a self-rooted
    layout. `package_dir={'cis': '.'}` registers the package root under the
    literal key '.', and setuptools' build_py.analyze_manifest walks a file's
    path upward looking for a matching src_dirs key -- but the walk stops once
    the remainder becomes the empty string, so it never matches '.'. Every file
    under a non-package directory at the package root is silently dropped from
    the wheel. Verified against setuptools 66.1.1.

    Explicit package_data takes a different code path and works, so the asset
    trees are enumerated here instead.
    """
    patterns = []
    for directory in dirs:
        for root, _dirs, files in os.walk(directory):
            if files:
                patterns.append(os.path.join(root, '*'))
    return sorted(patterns)


subpackages = find_packages(where='.', exclude=['tests', 'tests.*'])

setup(
    packages=['cis'] + [f'cis.{name}' for name in subpackages],
    package_dir={'cis': '.'},
    package_data={'cis': asset_patterns('templates', 'staticfiles', 'fixtures')},
    include_package_data=False,
)
