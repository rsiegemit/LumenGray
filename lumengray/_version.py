"""Single source of truth for the app version.

The committed value is the fallback for source / dev runs. On release builds CI
overwrites this file from the pushed git tag (see .github/workflows/build.yml), so
the frozen desktop app knows exactly which version it is — which is what the in-app
"Check for updates" button compares against the latest GitHub release.
"""

__version__ = "0.1.18"
