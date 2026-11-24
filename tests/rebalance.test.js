const test = require("node:test");
const assert = require("node:assert");
const { plan, contribution } = require("../rebalance.js");

const base = { qldPx: 100, sgovPx: 100, cash: 0, useSgov: true };

test("실제 65% / 목표 58% → 유지", () => {
  const r = plan({ ...base, qldQty: 65, sgovQty: 35, w: 0.58 });
  assert.strictEqual(r.rebalance, false);
  assert.strictEqual(r.qldShares, 0);
});

test("실제 65% / 목표 54% → 정확히 54%로 조정", () => {
  const r = plan({ ...base, qldQty: 65, sgovQty: 35, w: 0.54 });
  assert.strictEqual(r.rebalance, true);
  assert.strictEqual(r.qldShares, -11);   // QLD 11주 매도
  assert.strictEqual(r.sgovShares, 11);   // SGOV 11주 매수
  assert.ok(Math.abs((r.qldVal + r.qldAmount) / r.total - 0.54) < 1e-9);
  assert.strictEqual(r.cashAfter, 0);
});

test("정확히 10%p 차이면 조정", () => {
  assert.strictEqual(plan({ ...base, qldQty: 65, sgovQty: 35, w: 0.55 }).rebalance, true);
});

test("예수금 포함, 소수점 4자리 수량", () => {
  const r = plan({ qldQty: 10, sgovQty: 5, cash: 1234.56, qldPx: 123.45, sgovPx: 100.37, w: 0.3, useSgov: true });
  assert.strictEqual(r.rebalance, true);
  assert.ok(Math.abs(r.cashAfter) < 0.02);
  assert.strictEqual(r.qldShares, Math.round(r.qldShares * 1e4) / 1e4);
});

test("SGOV 미사용 시 예수금으로 조정", () => {
  const r = plan({ ...base, qldQty: 65, sgovQty: 0, cash: 3500, w: 0.54, useSgov: false });
  assert.strictEqual(r.sgovShares, 0);
  assert.strictEqual(r.cashAfter, 3500 + 1100);
});

test("적립 분배", () => {
  const c = contribution(100, 0.32, 80, 100);
  assert.strictEqual(c.qld, 32);
  assert.strictEqual(c.sgov, 68);
  assert.strictEqual(c.qldShares, 0.4);
});
