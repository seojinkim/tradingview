// 리밸런싱 · 적립 계산 (브라우저와 Node 테스트에서 공용)
(function (root, factory) {
  if (typeof module === "object" && module.exports) module.exports = factory();
  else root.Rebalance = factory();
})(typeof self !== "undefined" ? self : this, function () {
  const BAND = 0.10;
  const EPS = 1e-9;
  const r4 = (x) => Math.round(x * 1e4) / 1e4;
  const r2 = (x) => Math.round(x * 100) / 100;

  /**
   * @param {object} p
   *  qldQty, sgovQty, cash, qldPx, sgovPx, w (목표 0~1),
   *  useSgov: true면 나머지(1-w)를 전부 SGOV로, false면 SGOV는 그대로 두고 예수금으로 조절
   */
  function plan(p) {
    const qldVal = p.qldQty * p.qldPx;
    const sgovVal = p.sgovQty * p.sgovPx;
    const cash = p.cash || 0;
    const total = qldVal + sgovVal + cash;
    const actual = total > 0 ? qldVal / total : 0;
    const diff = actual - p.w;
    const rebalance = total > 0 && Math.abs(diff) >= BAND - EPS;
    const out = { total, qldVal, sgovVal, cash, actual, target: p.w, diff, rebalance,
      qldShares: 0, qldAmount: 0, sgovShares: 0, sgovAmount: 0, cashAfter: cash };
    if (!rebalance) return out;

    const qldTarget = p.w * total;
    out.qldAmount = r2(qldTarget - qldVal);           // +매수 / -매도
    out.qldShares = r4(out.qldAmount / p.qldPx);
    if (p.useSgov !== false && p.sgovPx > 0) {
      const sgovTarget = (1 - p.w) * total;
      out.sgovAmount = r2(sgovTarget - sgovVal);
      out.sgovShares = r4(out.sgovAmount / p.sgovPx);
    }
    out.cashAfter = r2(cash - out.qldAmount - out.sgovAmount);
    return out;
  }

  function contribution(amount, w, qldPx, sgovPx) {
    const qld = r2(amount * w);
    const sgov = r2(amount - qld);
    return { qld, sgov,
      qldShares: qldPx > 0 ? r4(qld / qldPx) : 0,
      sgovShares: sgovPx > 0 ? r4(sgov / sgovPx) : 0 };
  }

  return { plan, contribution, BAND };
});
