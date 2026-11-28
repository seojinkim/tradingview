"use strict";
(function () {
  const $ = (id) => document.getElementById(id);
  const WD = ["월", "화", "수", "목", "금", "토", "일"];
  const LS_KEY = "qld-dashboard-v1";
  const pct = (x, d = 1) => (x * 100).toFixed(d) + "%";
  const usd = (x) => (x < 0 ? "-$" : "$") + Math.abs(x).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  const qty = (x) => Math.abs(x).toLocaleString("en-US", { minimumFractionDigits: 4, maximumFractionDigits: 4 });
  const wdOf = (iso) => WD[(new Date(iso + "T12:00:00Z").getUTCDay() + 6) % 7];
  const dLabel = (iso) => `${iso.slice(5).replace("-", "/")}(${wdOf(iso)})`;
  const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

  let latest = null, history = null, range = 252, weeksShown = 12;

  // ---------- storage (try/catch: 사생활 모드 등) ----------
  function loadPf() {
    try { return JSON.parse(localStorage.getItem(LS_KEY)) || {}; } catch (e) { return {}; }
  }
  function savePf(p) {
    try { localStorage.setItem(LS_KEY, JSON.stringify(p)); } catch (e) { /* ignore */ }
  }
  function readInputs() {
    const n = (id) => { const v = parseFloat($(id).value); return isFinite(v) && v >= 0 ? v : 0; };
    const dailyRaw = parseFloat($("daily").value);
    return { qldQty: n("qldQty"), sgovQty: n("sgovQty"), cash: n("cash"),
      daily: isFinite(dailyRaw) && dailyRaw >= 0 ? dailyRaw : 100, useSgov: $("useSgov").checked };
  }

  // ---------- 상단 신호 카드 ----------
  function renderSignal() {
    const s = latest.signal, t = latest.today;
    if (s) {
      const notFri = s.weekday !== 4;
      $("signalTitle").textContent = `이번 주 확정 신호 · ${dLabel(s.date)} 종가` + (notFri ? " (금요일 휴장 → 마지막 거래일 기준)" : "");
      $("sHv").textContent = s.tv_hv.toFixed(1);
      $("sW").innerHTML = pct(s.w) ;
      $("sLev").textContent = (s.w * 2).toFixed(2) + "배";
      if (s.delta_w != null) {
        const d = s.delta_w * 100, cls = d >= 0 ? "up" : "down";
        $("sDelta").innerHTML = `<span class="pill ${cls}">${d >= 0 ? "▲" : "▼"} ${Math.abs(d).toFixed(1)}%p</span> <span class="sub">${pct(s.prev_w)} →</span>`;
      }
      $("sSma").innerHTML = smaText(s);
      $("sClose").textContent = "$" + s.close.toFixed(2);
    }
    $("tLabel").textContent = `오늘 기준이라면 · ${dLabel(t.date)} 종가`;
    $("tHv").textContent = t.tv_hv.toFixed(1);
    $("tW").textContent = pct(t.w);
    $("tSma").innerHTML = smaText(t);
  }
  function smaText(r) {
    if (r.sma250 == null) return "<span class='sub'>데이터 부족</span>";
    const up = r.above_sma;
    return `<span class="pill ${up ? "up" : "down"}">${up ? "위 ▲" : "아래 ▼"}</span> <span class="sub">${r.sma_gap_pct >= 0 ? "+" : ""}${r.sma_gap_pct.toFixed(1)}%</span>`;
  }

  // ---------- 포트폴리오 / 리밸런싱 / 적립 ----------
  function renderPortfolio() {
    const p = readInputs();
    savePf(p);
    const px = latest.prices, w = (latest.signal || latest.today).w;
    const qldPx = px.QLD ? px.QLD.close : 0, sgovPx = px.SGOV ? px.SGOV.close : 0;
    const r = Rebalance.plan({ ...p, qldPx, sgovPx, w });

    const rows = [
      ["QLD", qldPx, r.qldVal], ["SGOV", sgovPx, r.sgovVal], ["예수금", null, r.cash],
    ];
    $("pfBody").innerHTML = rows.map(([n, c, v]) =>
      `<tr><td>${n}</td><td>${c ? "$" + c.toFixed(2) : "–"}</td><td>${usd(v)}</td><td>${r.total > 0 ? pct(v / r.total) : "–"}</td></tr>`
    ).join("") + `<tr><td><b>합계</b></td><td></td><td><b>${usd(r.total)}</b></td><td>${r.total > 0 ? "100%" : "–"}</td></tr>`;

    const sig = latest.signal;
    const when = sig ? `${dLabel(sig.date)} 신호 기준, 다음 거래일(보통 월요일)` : "다음 거래일";
    if (r.total <= 0) {
      $("rebal").innerHTML = `<span class="sub">보유 수량을 입력하면 계산됩니다.</span>`;
    } else {
      const head = `<div class="sub">실제 QLD 비중 <b>${pct(r.actual)}</b> · 목표 <b>${pct(w)}</b> · 차이 <b>${(r.diff * 100 >= 0 ? "+" : "") + (r.diff * 100).toFixed(1)}%p</b> (기준 ±10%p)</div>`;
      if (!r.rebalance) {
        $("rebal").innerHTML = head + `<div class="action hold" style="margin-top:10px"><b>이번 주는 유지</b><div class="sub">차이가 10%p 미만이라 매매하지 않습니다.</div></div>`;
      } else {
        const items = [];
        items.push(`QLD <b>${qty(r.qldShares)}주 ${r.qldShares < 0 ? "매도" : "매수"}</b> (${usd(Math.abs(r.qldAmount))})`);
        if (p.useSgov && Math.abs(r.sgovShares) > 0) items.push(`SGOV <b>${qty(r.sgovShares)}주 ${r.sgovShares < 0 ? "매도" : "매수"}</b> (${usd(Math.abs(r.sgovAmount))})`);
        items.push(`매매 후 예수금 약 ${usd(r.cashAfter)}` + (r.cashAfter < -0.01 ? ' <span class="err">(부족 — 순서: 매도 먼저)</span>' : ""));
        $("rebal").innerHTML = head + `<div class="action trade" style="margin-top:10px"><b>${when}에 ${pct(w)}로 조정</b><ul>${items.map((x) => `<li>${x}</li>`).join("")}</ul>` +
          `<div class="sub" style="margin-top:6px">${dLabel(latest.prices.QLD ? latest.prices.QLD.date : latest.data_date)} 종가로 계산. 실제 체결가에 따라 수량은 달라집니다. 매도 주문을 먼저 실행하세요.</div></div>`;
      }
    }

    const c = Rebalance.contribution(p.daily, w, qldPx, sgovPx);
    $("contrib").innerHTML = `하루 <b>${usd(p.daily)}</b>을 목표 비중 ${pct(w)}대로 나누면:` +
      `<ul style="margin:8px 0 0;padding-left:18px"><li>QLD <b>${usd(c.qld)}</b> (약 ${qty(c.qldShares)}주)</li>` +
      `<li>SGOV <b>${usd(c.sgov)}</b> (약 ${qty(c.sgovShares)}주)${p.useSgov ? "" : " — 또는 현금 보유"}</li></ul>` +
      `<div class="label" style="margin-top:6px">이번 주 확정 비중 기준 · 오늘 기준 비중이라면 QLD ${usd(p.daily * latest.today.w)}</div>`;
  }

  // ---------- 차트 (단일 시리즈, 크로스헤어 툴팁) ----------
  function lineChart(el, data, opt) {
    const W = Math.max(280, el.clientWidth || 680), H = W < 500 ? 170 : 200, m = { t: 10, r: 8, b: 24, l: 34 };
    const iw = W - m.l - m.r, ih = H - m.t - m.b;
    const ys = data.map((d) => d.y);
    let lo = opt.yMin != null ? opt.yMin : Math.min(...ys), hi = opt.yMax != null ? opt.yMax : Math.max(...ys);
    if (opt.ref != null) { lo = Math.min(lo, opt.ref); hi = Math.max(hi, opt.ref); }
    const step = niceStep((hi - lo) / 4);
    lo = Math.floor(lo / step) * step; hi = Math.ceil(hi / step) * step;
    const x = (i) => m.l + (data.length > 1 ? (i / (data.length - 1)) * iw : 0);
    const y = (v) => m.t + ih - ((v - lo) / (hi - lo || 1)) * ih;
    let s = `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(opt.title)}">`;
    for (let v = lo; v <= hi + 1e-9; v += step) {
      s += `<line x1="${m.l}" x2="${W - m.r}" y1="${y(v)}" y2="${y(v)}" stroke="var(--grid)" stroke-width="1"/>`;
      s += `<text x="${m.l - 6}" y="${y(v) + 4}" text-anchor="end" font-size="11" fill="var(--muted)">${opt.tick(v)}</text>`;
    }
    // x축: 월 경계 라벨
    let lastM = "", every = Math.ceil((data.length / 21) / (W / 60)), cnt = 0;
    data.forEach((d, i) => {
      const mo = d.date.slice(0, 7);
      if (mo !== lastM) {
        if (lastM && cnt++ % every === 0) {
          const lab = mo.slice(5) === "01" ? mo.slice(0, 4) : +mo.slice(5) + "월";
          s += `<text x="${x(i)}" y="${H - 6}" text-anchor="middle" font-size="11" fill="var(--muted)">${lab}</text>`;
        }
        lastM = mo;
      }
    });
    if (opt.ref != null) s += `<line x1="${m.l}" x2="${W - m.r}" y1="${y(opt.ref)}" y2="${y(opt.ref)}" stroke="var(--muted)" stroke-dasharray="4 4" stroke-width="1"/>`;
    const path = data.map((d, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(d.y).toFixed(1)}`).join("");
    s += `<path d="${path}" fill="none" stroke="var(--series)" stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/>`;
    const last = data[data.length - 1];
    s += `<circle cx="${x(data.length - 1)}" cy="${y(last.y)}" r="4" fill="var(--series)" stroke="var(--surface)" stroke-width="2"/>`;
    s += `<g class="hover" style="display:none"><line class="hx" y1="${m.t}" y2="${m.t + ih}" stroke="var(--muted)" stroke-width="1"/><circle class="hc" r="4" fill="var(--series)" stroke="var(--surface)" stroke-width="2"/></g>`;
    s += `<rect x="${m.l}" y="0" width="${iw}" height="${H}" fill="transparent" class="hit"/></svg><div class="tip"></div>`;
    el.innerHTML = s;

    const svg = el.querySelector("svg"), tip = el.querySelector(".tip"), g = el.querySelector(".hover");
    const move = (ev) => {
      const rect = svg.getBoundingClientRect();
      const cx = ((ev.touches ? ev.touches[0].clientX : ev.clientX) - rect.left) * (W / rect.width);
      const i = Math.max(0, Math.min(data.length - 1, Math.round(((cx - m.l) / iw) * (data.length - 1))));
      const d = data[i];
      g.style.display = "";
      g.querySelector(".hx").setAttribute("x1", x(i)); g.querySelector(".hx").setAttribute("x2", x(i));
      const c = g.querySelector(".hc"); c.setAttribute("cx", x(i)); c.setAttribute("cy", y(d.y));
      tip.style.display = "block";
      tip.innerHTML = `<div class="label">${d.date} (${wdOf(d.date)})</div><b>${opt.fmt(d.y)}</b>`;
      const px = (x(i) / W) * rect.width;
      tip.style.left = Math.min(Math.max(0, px - tip.offsetWidth / 2), rect.width - tip.offsetWidth) + "px";
      tip.style.top = Math.max(0, (y(d.y) / H) * rect.height - tip.offsetHeight - 12) + "px";
    };
    const leave = () => { g.style.display = "none"; tip.style.display = "none"; };
    svg.addEventListener("pointermove", move);
    svg.addEventListener("pointerdown", move);
    svg.addEventListener("pointerleave", leave);
  }
  function niceStep(raw) {
    const p = Math.pow(10, Math.floor(Math.log10(raw || 1))), f = raw / p;
    return (f <= 1 ? 1 : f <= 2 ? 2 : f <= 2.5 ? 2.5 : f <= 5 ? 5 : 10) * p;
  }
  function renderCharts() {
    const d = history.daily.slice(-range);
    lineChart($("chartHv"), d.map((r) => ({ date: r.date, y: r.tv_hv })),
      { title: "TradingView HV(20) 추이", yMin: 0, ref: 15, tick: (v) => v.toFixed(0), fmt: (v) => "HV " + v.toFixed(1) });
    lineChart($("chartW"), d.map((r) => ({ date: r.date, y: r.w * 100 })),
      { title: "목표 QLD 비중 추이", yMin: 0, yMax: 100, tick: (v) => v.toFixed(0) + "%", fmt: (v) => "목표 " + v.toFixed(1) + "%" });
  }

  function renderWeekly() {
    const w = history.weekly.slice().reverse();
    $("weekly").innerHTML = w.slice(0, weeksShown).map((s) => {
      const dd = s.delta_w != null ? (s.delta_w >= 0 ? "+" : "") + (s.delta_w * 100).toFixed(1) + "%p" : "–";
      const sma = s.sma250 != null ? (s.sma_gap_pct >= 0 ? "▲+" : "▼") + s.sma_gap_pct.toFixed(1) + "%" : "–";
      return `<tr><td>${s.date.slice(2).replace(/-/g, ".")}${s.weekday !== 4 ? "(" + wdOf(s.date) + ")" : ""}</td><td>${s.tv_hv.toFixed(1)}</td><td><b>${pct(s.w)}</b></td><td>${dd}</td><td>${sma}</td></tr>`;
    }).join("");
    $("moreWeeks").style.display = weeksShown >= w.length ? "none" : "";
  }

  function renderMeta() {
    const L = latest;
    $("asof").textContent = `${L.data_date || "–"} 종가 기준`;
    const src = L.sources ? Object.entries(L.sources).map(([k, v]) => `${k}:${v}`).join(", ") : "–";
    $("meta").innerHTML = `데이터 기준: ${esc(L.data_date || "–")} 미국 장 마감 · 갱신 ${esc(L.generated_at_kst || "–")} KST · 출처 ${esc(src)}` +
      ` · 상태: ${L.stale ? '<span class="err">오래된 데이터(stale)</span>' : "정상"}`;
    if (L.stale) {
      const box = $("staleBox");
      box.style.display = "block";
      const ls = L.last_success ? new Date(L.last_success).toLocaleString("ko-KR", { timeZone: "Asia/Seoul" }) : "없음";
      box.innerHTML = `⚠ 최근 데이터 수집에 실패해 이전 데이터를 표시 중입니다. 마지막 성공: ${esc(ls)}`;
    }
  }

  function bindInputs() {
    const p = loadPf();
    $("qldQty").value = p.qldQty || "";
    $("sgovQty").value = p.sgovQty || "";
    $("cash").value = p.cash || "";
    $("daily").value = p.daily != null ? p.daily : 100;
    $("useSgov").checked = p.useSgov !== false;
    $("pf").addEventListener("input", renderPortfolio);
    $("pf").addEventListener("change", renderPortfolio);
    document.querySelectorAll(".seg button").forEach((b) => b.addEventListener("click", () => {
      range = +b.dataset.range;
      document.querySelectorAll(".seg button").forEach((x) => x.setAttribute("aria-pressed", String(x === b)));
      renderCharts();
    }));
    $("moreWeeks").addEventListener("click", () => { weeksShown += 26; renderWeekly(); });
  }

  async function main() {
    try {
      const bust = "?t=" + Math.floor(Date.now() / 600000);
      const [l, h] = await Promise.all([
        fetch("data/latest.json" + bust).then((r) => r.json()),
        fetch("data/history.json" + bust).then((r) => r.json()),
      ]);
      latest = l; history = h;
    } catch (e) {
      $("staleBox").style.display = "block";
      $("staleBox").textContent = "데이터를 불러오지 못했습니다: " + e.message;
      return;
    }
    renderMeta();
    if (!latest.today) {
      $("staleBox").style.display = "block";
      $("staleBox").textContent = "아직 계산된 데이터가 없습니다. Actions에서 워크플로를 실행해 주세요.";
      return;
    }
    bindInputs();
    renderSignal();
    renderPortfolio();
    renderCharts();
    renderWeekly();
    let resizeT;
    window.addEventListener("resize", () => { clearTimeout(resizeT); resizeT = setTimeout(renderCharts, 150); });
  }
  main();
})();
