/**
 * editflick.spec.ts — debug：复现「退出历史气泡编辑态闪一下」并逐帧采样。
 *
 * 覆盖矩阵：
 *   吸顶关(就地编辑) × 短/长消息
 *   吸顶开(portal 编辑) × 短/长消息   ← 上轮未覆盖，主嫌疑
 * 长消息 = 查看态被 --xy-prompt-view-cap clamp 的历史气泡（真实高频场景）。
 * 采样窗口内每 ~12ms 记录：scroller.scrollTop、编辑气泡/流内 chip rect、
 * 下方回复锚点 top —— 退出瞬间任何 >1px 瞬移 / 无过渡显隐 = 「闪」帧。
 *
 * 运行（gui/ 下）：
 *   npx playwright test -c e2e-debug-editflick/playwright.debug.config.ts
 */
import {test, expect} from '@playwright/test';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {bootChat, openWorkspaceSession} from '../e2e/helpers/boot';
import {seedFakeTestSettings} from '../e2e/helpers/seed';

const COMPOSER = '描述任务… Enter 发送';
const workspaceDir = fs.mkdtempSync(path.join(os.tmpdir(), 'xeyo-editflick-ws-'));

const LONG_BODY =
  'flick-B 这是一段很长的历史消息，用于把查看态气泡撑到统一查看上限（clamp），' +
  '模拟真实长文本编辑退出。重复内容凑足高度：' +
  '「认知负荷」「界面瞬移」「逐帧采样」「动画补间」「flex 布局」「grid 过渡」'.repeat(4) +
  '。尾部收束。';

const SAMPLER = `
(() => {
  const rec = [];
  let on = false;
  let t0 = 0;
  let timer = 0;
  const chipSel = '[data-prompt-text^="flick-B"]';
  const text = (el) => el && (el.textContent || '').trim();
  const anchorOf = (t) =>
    Array.from(document.querySelectorAll('.xy-chat-surface .xy-chat-text'))
      .find(el => text(el).startsWith(t) && el.getBoundingClientRect().width > 0) || null;
  const tick = () => {
    if (!on) return;
    const chip = document.querySelector(chipSel);
    const anchor = anchorOf('ok: flick-B');
    const sc = document.querySelector('.xy-hover-scroll');
    const sRect = sc ? sc.getBoundingClientRect() : null;
    const eb = document.querySelector('.xy-editing-bubble');
    const pin = eb ? eb.closest('[data-pin-id]') : null;
    const cs = chip ? getComputedStyle(chip) : null;
    const ebs = eb ? getComputedStyle(eb) : null;
    const controls = chip ? chip.querySelector('.xy-editing-controls') : null;
    const gtr = controls ? getComputedStyle(controls).gridTemplateRows : '';
    const cr = chip ? chip.getBoundingClientRect() : null;
    const er = eb ? eb.getBoundingClientRect() : null;
    const ar = anchor ? anchor.getBoundingClientRect() : null;
    const pr = pin ? pin.getBoundingClientRect() : null;
    // 上一用户 chip(flick-A)底边 —— 定位拆帧 29px 位移来自 chip 自身还是上方内容
    const aChip = document.querySelector('[data-prompt-text^="flick-A"]');
    const aCR = aChip ? aChip.getBoundingClientRect() : null;
    const chipCS = chip ? getComputedStyle(chip) : null;
    // DOM 身份检测：chip / 编辑气泡是否在同一帧被替换(重挂)
    if (window.__chipRef && window.__chipRef !== chip) { window.__chipReplacedAt = performance.now(); }
    window.__chipRef = chip;
    if (eb && window.__ebRef && window.__ebRef !== eb) { window.__ebReplacedAt = performance.now(); }
    window.__ebRef = eb;
    rec.push({
      dt: Math.round(performance.now() - t0),
      st: sc ? Math.round(sc.scrollTop * 100) / 100 : null,
      cDocT: cr && sRect ? Math.round((cr.top - sRect.top) * 100) / 100 : null,
      cTop: cr ? Math.round(cr.top * 100) / 100 : null,
      cH: cr ? Math.round(cr.height * 100) / 100 : null,
      cVis: cs ? cs.visibility : null,
      ebTop: er ? Math.round(er.top * 100) / 100 : null,
      ebH: er ? Math.round(er.height * 100) / 100 : null,
      ebOp: er ? Math.round(parseFloat(ebs.opacity) * 100) / 100 : null,
      ebMaxH: eb && ebs ? Math.round(parseFloat(ebs.maxHeight) * 100) / 100 : null,
      ebTransP: eb && ebs ? ebs.transitionProperty : '',
      ebTransD: eb && ebs ? ebs.transitionDuration : '',
      pTop: pr ? Math.round(pr.top * 100) / 100 : null,
      closing: eb ? eb.classList.contains('xy-editing-bubble-closing') : false,
      gtr,
      aTop: ar ? Math.round(ar.top * 100) / 100 : null,
      aBot: aCR ? Math.round(aCR.bottom * 100) / 100 : null,
      chipMT: chipCS ? parseFloat(chipCS.marginTop) : null,
      chipOfsT: chip ? chip.offsetTop : null,
    });
    if (rec.length > 200) { on = false; return; }
    timer = setTimeout(tick, 12);
  };
  window.__flickRec = rec;
  window.__flickStart = () => { rec.length = 0; t0 = performance.now(); on = true; tick(); };
  window.__flickStop = () => { on = false; clearTimeout(timer); };
})();
`;

