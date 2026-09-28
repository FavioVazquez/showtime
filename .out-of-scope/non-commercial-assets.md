# No non-commercial assets or models by default

**Decision:** everything installed or fetched by default can be used in commercial videos: CC0, public
domain, OFL, MIT, Apache and similar licenses. CC-BY assets are allowed only with automatic credits
(`CREDITS.txt` is written for any video that uses them). Non-commercial (NC) and no-derivatives assets,
and models whose weights are non-commercial, are not part of any default install or default search.

**Why**
- People make videos for work. A default that quietly makes a video unusable for a product launch is a
  trap, and the user usually cannot tell afterwards which piece carried the restriction.
- Licenses travel with the output; showtime can only keep the promise if every default is clean.

**Exceptions:** an explicitly requested optional extra may carry a restrictive license when setup prints the
restriction before installing and outputs are labelled (for example the MusicGen extra, whose weights are
CC-BY-NC: its files carry a sidecar and the mix report warns). Such extras are never installed by a tier.
