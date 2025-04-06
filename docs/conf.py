# Configuration file for the Sphinx documentation builder.
#
# For the full list of built-in configuration values, see the documentation:
# https://www.sphinx-doc.org/en/master/usage/configuration.html

# -- Project information -----------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#project-information

project = 'QuickMacApp'
copyright = '2025, Glyph'
author = 'Glyph'

# -- General configuration ---------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#general-configuration

extensions = [
    "sphinx.ext.intersphinx",
    "pydoctor.sphinx_ext.build_apidocs",
    "sphinx.ext.autosectionlabel",
]

templates_path = ['_templates']
exclude_patterns = ['_build', 'Thumbs.db', '.DS_Store']

import pathlib, subprocess

_project_root = pathlib.Path(__file__).parent.parent
_source_root = _project_root / "src"

_git_reference = subprocess.run(
    ["git", "rev-parse", "--abbrev-ref", "HEAD"],
    text=True,
    encoding="utf8",
    capture_output=True,
    check=True,
).stdout

pydoctor_args = [
    # pydoctor should not fail the sphinx build, we have another tox environment for that.
    "--intersphinx=https://docs.twisted.org/en/twisted-22.1.0/api/objects.inv",
    "--intersphinx=https://docs.python.org/3/objects.inv",
    "--intersphinx=https://zopeinterface.readthedocs.io/en/latest/objects.inv",
    # TODO: not sure why I have to specify these all twice.
    f"--config={_project_root}/.pydoctor.cfg",
    f"--html-viewsource-base=https://github.com/glyph/QuickMacApp/tree/{_git_reference}/src",
    f"--project-base-dir={_source_root}",
    "--html-output={outdir}/api",
    "--privacy=HIDDEN:quickmacapp.test.*",
    "--privacy=HIDDEN:quickmacapp.test",
    "--privacy=HIDDEN:**.__post_init__",
    str(_source_root / "quickmacapp"),
]
pydoctor_url_path = "/en/{rtd_version}/api/"
intersphinx_mapping = {
    "py3": ("https://docs.python.org/3", None),
    "zopeinterface": ("https://zopeinterface.readthedocs.io/en/latest", None),
    "twisted": ("https://docs.twisted.org/en/twisted-22.1.0/api", None),
}

# -- Options for HTML output -------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#options-for-html-output

html_theme = 'furo'
html_static_path = ['_static']