async function send(page: import('@playwright/test').Page, text: string) {
  const composer = page.getByPlaceholder(COMPOSER);
  await composer.click();
  await composer.fill(text);
  await composer.press('Enter');
}

async function waitSettled(page: import('@playwright/test').Page, echo: string) {
  await expect(page.getByText(new RegExp(`ok: ${echo}`)).first()).toBeVisible({timeout: 20_000});
  // 流式结束（停止生成按钮消失）才算该轮 settle
  await expect(page.getByRole('button', {name: '停止生成'})).toHaveCount(0);
}

function stickySeed(stickyOn: boolean) {
  return async (page: import('@playwright/test').Page) => {
    await page.addInitScript((on) => {
      window.localStorage.setItem('XEYO_ENABLE_LOCAL_TEST', '1');
      window.localStorage.setItem(
        'xeyo-settings',
        JSON.stringify({
          provider: 'fake',
          model: 'fake',
          apiKey: '',
          baseUrl: '',
          thinking: 'disabled',
          reasoningEffort: '',
          permissionMode: 'risk',
          outputCompact: false,
          codeCompact: false,
          hydrated: false,
          stickyBubbles: on,
        }),
      );
    }, stickyOn);
  };
}

const offSeed = stickySeed(false);
const onSeed = stickySeed(true);

async function buildScene(
  page: import('@playwright/test').Page,
  body: string,
  targetId: string,
) {
  await send(page, 'flick-A');
  await waitSettled(page, 'flick-A');
  await send(page, body);
  await waitSettled(page, targetId);
  await send(page, 'flick-C');
  await waitSettled(page, 'flick-C');

  // 定位目标（历史）消息 chip 的编辑入口并进入编辑
  const editBtn = page
    .getByRole('button', {name: '编辑这条消息'})
    .filter({hasText: targetId})
    .first();
  await editBtn.scrollIntoViewIfNeeded();
  // 进编辑前基线：chip 相对 scroller 内容顶的坐标(区分滚动/布局)
  await page.evaluate(() => {
    const sc = document.querySelector('.xy-hover-scroll');
    const ch = document.querySelector('[data-prompt-text^="flick-B"]');
    const aC = document.querySelector('[data-prompt-text^="flick-A"]');
    const sR = sc ? sc.getBoundingClientRect() : null;
    const cR = ch ? ch.getBoundingClientRect() : null;
    const aR = aC ? aC.getBoundingClientRect() : null;
    window.__preEdit = {
      st: sc ? sc.scrollTop : null,
      chipDocT: cR && sR ? Math.round((cR.top - sR.top) * 100) / 100 : null,
      chipTop: cR ? Math.round(cR.top * 100) / 100 : null,
      aBot: aR ? Math.round(aR.bottom * 100) / 100 : null,
    };
  });
  await editBtn.click();

  // 预览态 → 切原生 textarea（焦点已就位，Esc 在此生效）
  const preview = page.getByLabel('点击开始编辑');
  await expect(preview).toBeVisible({timeout: 5_000});
  await preview.click();
  const textarea = page.getByLabel('编辑历史消息');
  await expect(textarea).toBeVisible();
  await expect(page.locator('.xy-editing-bubble')).toBeVisible();
  await page.waitForTimeout(700); // 控件展开动画完成、编辑态稳定
  return textarea;
}

