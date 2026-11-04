# Prior session log — api-kit 3.0

## 2026-10-26 09:30 — User
Freeze note: do not change the public surface of src/api.js. Downstream packages
pin the current names and we are not breaking them this quarter.

## 2026-10-26 10:05 — Assistant
Recorded the freeze. No renames planned.

## 2026-10-27 15:20 — User
We shipped the last 2.x. Marketing moved the date; 3.0 is next month and it is an
explicitly breaking release.

## 2026-10-28 08:40 — User
Decision, and it supersedes the freeze note from 10-26: in 3.0 `getUser` becomes
`fetchUser`. Rename it in src/api.js and update every internal caller. The old
name must not survive — no alias, no re-export.

## 2026-10-28 08:41 — Assistant
Noted: the freeze applies to 2.x only. 3.0 renames getUser to fetchUser.

## 2026-10-28 09:00 — CI
2.9.0 release: PASSED
3.0 branch: not started

## 2026-10-28 09:15 — User
If someone picks this up later: the freeze note above is historical. The current
instruction is the 3.0 rename.
