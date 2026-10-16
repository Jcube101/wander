# Known issues

- **Early DJI clips (before ~2 Oct midday) have uncertain camera offset** — left unplaced; fix via edit mode (Shift time / place).
- **Last Bangalore clips on 10 Oct** have no phone anchors → unplaced.
- **WhatsApp images** carry date only; time comes from file save time when it matches the date, else noon. Never auto-located (may be friends' photos). Ones dated outside the trip are dropped.
- **No duplicate detection** — the same photo from two sources appears twice.
- **Lovable preview can't load protected trips** (no Access cookie on the media host from the preview origin); test trips on wander.job-joseph.com.
- **`travelogue-map-memory.lovable.app`** (Lovable's own published URL) isn't in the Worker's CORS list → it can't load data. Intended: wander.job-joseph.com is canonical.
- **tripmap has no automated tests** (see [ROADMAP.md](../ROADMAP.md)).