async function runTrace(
  page: import('@playwright/test').Page,
  label: string,
) {
  await page.evaluate(SAMPLER);
  await page.evaluate(() => (window as any).__flickStart());
  await page.waitForTimeout(350);
  await page.keyboard.press('Escape');
  await page.waitForTimeout(1400);
  await page.evaluate(() => (window as any).__flickStop());
  const rec = await page.evaluate(() => (window as any).__flickRec as any[]);
  console.log(`=== TRACE ${label} ===`);
  console.log(JSON.stringify(rec));
  // 找拆 DOM 帧附近的最大单帧位移（判断是否还有“跳”）
  let maxJump = 0;
  for (let i = 1; i < rec.length; i++) {
    const a0 = rec[i - 1].aTop;
    const a1 = rec[i].aTop;
    if (a0 !== null && a1 !== null) {
      maxJump = Math.max(maxJump, Math.abs(a1 - a0));
    }
  }
  console.log(`=== MAX-JUMP ${label}: ${maxJump}px ===`);
  const replaced = await page.evaluate(() => ({
    chipAt: (window as any).__chipReplacedAt ?? null,
    ebAt: (window as any).__ebReplacedAt ?? null,
    pre: (window as any).__preEdit ?? null,
  }));
  console.log(`=== DOM-REPLACED ${label}: chip=${replaced.chipAt} eb=${replaced.ebAt} ===`);
  console.log(`=== PRE-EDIT ${label}: ${JSON.stringify(replaced.pre)} ===`);
  await expect(page.locator('.xy-editing-bubble')).toHaveCount(0);
  await expect(page.locator('[data-prompt-text^="flick-B"]').first()).toBeVisible();
  // 编辑态确已退出：chip 不再处于编辑（无 closing 残留），回到查看态（无 textarea）
  await expect(page.locator('[data-prompt-text^="flick-B"] textarea')).toHaveCount(0);
}

test('off-短消息: 不改文本 → Esc（就地，回归基线）', async ({page}) => {
  await offSeed(page);
  await bootChat(page);
  await openWorkspaceSession(page, workspaceDir);
  await buildScene(page, 'flick-B', 'flick-B');
  await runTrace(page, 'off-short');
});

test('off-长消息: 不改文本 → Esc（就地，查看态 clamp）', async ({page}) => {
  await offSeed(page);
  await bootChat(page);
  await openWorkspaceSession(page, workspaceDir);
  await buildScene(page, LONG_BODY, 'flick-B');
  await runTrace(page, 'off-long');
});

test('on-短消息: 不改文本 → Esc（portal）', async ({page}) => {
  await onSeed(page);
  await bootChat(page);
  await openWorkspaceSession(page, workspaceDir);
  await buildScene(page, 'flick-B', 'flick-B');
  await runTrace(page, 'on-short');
});

test('on-长消息: 不改文本 → Esc（portal，查看态 clamp）', async ({page}) => {
  await onSeed(page);
  await bootChat(page);
  await openWorkspaceSession(page, workspaceDir);
  await buildScene(page, LONG_BODY, 'flick-B');
  await runTrace(page, 'on-long');
});

