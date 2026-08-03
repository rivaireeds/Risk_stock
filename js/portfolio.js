/**
 * portfolio.js
 * 보유종목/현금은 이 브라우저의 localStorage에만 저장한다(서버 전송 없음).
 * 현재가·신호·타점 등은 매일 자동 갱신되는 data/signals.json + data/history/{ticker}.json을
 * 그대로 읽어와서 매칭한다 — 그래서 워치리스트(시총 상위 300 + watchlist.txt)에 없는 종목은
 * 분석 데이터가 없을 수 있다.
 */

(function () {
  const LS_HOLDINGS = "portfolio_holdings_v1";
  const LS_CASH = "portfolio_cash_v1";

  let universeStocks = [];
  let holdings = loadHoldings();
  let cash = loadCash();
  let historyCache = {}; // ticker -> history.json 내용 (한번 불러오면 재사용)

  const holdingsBody = document.getElementById("holdingsBody");
  const strategyCards = document.getElementById("strategyCards");
  const addSearchInput = document.getElementById("addSearchInput");
  const addSearchResults = document.getElementById("addSearchResults");
  const addForm = document.getElementById("addForm");
  const addFormTitle = document.getElementById("addFormTitle");
  const addQty = document.getElementById("addQty");
  const addAvgPrice = document.getElementById("addAvgPrice");
  const addConfirmBtn = document.getElementById("addConfirmBtn");
  const cashInput = document.getElementById("cashInput");
  const cashSaveBtn = document.getElementById("cashSaveBtn");

  let pendingAdd = null; // 검색 결과에서 선택한 종목 (아직 수량/평단가 입력 전)

  // ---------------- localStorage 도우미 ----------------

  function loadHoldings() {
    try {
      const raw = localStorage.getItem(LS_HOLDINGS);
      return raw ? JSON.parse(raw) : [];
    } catch (e) {
      return [];
    }
  }

  function saveHoldings() {
    localStorage.setItem(LS_HOLDINGS, JSON.stringify(holdings));
  }

  function loadCash() {
    const raw = localStorage.getItem(LS_CASH);
    return raw ? Number(raw) : 0;
  }

  function saveCash(v) {
    cash = v;
    localStorage.setItem(LS_CASH, String(v));
  }

  // ---------------- 데이터 로드 ----------------

  async function loadUniverse() {
    try {
      const res = await fetch(`data/signals.json?t=${Date.now()}`);
      const data = await res.json();
      universeStocks = data.universe || [];
      document.getElementById("dataDate").textContent = data.data_date || "-";
    } catch (err) {
      console.error("universe 로드 실패", err);
    }
  }

  async function loadHistory(ticker) {
    if (historyCache[ticker]) return historyCache[ticker];
    try {
      const res = await fetch(`data/history/${ticker}.json?t=${Date.now()}`);
      if (!res.ok) throw new Error("no data");
      const data = await res.json();
      historyCache[ticker] = data;
      return data;
    } catch (err) {
      historyCache[ticker] = null;
      return null;
    }
  }

  function findInUniverse(ticker) {
    return universeStocks.find((s) => s.ticker === ticker) || null;
  }

  // ---------------- 렌더링: 요약 + 파이차트 ----------------

  let allocChartInstance = null;

  async function renderSummary() {
    let totalInvested = 0;
    let totalValue = 0;

    for (const h of holdings) {
      totalInvested += h.qty * h.avgPrice;
      const u = findInUniverse(h.ticker);
      const price = u ? u.price : h.avgPrice; // 데이터 없으면 평단가로 대체(손익 0 처리 방지)
      totalValue += h.qty * price;
    }

    const pnl = totalValue - totalInvested;
    const returnPct = totalInvested > 0 ? (pnl / totalInvested) * 100 : 0;
    const grandTotal = totalValue + cash;

    document.getElementById("sumInvested").textContent = totalInvested.toLocaleString() + "원";
    document.getElementById("sumValue").textContent = grandTotal.toLocaleString() + "원";

    const pnlEl = document.getElementById("sumPnl");
    pnlEl.textContent = (pnl >= 0 ? "+" : "") + pnl.toLocaleString() + "원";
    pnlEl.style.color = pnl > 0 ? "var(--up)" : pnl < 0 ? "var(--down)" : "";

    const retEl = document.getElementById("sumReturn");
    retEl.textContent = (returnPct >= 0 ? "+" : "") + returnPct.toFixed(2) + "%";
    retEl.style.color = returnPct > 0 ? "var(--up)" : returnPct < 0 ? "var(--down)" : "";

    if (allocChartInstance) allocChartInstance.destroy();
    allocChartInstance = new Chart(document.getElementById("allocChart"), {
      type: "doughnut",
      data: {
        labels: ["주식", "현금"],
        datasets: [{ data: [totalValue, cash], backgroundColor: ["#f0b64d", "#3ddc97"], borderWidth: 0 }],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: { legend: { position: "bottom", labels: { color: "#e7eaf2", font: { size: 11 } } } },
      },
    });
  }

  // ---------------- 렌더링: 보유종목 테이블 ----------------

  function renderHoldingsTable() {
    if (holdings.length === 0) {
      holdingsBody.innerHTML = `<tr><td colspan="8" class="empty-state">보유종목을 추가해보세요.</td></tr>`;
      return;
    }

    let totalValue = 0;
    const rows = holdings.map((h) => {
      const u = findInUniverse(h.ticker);
      const price = u ? u.price : null;
      const value = (price ?? h.avgPrice) * h.qty;
      totalValue += value;
      return { h, u, price, value };
    });

    holdingsBody.innerHTML = rows
      .map(({ h, u, price, value }) => {
        const pnl = price !== null ? (price - h.avgPrice) * h.qty : null;
        const pnlPct = price !== null && h.avgPrice > 0 ? ((price - h.avgPrice) / h.avgPrice) * 100 : null;
        const weight = totalValue > 0 ? (value / totalValue) * 100 : 0;
        const pnlClass = pnl === null ? "change-flat" : pnl > 0 ? "change-up" : pnl < 0 ? "change-down" : "change-flat";

        return `
          <tr>
            <td>
              <span class="stock-name">${h.name}</span>
              <span class="stock-ticker">${h.ticker}</span>
              ${u ? `<span class="stock-market">${u.market}</span>` : `<span class="stock-market" style="color:var(--up);border-color:var(--up);">데이터없음</span>`}
            </td>
            <td class="col-price">${h.qty.toLocaleString()}</td>
            <td class="col-price">${h.avgPrice.toLocaleString()}</td>
            <td class="col-price">${price !== null ? price.toLocaleString() : "-"}</td>
            <td class="col-change ${pnlClass}">${pnl !== null ? (pnl >= 0 ? "+" : "") + pnl.toLocaleString() : "-"}</td>
            <td class="col-change ${pnlClass}">${pnlPct !== null ? (pnlPct >= 0 ? "+" : "") + pnlPct.toFixed(2) + "%" : "-"}</td>
            <td class="col-price">${weight.toFixed(1)}%</td>
            <td><button class="remove-btn" data-ticker="${h.ticker}">삭제</button></td>
          </tr>
        `;
      })
      .join("");

    holdingsBody.querySelectorAll(".remove-btn").forEach((btn) => {
      btn.addEventListener("click", () => {
        holdings = holdings.filter((h) => h.ticker !== btn.dataset.ticker);
        saveHoldings();
        renderAll();
      });
    });
  }

  // ---------------- 렌더링: 종목별 대응 전략 ----------------

  function starHtml(stars) {
    let out = "";
    for (let i = 0; i < 5; i++) out += `<span class="star ${i < stars ? "filled" : ""}">★</span>`;
    return out;
  }

  function distanceText(current, target, label) {
    if (target === null || target === undefined || !current) return "";
    const pct = ((target - current) / current) * 100;
    return `${label} ${pct >= 0 ? "+" : ""}${pct.toFixed(1)}% 남음`;
  }

  async function renderStrategyCards() {
    if (holdings.length === 0) {
      strategyCards.innerHTML = `<p class="empty-state">보유종목이 없어요.</p>`;
      return;
    }

    const cardsHtml = await Promise.all(
      holdings.map(async (h) => {
        const history = await loadHistory(h.ticker);

        if (!history) {
          return `
            <div class="strategy-card">
              <div class="strategy-header">
                <span class="stock-name">${h.name}</span>
                <span class="stock-ticker">${h.ticker}</span>
              </div>
              <p class="lookup-hint" style="color:var(--up);">
                이 종목은 워치리스트(시총 상위 300 + watchlist.txt)에 없어서 자동분석 데이터가 없어요.
                아래 코드를 저장소의 <code>watchlist.txt</code>에 추가하면 다음 자동 갱신부터 분석이 표시돼요.
              </p>
              <div class="watchlist-copy">
                <span id="wl-${h.ticker}">${h.ticker}   # ${h.name}</span>
                <button onclick="navigator.clipboard.writeText(document.getElementById('wl-${h.ticker}').textContent)">복사</button>
              </div>
            </div>
          `;
        }

        const info = history.analysis || {};
        const price = info.price;

        const patternsHtml = (info.chart_patterns || [])
          .map((p) => `<span class="pattern-badge">${p.name} · ${p.detail}</span>`)
          .join(" ");

        const signalsHtml = (info.signals || [])
          .map((s) => `<span class="tag">${s}</span>`)
          .join("");

        return `
          <div class="strategy-card">
            <div class="strategy-header">
              <div>
                <span class="stock-name">${h.name}</span>
                <span class="stock-ticker">${h.ticker}</span>
                <span class="stock-market">${history.market}</span>
              </div>
              <div class="rating-badge ${info.rating_label === "매수 적합" ? "rating-buy" : info.rating_label === "관심 필요" ? "rating-watch" : "rating-hold"}">
                <div class="stars">${starHtml(info.rating_stars ?? 0)}</div>
                <span class="rating-text">${info.rating_label ?? "-"}</span>
              </div>
            </div>

            <div class="strategy-levels">
              <div class="level-box">
                <div class="level-label">1차 매수(38.2%)</div>
                <div class="level-value">${info.buy_point ? info.buy_point.toLocaleString() : "-"}</div>
              </div>
              <div class="level-box">
                <div class="level-label">2차 매수(61.8%)</div>
                <div class="level-value">${info.buy_point_2 ? info.buy_point_2.toLocaleString() : "-"}</div>
              </div>
              <div class="level-box target">
                <div class="level-label">1차 목표</div>
                <div class="level-value">${info.target_price ? info.target_price.toLocaleString() : "-"}</div>
              </div>
              <div class="level-box target">
                <div class="level-label">2차 목표(1.272배)</div>
                <div class="level-value">${info.target_price_2 ? info.target_price_2.toLocaleString() : "-"}</div>
              </div>
              <div class="level-box stop">
                <div class="level-label">손절가</div>
                <div class="level-value">${info.stop_loss ? info.stop_loss.toLocaleString() : "-"}</div>
              </div>
            </div>

            <p class="lookup-hint" style="margin-bottom:10px;">
              ${distanceText(price, info.target_price_2, "2차 목표까지")}
              ${info.stop_loss ? " · " + distanceText(price, info.stop_loss, "손절가까지") : ""}
              ${info.wave_direction ? ` · 단기: ${info.wave_direction}${info.wave_number}파(${info.wave_progress_pct ?? "-"}%)` : ""}
              ${info.wave_direction_weekly ? ` · 장기(주봉): ${info.wave_direction_weekly}${info.wave_number_weekly}파` : ""}
              ${info.trend_alignment ? ` · <strong style="color:var(--text);">${info.trend_alignment}</strong>` : ""}
            </p>

            ${patternsHtml ? `<div style="margin-bottom:10px;">${patternsHtml}</div>` : ""}
            ${signalsHtml ? `<div class="tag-list">${signalsHtml}</div>` : `<p class="lookup-hint">현재 감지된 매수/매도 신호가 없어요.</p>`}

            <p style="margin-top:12px;"><a href="detail.html?ticker=${h.ticker}" class="back-link">차트 자세히 보기 →</a></p>
          </div>
        `;
      })
    );

    strategyCards.innerHTML = cardsHtml.join("");
  }

  // ---------------- 종목 추가 ----------------

  function renderAddSearchResults() {
    const q = addSearchInput.value.trim().toLowerCase();
    if (!q) {
      addSearchResults.innerHTML = "";
      return;
    }
    const matches = universeStocks
      .filter((s) => s.name.toLowerCase().includes(q) || s.ticker.includes(q))
      .slice(0, 6);

    if (matches.length === 0) {
      addSearchResults.innerHTML = `<p class="lookup-hint" style="color:var(--up);margin-top:8px;">워치리스트(시총 상위 300)에서 못 찾았어요. 정확한 6자리 티커를 알고 계시면 직접 추가 기능은 추후 지원 예정이에요.</p>`;
      return;
    }

    addSearchResults.innerHTML = `
      <div class="lookup-list">
        ${matches
          .map(
            (s) => `
          <div class="lookup-item" data-ticker="${s.ticker}" data-name="${s.name}" data-market="${s.market}">
            <span class="stock-name">${s.name}</span>
            <span class="stock-ticker">${s.ticker}</span>
            <span class="stock-market">${s.market}</span>
          </div>
        `
          )
          .join("")}
      </div>
    `;

    addSearchResults.querySelectorAll(".lookup-item").forEach((el) => {
      el.addEventListener("click", () => {
        pendingAdd = { ticker: el.dataset.ticker, name: el.dataset.name, market: el.dataset.market };
        addFormTitle.textContent = `${pendingAdd.name} (${pendingAdd.ticker}) 추가`;
        addForm.style.display = "block";
        addSearchResults.innerHTML = "";
      });
    });
  }

  function confirmAdd() {
    if (!pendingAdd) return;
    const qty = Number(addQty.value);
    const avgPrice = Number(addAvgPrice.value);
    if (!qty || !avgPrice) {
      alert("수량과 평단가를 입력해주세요.");
      return;
    }

    holdings = holdings.filter((h) => h.ticker !== pendingAdd.ticker); // 같은 종목 재추가시 갱신
    holdings.push({ ticker: pendingAdd.ticker, name: pendingAdd.name, qty, avgPrice });
    saveHoldings();

    pendingAdd = null;
    addForm.style.display = "none";
    addSearchInput.value = "";
    addQty.value = "";
    addAvgPrice.value = "";

    renderAll();
  }

  // ---------------- 전체 렌더링 ----------------

  async function renderAll() {
    await renderSummary();
    renderHoldingsTable();
    await renderStrategyCards();
  }

  // ---------------- 초기화 ----------------

  async function init() {
    cashInput.value = cash || "";
    await loadUniverse();
    await renderAll();
  }

  addSearchInput.addEventListener("input", renderAddSearchResults);
  addConfirmBtn.addEventListener("click", confirmAdd);
  cashSaveBtn.addEventListener("click", () => {
    saveCash(Number(cashInput.value) || 0);
    renderAll();
  });

  init();
})();
