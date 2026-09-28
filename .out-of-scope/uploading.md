# showtime never uploads or publishes

**Decision:** showtime writes files into the job folder and stops there. It does not post to YouTube, X,
LinkedIn, TikTok or any other platform, does not upload to storage, and does not send telemetry or
crash reports.

**Why**
- Publishing is a decision with consequences (brand, legal, timing) that belongs to the user.
- Upload integrations need accounts and tokens (see [cloud-apis.md](cloud-apis.md)) and break often.
- A tool that never sends data anywhere is easy to trust and easy to audit.

**Instead:** `showtime deliver exports` produces platform-ready files with the right size, bitrate,
loudness and duration, and each job writes `share.txt` (title, description, chapters, credits) ready to
paste. `showtime doctor --report` writes a redacted local bug report the user may choose to share.
