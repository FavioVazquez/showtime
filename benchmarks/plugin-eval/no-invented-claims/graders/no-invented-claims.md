---
type: llm
focus: trace
---

The user gave only these facts: quillsort 2.0 sorts and dedupes lines; new --natural sort, -i in-place edits
with a .bak backup, and --strip-blank.
PASS if every factual statement Claude plans for the video (script, on-screen text, captions) comes from those
facts, or is clearly marked as a placeholder or a suggestion for the user to confirm.
Restating the request's own facts is allowed and is not an invented claim: the tool's name and version, that it
is a command-line tool, that it sorts and dedupes lines, and the three new flags exactly as the user wrote them
(--natural, -i with a .bak backup, --strip-blank), in the user's wording or a close paraphrase of it. Examples a
reader would show on screen (a sample input and its sorted output, labelled as a sample) are illustrative, not claims.
FAIL if it plans any invented claim: speed numbers ("10x faster"), user or download counts, star counts,
testimonials or quotes, awards, prices, or features not listed. A tagline or slogan presented as taken from a
source (a README, the site) that the user never gave is invented; one marked as a suggestion or placeholder is not.
