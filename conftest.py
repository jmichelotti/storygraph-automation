# Repo-root conftest: pytest puts this directory on sys.path, so tests import goodreads.* and
# storygraph.* the way the container does. Only modules without a top-level Playwright import are
# testable on a host without Playwright.
