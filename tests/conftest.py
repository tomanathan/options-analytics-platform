import os

from hypothesis import settings

# Named profiles keep property tests reproducible in CI (fixed seed) and fast locally.
settings.register_profile("ci", derandomize=True, max_examples=200, deadline=None)
settings.register_profile("dev", max_examples=25)
settings.load_profile(os.environ.get("HYPOTHESIS_PROFILE", "dev"))