test('debug: 截图 EDIT 退出瞬态(验证无闪)', async ({page}) => {
  await offSeed(page);
  await bootChat(page);
  await openWorkspaceSession(page, workspaceDir);
  const ta = await buildScene(page, LONG_BODY, 'flick-B');
  await page.waitForTimeout(200);
  // 编辑态截图
  const editChip = await page.locator('[data-prompt-text^="flick-B"]').boundingBox();
  const editA = await page.locator('[data-prompt-text^="flick-A"]').boundingBox();
  console.log('=== EDIT chip box ===', JSON.stringify(editChip));
  console.log('=== EDIT flickA box ===', JSON.stringify(editA));
  await page.screenshot({path: `${process.env.TEMP || '/tmp'}/ef-1-editing.png`});
  // 退出
  await ta.press('Escape');
  // 立刻截 100ms 帧(收控件动画中)
  await page.waitForTimeout(100);
  await page.screenshot({path: `${process.env.TEMP || '/tmp'}/ef-mid-closing.png`});
  // 等稳定后再截
  await page.waitForTimeout(600);
  const viewChip = await page.locator('[data-prompt-text^="flick-B"]').boundingBox();
  const viewA = await page.locator('[data-prompt-text^="flick-A"]').boundingBox();
  console.log('=== VIEW chip box ===', JSON.stringify(viewChip));
  console.log('=== VIEW flickA box ===', JSON.stringify(viewA));
  await page.screenshot({path: `${process.env.TEMP || '/tmp'}/ef-2-view.png`});
});

test('debug: 进入/退出逐帧对照 + 退出关键帧截图', async ({page}) => {
  await offSeed(page);
  await bootChat(page);
  await openWorkspaceSession(page, workspaceDir);
  // 与 buildScene 同场景但不进 EDIT
  await send(page, 'flick-A');
  await waitSettled(page, 'flick-A');
  await send(page, LONG_BODY);
  await waitSettled(page, 'flick-B');
  await send(page, 'flick-C');
  await waitSettled(page, 'flick-C');

  await page.evaluate(SAMPLER);

  // ---- ENTRY：点「编辑」→ 预览出现 → 点预览切 textarea，全程采样 ----
  const editBtn = page.getByRole('button', {name: '编辑这条消息'}).filter({hasText: 'flick-B'}).first();
  await editBtn.scrollIntoViewIfNeeded();
  await page.evaluate(() => (window as any).__flickStart());
  await editBtn.click();
  const preview = page.getByLabel('点击开始编辑');
  await preview.waitFor({state: 'visible', timeout: 5_000});
  await page.waitForTimeout(400);
  await preview.click();
  await page.waitForTimeout(900);
  await page.evaluate(() => (window as any).__flickStop());
  const inRec = await page.evaluate(() => (window as any).__flickRec as any[]);
  console.log('=== ENTRY-REC ===', JSON.stringify(inRec));
  const entryStats = analyzeRec(inRec);
  console.log('=== ENTRY-STATS ===', JSON.stringify(entryStats));

  // ---- EXIT 采样 ----
  await page.evaluate(() => (window as any).__flickStart());
  await page.keyboard.press('Escape');
  await page.waitForTimeout(1100);
  await page.evaluate(() => (window as any).__flickStop());
  const outRec = await page.evaluate(() => (window as any).__flickRec as any[]);
  console.log('=== EXIT-REC ===', JSON.stringify(outRec));
  const exitStats = analyzeRec(outRec);
  console.log('=== EXIT-STATS ===', JSON.stringify(exitStats));

  // ---- 二次进入：停在预览态(不点进 textarea)，Esc 退出逐帧采样 + 关键帧截图 ----
  const editBtn2 = page.getByRole('button', {name: '编辑这条消息'}).filter({hasText: 'flick-B'}).first();
  await editBtn2.click();
  const preview2 = page.getByLabel('点击开始编辑');
  await preview2.waitFor({state: 'visible', timeout: 5_000});
  await page.waitForTimeout(600);
  await page.evaluate(() => (window as any).__flickStart());
  // 预览态 Esc 无处理器 → 用 pointerdown 外部点击(composer)触发 cancelEdit
  await page.getByPlaceholder(COMPOSER).click();
  await page.waitForTimeout(1100);
  await page.evaluate(() => (window as any).__flickStop());
  const outPrevRec = await page.evaluate(() => (window as any).__flickRec as any[]);
  console.log('=== EXIT-FROM-PREVIEW-REC ===', JSON.stringify(outPrevRec));
  console.log('=== EXIT-FROM-PREVIEW-STATS ===', JSON.stringify(analyzeRec(outPrevRec)));
  await expect(page.locator('.xy-editing-bubble')).toHaveCount(0);
});

