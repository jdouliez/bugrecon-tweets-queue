# bugrecon-tweets-queue

Scheduled tweet/thread queue for @Bug_Recon.

## Layout
- `schedule.json` — 20 entries indexed by slot.
- `visuals/` — image assets referenced by entries.
- `post.py` — Playwright-based publisher invoked as `python post.py <slot>`.
