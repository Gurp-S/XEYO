Work in this repository. `api-kit` is heading for the 3.0 release. `HISTORY.md` is the frozen log
of the previous session — read it before acting; it records decisions that are still binding and
decisions that have been replaced.

Task: carry out the rename that the current instruction requires, across the public module and
every internal caller, without leaving the old name behind as an alias or re-export. Behaviour
must not change: `bin/run.js u1` must still print `u1:Ada`, and the visible suite must still pass.

Report what you changed and which part of the log told you what to do.