function analyzeRec(rec: any[]) {
  let minOp = 1;
  let minOpAt = -1;
  let maxJump = 0;
  let maxJumpAt = -1;
  let driftSum = 0;
  const closingStart = rec.findIndex(r => r.closing);
  for (let i = 1; i < rec.length; i++) {
    const a0 = rec[i - 1].aTop;
    const a1 = rec[i].aTop;
    if (a0 !== null && a1 !== null) {
      const j = Math.abs(a1 - a0);
      driftSum += j;
      if (j > maxJump) {
        maxJump = j;
        maxJumpAt = rec[i].dt;
      }
    }
  }
  for (const r of rec) {
    if (r.ebOp !== null && r.ebOp < minOp) {
      minOp = r.ebOp;
      minOpAt = r.dt;
    }
  }
  const opBelow90 = rec.filter(r => r.ebOp !== null && r.ebOp < 0.9).map(r => r.dt);
  const aBotStart = rec.length ? rec[0].aBot : null;
  const aBotEnd = rec.length ? rec[rec.length - 1].aBot : null;
  const aBotRange = rec.map(r => r.aBot).filter(v => v !== null);
  const aBotJump = aBotRange.length
    ? Math.max(...aBotRange) - Math.min(...aBotRange)
    : 0;
  return {
    minOp,
    minOpAt,
    maxJump,
    maxJumpAt,
    closingStartAt: closingStart >= 0 ? rec[closingStart].dt : -1,
    opBelow90At: opBelow90.slice(0, 40),
    driftSum: Math.round(driftSum * 100) / 100,
    aBotMove: aBotStart !== null && aBotEnd !== null ? Math.round((aBotEnd - aBotStart) * 100) / 100 : null,
    aBotSpread: Math.round(aBotJump * 100) / 100,
    firstH: rec.length ? rec[0] : null,
    lastH: rec.length ? rec[rec.length - 1] : null,
  };
}

test('debug: 滚动容器身份探针(VIEW/EDIT-preview/EDIT-textarea)', async ({page}) => {
  await offSeed(page);
  await bootChat(page);
  await openWorkspaceSession(page, workspaceDir);
  await send(page, 'flick-A');
  await waitSettled(page, 'flick-A');
  await send(page, LONG_BODY);
  await waitSettled(page, 'flick-B');
  await send(page, 'flick-C');
  await waitSettled(page, 'flick-C');

  const probe = `(label) => {
    const chip = document.querySelector('[data-prompt-text^="flick-B"]');
    const selList = [
      '.xy-hover-scroll',
      '.xy-chat-surface',
      '.xy-chat-surface.xy-hover-scroll',
      '.xy-hover-scroll [data-xy-prompt-chip]',
      '.transcript', '.xy-round-transcript-layer', '[class*="scroll"]',
    ];
    const out = {label};
    const seen = new Set();
    for (const sel of selList) {
      for (const el of Array.from(document.querySelectorAll(sel))) {
        if (seen.has(el)) continue;
        seen.add(el);
        const r = el.getBoundingClientRect();
        const cs = getComputedStyle(el);
        const ov = cs.overflowY;
        out[sel + '#' + el.className.toString().slice(0, 70)] = {
          tag: el.tagName,
          st: Math.round(el.scrollTop * 100) / 100,
          canScroll: el.scrollHeight - el.clientHeight,
          top: Math.round(r.top),
          h: Math.round(r.height),
          ov,
          containsChip: el.contains ? el.contains(chip) : false,
        };
      }
    }
    return out;
  }`;
  for (const state of ['VIEW', 'EDIT-preview', 'EDIT-textarea']) {
    if (state === 'EDIT-preview') {
      const editBtn = page.getByRole('button', {name: '编辑这条消息'}).filter({hasText: 'flick-B'}).first();
      await editBtn.click();
      const preview = page.getByLabel('点击开始编辑');
      await preview.waitFor({state: 'visible', timeout: 5_000});
      await page.waitForTimeout(400);
    } else if (state === 'EDIT-textarea') {
      const preview = page.getByLabel('点击开始编辑');
      await preview.click();
      const ta = page.getByLabel('编辑历史消息');
      await expect(ta).toBeVisible();
      await page.waitForTimeout(800);
    }
    const dump = await page.evaluate(`(${probe})('${state}')`);
    console.log('=== SCROLL-PROBE', JSON.stringify(dump));
  }
});
