"""Prevention layer: turns the classifier's after-the-fact output into guidance at the
moment work happens.

Three tiers, none of which need an LLM call at request time:

* ``risk``       - tier 1, point-of-entry guidance from already-aggregated history.
* ``similarity`` - tier 2, live investigation assist by nearest-neighbour lookup.
* ``attention``  - tier 3, repeat-issue flags per terminal / handler for supervisors.
"""
