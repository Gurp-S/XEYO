import assert from "node:assert/strict";
import test from "node:test";

import {
  acceptedNote,
  busySlashNote,
  resolveBusySubmit,
} from "./busySubmit.js";

test("忙时提交判定：Enter=排队（queued）、加速键=边界引导（steered）", () => {
  assert.deepEqual(resolveBusySubmit(false), {
    queueIfBusy: true,
    steerIfBusy: false,
  });
  assert.deepEqual(resolveBusySubmit(true), {
    queueIfBusy: true,
    steerIfBusy: true,
  });
});

test("202 受理体回执：queued 带位次、steered 讲清边界口径", () => {
  assert.match(acceptedNote({queued: true, position: 3}), /位次 3/);
  assert.match(acceptedNote({queued: true}), /已排队/);
  assert.match(acceptedNote({steered: true}), /引导/);
  assert.match(acceptedNote({steered: true}), /不打断/);
});

test("忙时斜杠拒绝文案给出口（/stop 或 Esc）", () => {
  const s = busySlashNote("goal");
  assert.match(s, /暂不可执行/);
  assert.match(s, /\/stop/);
});
