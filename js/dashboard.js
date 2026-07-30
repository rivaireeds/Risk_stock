/**
 * dashboard.js
 * data/signals.json 을 불러와서 검색/필터/정렬 후 테이블에 렌더링한다.
 * 백엔드 없이 순수 정적 파일(fetch)만으로 동작한다.
 *
 * [새로고침 관련 안내]
 * 이 버튼은 "지금 즉시 재계산"이 아니라, 이미 GitHub Actions가 계산해둔
 * 최신 data/signals.json을 다시 불러오는 것이다. 데이터 자체는 장마감 후
 * 하루 1회 갱신되므로, 장중에 눌러도 값이 바뀌지 않을 수 있다(정상 동작).
 */

(function () {
  let allStocks = [];
  let universeStocks = [];
  let currentFilter = "ALL";
  let currentSort = "rating_desc";
  let currentSearch = "";
  let lastUpdateTime = null;

  const tableBody = document.getElementById("tableBody");
  const searchBox = document.getElementById("searchBox");
  const sortSelect = document.getElementById("sortSelect");
  const filterChips = document.getElementById("filterChips");
  const refreshBtn = document.getElementById("refreshBtn");
  const lookupInput = document.getElementById("lookupInput");
  const lookupBtn = document.getElementById("lookupBtn");
  const lookupResults = document.getElementById("lookupResults");

  const COLUMN_COUNT = 8;
  const AUTO_POLL_MS = 3 * 60 * 1000; // 3분마다 자동으로 최신 데이터 확인

  async function loadData(isManualRefresh) {
    if (isManualRefresh) {
      refreshBtn.classList.add("spinning");
      refreshBtn.disabled = true;
    }

    try {
      // 캐시로 인해 예전 데이터가 보이는 걸 방지하기 위해 타임스탬프 쿼리 추가
      const res = await fetch(`data/signals.json?t=${Date.now()}`);
      const data = await res.json();

      lastUpdateTime = data.update_time || null;
      document.getElementById("updateTime").textContent = lastUpdateTime || "-";
      document.getElementById("dataDate").textContent = data.data_date || "-";
      document.getElementById("statScanned").textContent =
        (data.total_scanned || 0).toLocaleString();
      document.getElementById("statSignals").textContent =
        (data.total_signals || 0).toLocaleString();
      document.getElementById("statUniverse").textContent =
        (data.total_universe || 0).toLocaleString();

      allStocks = data.stocks || [];
      universeStocks = data.universe || [];
      render();
    } catch (err) {
      tableBody.innerHTML = `<tr><td colspan="${COLUMN_COUNT}" class="empty-state">
        데이터를 불러오지 못했습니다. data/signals.json 파일이 존재하는지 확인해주세요.
      </td></tr>`;
      console.error(err);
    } finally {
      if (isManualRefresh) {
        setTimeout(() => {
          refreshBtn.classList.remove("spinning");
          refreshBtn.disabled = false;
        }, 400);
      }
    }
  }

  function matchesFilter(stock) {
    if (currentFilter === "ALL") return true;
    if (currentFilter.startsWith("RATING:")) {
      const label = currentFilter.split("RATING:")[1];
      return stock.rating_label === label;
    }
    if (currentFilter === "피보나치") {
      return stock.signals.some((s) => s.startsWith("피보나치"));
    }
    return stock.signals.includes(currentFilter);
  }

  function matchesSearch(stock) {
    if (!currentSearch) return true;
    const q = currentSearch.toLowerCase();
    return (
      stock.name.toLowerCase().includes(q) ||
      stock.ticker.includes(q)
    );
  }

  function sortStocks(stocks) {
    const sorted = [...stocks];
    switch (currentSort) {
      case "rating_desc":
        sorted.sort((a, b) => (b.rating_stars ?? 0) - (a.rating_stars ?? 0) || b.score - a.score);
        break;
      case "score_desc":
        sorted.sort((a, b) => b.score - a.score);
        break;
      case "change_desc":
        sorted.sort((a, b) => (b.change_rate ?? -999) - (a.change_rate ?? -999));
        break;
      case "volume_desc":
        sorted.sort((a, b) => (b.volume_ratio ?? 0) - (a.volume_ratio ?? 0));
        break;
      case "name_asc":
        sorted.sort((a, b) => a.name.localeCompare(b.name, "ko"));
        break;
    }
    return sorted;
  }

  function scoreMeterHtml(score) {
    const max = 5;
    let segs = "";
    for (let i = 0; i < max; i++) {
      segs += `<div class="seg ${i < score ? "on" : ""}"></div>`;
    }
    return `<div class="score-meter">${segs}</div>`;
  }

  function starHtml(stars) {
    const max = 5;
    let out = "";
    for (let i = 0; i < max; i++) {
      out += `<span class="star ${i < stars ? "filled" : ""}">★</span>`;
    }
    return out;
  }

  function ratingClass(label) {
    if (label === "매수 적합") return "rating-buy";
    if (label === "관심 필요") return "rating-watch";
    return "rating-hold";
  }

  function changeClass(rate) {
    if (rate === null || rate === undefined) return "change-flat";
    if (rate > 0) return "change-up";
    if (rate < 0) return "change-down";
    return "change-flat";
  }

  function renderRow(stock) {
    const rate = stock.change_rate;
    const rateText =
      rate === null || rate === undefined
        ? "-"
        : `${rate > 0 ? "+" : ""}${rate.toFixed(2)}%`;

    const tags = stock.signals
      .map((s) => `<span class="tag">${s}</span>`)
      .join("");

    return `
      <tr class="row-link" onclick="window.location.href='detail.html?ticker=${stock.ticker}'">
        <td class="col-score">${scoreMeterHtml(stock.score)}</td>
        <td class="col-rating">
          <div class="rating-badge ${ratingClass(stock.rating_label)}">
            <div class="stars">${starHtml(stock.rating_stars ?? 0)}</div>
            <span class="rating-text">${stock.rating_label ?? "-"}</span>
          </div>
        </td>
        <td class="col-name">
          <span class="stock-name">${stock.name}</span>
          <span class="stock-ticker">${stock.ticker}</span>
          <span class="stock-market">${stock.market}</span>
        </td>
        <td class="col-price">${stock.price?.toLocaleString() ?? "-"}</td>
        <td class="col-change ${changeClass(rate)}">${rateText}</td>
        <td class="col-rsi">${stock.rsi ?? "-"}</td>
        <td class="col-vol">${stock.volume_ratio ? stock.volume_ratio + "x" : "-"}</td>
        <td class="col-tags"><div class="tag-list">${tags}</div></td>
      </tr>
    `;
  }

  function render() {
    const filtered = allStocks
      .filter(matchesFilter)
      .filter(matchesSearch);
    const sorted = sortStocks(filtered);

    if (sorted.length === 0) {
      tableBody.innerHTML = `<tr><td colspan="${COLUMN_COUNT}" class="empty-state">
        조건에 맞는 종목이 없습니다. 필터나 검색어를 바꿔보세요.
      </td></tr>`;
      return;
    }

    tableBody.innerHTML = sorted.map(renderRow).join("");
  }

  function runLookup() {
    const q = lookupInput.value.trim().toLowerCase();
    if (!q) {
      lookupResults.innerHTML = "";
      return;
    }

    const matches = universeStocks
      .filter((s) => s.name.toLowerCase().includes(q) || s.ticker.includes(q))
      .slice(0, 8);

    if (matches.length === 0) {
      lookupResults.innerHTML = `<p class="lookup-hint" style="color:var(--up);margin-top:10px;">
        "${lookupInput.value}"에 대한 데이터가 없어요. 시가총액 상위 300위 밖이면서 신호도 없는 종목일 수 있어요.
      </p>`;
      return;
    }

    lookupResults.innerHTML = `
      <div class="lookup-list">
        ${matches
          .map(
            (s) => `
          <div class="lookup-item" onclick="window.location.href='detail.html?ticker=${s.ticker}'">
            <div>
              <span class="stock-name">${s.name}</span>
              <span class="stock-ticker">${s.ticker}</span>
              <span class="stock-market">${s.market}</span>
            </div>
            <div class="rating-badge ${ratingClass(s.rating_label)}">
              <div class="stars">${starHtml(s.rating_stars ?? 0)}</div>
              <span class="rating-text">${s.rating_label ?? "-"}</span>
            </div>
          </div>
        `
          )
          .join("")}
      </div>
    `;
  }

  // ---- 이벤트 바인딩 ----

  searchBox.addEventListener("input", (e) => {
    currentSearch = e.target.value.trim();
    render();
  });

  sortSelect.addEventListener("change", (e) => {
    currentSort = e.target.value;
    render();
  });

  filterChips.addEventListener("click", (e) => {
    const btn = e.target.closest(".chip");
    if (!btn) return;
    filterChips.querySelectorAll(".chip").forEach((c) => c.classList.remove("active"));
    btn.classList.add("active");
    currentFilter = btn.dataset.filter;
    render();
  });

  refreshBtn.addEventListener("click", () => loadData(true));

  lookupBtn.addEventListener("click", runLookup);
  lookupInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter") runLookup();
  });

  loadData(false);
  setInterval(() => loadData(false), AUTO_POLL_MS); // 자동 폴링 (조용히 갱신, 스피너 없음)
})();
