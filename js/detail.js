/**
 * detail.js
 * URL의 ?ticker=005930 파라미터를 읽어서
 * data/history/{ticker}.json (시세 이력 + 분석 + 공시)을 불러와 상세 페이지를 렌더링한다.
 *
 * data/history/{ticker}.json 에는 이미 analysis(신호/파동/타점/별점)가 통째로 들어있어서
 * "신호가 없어도 워치리스트(코스피/코스닥 시총 상위 300)에 속한 종목"도 이 페이지 하나로 완결된다.
 */

(function () {
  const params = new URLSearchParams(window.location.search);
  const ticker = params.get("ticker");
  const content = document.getElementById("detailContent");

  if (!ticker) {
    content.innerHTML = `<p class="empty-state">종목이 지정되지 않았습니다. 목록으로 돌아가주세요.</p>`;
    return;
  }

  function changeClass(rate) {
    if (rate === null || rate === undefined) return "change-flat";
    if (rate > 0) return "change-up";
    if (rate < 0) return "change-down";
    return "change-flat";
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

  async function load() {
    let history, waveBasisNote = "";

    try {
      const res = await fetch(`data/history/${ticker}.json?t=${Date.now()}`);
      if (!res.ok) throw new Error("history not found");
      history = await res.json();
    } catch (err) {
      content.innerHTML = `<p class="empty-state">
        이 종목의 상세 데이터를 찾을 수 없습니다. (신호 목록·워치리스트 300종목에 없는 종목이거나,
        데이터가 아직 갱신되지 않았을 수 있어요)
      </p>`;
      return;
    }

    try {
      const res = await fetch(`data/signals.json?t=${Date.now()}`);
      const data = await res.json();
      waveBasisNote = data.wave_basis_note || "";
    } catch (err) {
      // 기준 설명 문구를 못 가져와도 차트 자체는 렌더링 가능
    }

    render(history, waveBasisNote);
  }

  function render(history, waveBasisNote) {
    const info = history.analysis || {};
    const rate = info.change_rate;
    const rateText =
      rate === null || rate === undefined ? "-" : `${rate > 0 ? "+" : ""}${rate.toFixed(2)}%`;

    const tags = (info.signals || []).map((s) => `<span class="tag">${s}</span>`).join("");
    const hasSignals = (info.signals || []).length > 0;

    const disclosures = history.disclosures || [];
    const disclosuresHtml =
      disclosures.length > 0
        ? disclosures
            .map(
              (d) => `
        <a class="disclosure-item" href="${d.url}" target="_blank" rel="noopener">
          <span class="disclosure-title">${d.title}</span>
          <span class="disclosure-date">${d.date}</span>
        </a>
      `
            )
            .join("")
        : `<p class="empty-state" style="padding:20px;">최근 90일 내 공시가 없거나, 공시 조회 기능이 아직 설정되지 않았어요.</p>`;

    content.innerHTML = `
      <div class="detail-header">
        <div class="detail-title">
          <h1>${history.name}</h1>
          <span class="stock-ticker">${history.ticker}</span>
          <span class="stock-market">${history.market}</span>
          <div class="detail-rating">
            <div class="rating-badge ${ratingClass(info.rating_label)}">
              <div class="stars">${starHtml(info.rating_stars ?? 0)}</div>
              <span class="rating-text">${info.rating_label ?? "-"}</span>
            </div>
          </div>
        </div>
        <div class="detail-price">
          ${history.close.at(-1).toLocaleString()}<span class="unit">원</span>
          <div class="${changeClass(rate)}" style="font-size:14px;">${rateText}</div>
        </div>
      </div>

      <section class="detail-stats">
        <div class="stat-card">
          <div class="stat-num">${scoreMeterHtml(info.score ?? 0)}</div>
          <div class="stat-label">신호 점수</div>
        </div>
        <div class="stat-card">
          <div class="stat-num">${info.rsi ?? "-"}</div>
          <div class="stat-label">RSI(14)</div>
        </div>
        <div class="stat-card">
          <div class="stat-num">${info.volume_ratio ? info.volume_ratio + "x" : "-"}</div>
          <div class="stat-label">거래량 / 20일평균</div>
        </div>
        <div class="stat-card">
          <div class="stat-num">${info.volume?.toLocaleString() ?? "-"}</div>
          <div class="stat-label">당일 거래량</div>
        </div>
      </section>

      ${
        hasSignals
          ? `<div class="tag-list" style="margin-bottom:20px;">${tags}</div>`
          : info.insufficient_data
          ? `<p class="lookup-hint" style="margin-bottom:20px;color:var(--up);">
              상장/데이터 수집 후 거래일이 아직 부족해서(현재 ${info.trading_days_available}일, 분석에는 65일 필요)
              전체 신호·파동 분석은 준비되지 않았어요. 현재가·차트만 확인 가능해요.
            </p>`
          : `<p class="lookup-hint" style="margin-bottom:20px;">현재 감지된 기술적 신호가 없어요 (워치리스트 종목이라 항상 조회는 가능해요).</p>`
      }

      ${
        info.wave_direction
          ? `
      <div class="chart-card">
        <h3>파동 위치 &amp; 매매 타점</h3>
        <div class="wave-row">
          <span class="wave-badge ${info.wave_direction === "상승" ? "wave-up" : "wave-down"}">
            단기(일봉) ${info.wave_direction} ${info.wave_number}파
          </span>
          ${
            info.wave_direction_weekly
              ? `<span class="wave-badge ${info.wave_direction_weekly === "상승" ? "wave-up" : "wave-down"}">
                  장기(주봉) ${info.wave_direction_weekly} ${info.wave_number_weekly}파
                </span>`
              : ""
          }
          <span class="wave-progress">전 스윙 대비 진행률 ${info.wave_progress_pct ?? "-"}%</span>
        </div>
        ${
          info.trend_alignment
            ? `<p class="lookup-hint" style="margin-bottom:12px;">
                <strong style="color:var(--text);">${info.trend_alignment}</strong> — ${info.trend_alignment_note}
              </p>`
            : ""
        }
        <div class="level-grid">
          <div class="level-box">
            <div class="level-label">매수타점 (조정시 38.2%)</div>
            <div class="level-value">${info.buy_point ? info.buy_point.toLocaleString() + "원" : "해당없음"}</div>
          </div>
          <div class="level-box target">
            <div class="level-label">목표가 (확장 1.272배)</div>
            <div class="level-value">${info.target_price ? info.target_price.toLocaleString() + "원" : "해당없음"}</div>
          </div>
          <div class="level-box stop">
            <div class="level-label">손절가</div>
            <div class="level-value">${info.stop_loss ? info.stop_loss.toLocaleString() + "원" : "-"}</div>
          </div>
        </div>
        <p class="wave-basis">${waveBasisNote || ""}</p>
      </div>
      `
          : ""
      }

      <div class="chart-card">
        <h3>일봉 캔들 &amp; 매매 타점 오버레이</h3>
        <p class="lookup-hint" style="margin-bottom:10px;">
          마지막 캔들 기준일: <strong style="color:var(--text);">${history.dates.at(-1)}</strong>
          (실시간 아님 — 장마감 후 하루 1회 갱신되는 데이터예요. "오늘 vs 어제"는 GitHub Actions 실행 시점에
          데이터 소스가 그날 시세를 이미 게시했는지에 따라 달라져요)
        </p>
        <div class="chart-wrap main"><canvas id="priceChart"></canvas></div>
        <div class="legend-row">
          <span class="legend-item"><span class="legend-dot" style="background:#e5484d"></span>상승봉</span>
          <span class="legend-item"><span class="legend-dot" style="background:#3b82f6"></span>하락봉</span>
          <span class="legend-item"><span class="legend-dot" style="background:#f0b64d"></span>MA5</span>
          <span class="legend-item"><span class="legend-dot" style="background:#3ddc97"></span>MA20</span>
          <span class="legend-item"><span class="legend-dot" style="background:#a9b4cc"></span>MA60</span>
          ${history.ma112?.some((v) => v !== null) ? `<span class="legend-item"><span class="legend-dot" style="background:#c084fc"></span>MA112</span>` : ""}
          ${history.ma224?.some((v) => v !== null) ? `<span class="legend-item"><span class="legend-dot" style="background:#60a5fa"></span>MA224</span>` : ""}
          ${info.buy_point ? `<span class="legend-item"><span class="legend-dot" style="background:#f0b64d;opacity:.6"></span>매수타점(점선)</span>` : ""}
          ${info.target_price ? `<span class="legend-item"><span class="legend-dot" style="background:#3ddc97"></span>목표가(점선)</span>` : ""}
          ${info.stop_loss ? `<span class="legend-item"><span class="legend-dot" style="background:#e5484d"></span>손절가(점선)</span>` : ""}
          ${history.signal_markers?.length ? `<span class="legend-item">▲ 매수신호 · ▼ 매도신호 (과거 발생 지점)</span>` : ""}
        </div>
        <p class="wave-basis">
          112·224일선은 데이터가 아직 부족해서 안 보일 수 있어요 (캐시 저장소가 2026년 3월부터 시작돼서
          현재 확보 가능한 거래일수가 112일 미만이에요 — 시간이 지나며 자동으로 채워져요).
          ▲▼ 마커는 정배열전환/역배열전환, RSI 30·70 돌파, MACD 골든·데드크로스가 과거에 발생했던 지점이에요.
        </p>
      </div>

      <div class="chart-card">
        <h3>MACD (12,26,9)</h3>
        <div class="chart-wrap sub"><canvas id="macdChart"></canvas></div>
        <div class="legend-row">
          <span class="legend-item"><span class="legend-dot" style="background:#f0b64d"></span>MACD선</span>
          <span class="legend-item"><span class="legend-dot" style="background:#8b93a7"></span>시그널선</span>
          <span class="legend-item"><span class="legend-dot" style="background:#e5484d"></span>+히스토그램</span>
          <span class="legend-item"><span class="legend-dot" style="background:#3b82f6"></span>−히스토그램</span>
        </div>
      </div>

      <div class="chart-card">
        <h3>RSI (14)</h3>
        <div class="chart-wrap sub"><canvas id="rsiChart"></canvas></div>
        <div class="legend-row">
          <span class="legend-item"><span class="legend-dot" style="background:#f0b64d"></span>RSI</span>
          <span class="legend-item">점선: 과매수(70) / 과매도(30) 기준선</span>
        </div>
      </div>

      <div class="chart-card">
        <h3>거래량</h3>
        <div class="chart-wrap volume"><canvas id="volumeChart"></canvas></div>
      </div>

      <div class="chart-card">
        <h3>최근 공시 (DART, 최근 90일)</h3>
        <div class="disclosure-list">${disclosuresHtml}</div>
      </div>

      <p class="footnote">
        본 페이지는 기술적 지표 기반 자동 스캔 결과이며, 투자 조언이나 매수·매도 추천이 아닙니다.
        가격 데이터는 <strong>KRX 정규장(09:00~15:30) 종가</strong> 기준이며, 넥스트레이드(NXT) 애프터마켓
        (15:40~20:00) 체결가는 반영되지 않습니다. 또한 비공식 커뮤니티 데이터 캐시를 사용하므로
        드물게 오류가 있을 수 있습니다. <strong>실제 매매 전에는 반드시 증권사 앱/HTS에서 최종 시세를
        확인해주세요.</strong>
      </p>
    `;

    drawCharts(history, info);
  }

  function flatLine(labels, value) {
    return labels.map(() => value);
  }

  function toXY(dates, values) {
    return dates.map((d, i) => ({ x: new Date(d).valueOf(), y: values[i] }));
  }

  function drawCharts(history, info) {
    const labels = history.dates.map((d) => d.slice(5)); // MM-DD만 표시 (라인차트 폴백용)

    const canCandlestick =
      typeof Chart !== "undefined" &&
      Chart.registry &&
      Chart.registry.controllers.get("candlestick");

    if (canCandlestick) {
      try {
        drawCandlestickOverlay(history, info);
      } catch (err) {
        console.warn("[detail.js] 캔들스틱 차트 렌더링 실패, 라인차트로 대체합니다:", err);
        drawLineOverlay(history, info, labels);
      }
    } else {
      console.warn("[detail.js] 캔들스틱 플러그인을 불러오지 못해 라인차트로 대체합니다.");
      drawLineOverlay(history, info, labels);
    }

    drawVolumeChart(history, labels);
    drawMacdChart(history);
    drawRsiChart(history);
  }

  function drawCandlestickOverlay(history, info) {
    const candleData = history.dates.map((d, i) => ({
      x: new Date(d).valueOf(),
      o: history.open[i],
      h: history.high[i],
      l: history.low[i],
      c: history.close[i],
    }));

    const datasets = [
      {
        label: "일봉",
        type: "candlestick",
        data: candleData,
        color: { up: "#e5484d", down: "#3b82f6", unchanged: "#7c869c" }, // 국내 관례: 상승=빨강, 하락=파랑
        borderColor: { up: "#e5484d", down: "#3b82f6", unchanged: "#7c869c" },
      },
      {
        label: "MA5",
        type: "line",
        data: toXY(history.dates, history.ma5),
        borderColor: "#f0b64d",
        borderWidth: 1.5,
        pointRadius: 0,
        tension: 0.15,
      },
      {
        label: "MA20",
        type: "line",
        data: toXY(history.dates, history.ma20),
        borderColor: "#3ddc97",
        borderWidth: 1.5,
        pointRadius: 0,
        tension: 0.15,
      },
      {
        label: "MA60",
        type: "line",
        data: toXY(history.dates, history.ma60),
        borderColor: "#a9b4cc",
        borderWidth: 1.5,
        pointRadius: 0,
        tension: 0.15,
      },
    ];

    if (history.ma112?.some((v) => v !== null)) {
      datasets.push({
        label: "MA112",
        type: "line",
        data: toXY(history.dates, history.ma112),
        borderColor: "#c084fc",
        borderWidth: 1.5,
        pointRadius: 0,
        tension: 0.15,
      });
    }
    if (history.ma224?.some((v) => v !== null)) {
      datasets.push({
        label: "MA224",
        type: "line",
        data: toXY(history.dates, history.ma224),
        borderColor: "#60a5fa",
        borderWidth: 1.5,
        pointRadius: 0,
        tension: 0.15,
      });
    }

    if (info?.buy_point) {
      datasets.push({
        label: "매수타점",
        type: "line",
        data: toXY(history.dates, flatLine(history.dates, info.buy_point)),
        borderColor: "#f0b64d",
        borderWidth: 1,
        borderDash: [5, 4],
        pointRadius: 0,
      });
    }
    if (info?.target_price) {
      datasets.push({
        label: "목표가",
        type: "line",
        data: toXY(history.dates, flatLine(history.dates, info.target_price)),
        borderColor: "#3ddc97",
        borderWidth: 1,
        borderDash: [5, 4],
        pointRadius: 0,
      });
    }
    if (info?.stop_loss) {
      datasets.push({
        label: "손절가",
        type: "line",
        data: toXY(history.dates, flatLine(history.dates, info.stop_loss)),
        borderColor: "#e5484d",
        borderWidth: 1,
        borderDash: [2, 3],
        pointRadius: 0,
      });
    }

    if (history.signal_markers?.length) {
      const priceByDate = Object.fromEntries(history.dates.map((d, i) => [d, { l: history.low[i], h: history.high[i] }]));

      const buyMarkers = history.signal_markers
        .filter((m) => m.type === "buy")
        .map((m) => ({ x: new Date(m.date).valueOf(), y: priceByDate[m.date].l * 0.985, label: m.label }));
      const sellMarkers = history.signal_markers
        .filter((m) => m.type === "sell")
        .map((m) => ({ x: new Date(m.date).valueOf(), y: priceByDate[m.date].h * 1.015, label: m.label }));

      if (buyMarkers.length) {
        datasets.push({
          label: "매수신호",
          type: "scatter",
          data: buyMarkers,
          pointStyle: "triangle",
          rotation: 0,
          radius: 6,
          backgroundColor: "#e5484d",
          borderColor: "#e5484d",
        });
      }
      if (sellMarkers.length) {
        datasets.push({
          label: "매도신호",
          type: "scatter",
          data: sellMarkers,
          pointStyle: "triangle",
          rotation: 180,
          radius: 6,
          backgroundColor: "#3b82f6",
          borderColor: "#3b82f6",
        });
      }
    }

    new Chart(document.getElementById("priceChart"), {
      type: "candlestick",
      data: { datasets },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: { display: false },
          tooltip: {
            callbacks: {
              label: (ctx) => (ctx.raw?.label ? ctx.raw.label : ctx.dataset.label),
            },
          },
        },
        scales: {
          x: {
            type: "time",
            time: { unit: "week" },
            ticks: { color: "#7c869c", maxTicksLimit: 10 },
            grid: { color: "#182137" },
          },
          y: { ticks: { color: "#7c869c" }, grid: { color: "#182137" } },
        },
      },
    });
  }

  function drawLineOverlay(history, info, labels) {
    const priceDatasets = [
      {
        label: "종가",
        data: history.close,
        borderColor: "#f0b64d",
        backgroundColor: "#f0b64d22",
        borderWidth: 2,
        pointRadius: 0,
        tension: 0.15,
        fill: true,
      },
      {
        label: "MA5",
        data: history.ma5,
        borderColor: "#e5484d",
        borderWidth: 1,
        pointRadius: 0,
        tension: 0.15,
      },
      {
        label: "MA20",
        data: history.ma20,
        borderColor: "#3b82f6",
        borderWidth: 1,
        pointRadius: 0,
        tension: 0.15,
      },
      {
        label: "MA60",
        data: history.ma60,
        borderColor: "#8b93a7",
        borderWidth: 1,
        pointRadius: 0,
        tension: 0.15,
      },
    ];

    if (info?.buy_point) {
      priceDatasets.push({
        label: "매수타점",
        data: flatLine(labels, info.buy_point),
        borderColor: "#f0b64d",
        borderWidth: 1,
        borderDash: [5, 4],
        pointRadius: 0,
      });
    }
    if (info?.target_price) {
      priceDatasets.push({
        label: "목표가",
        data: flatLine(labels, info.target_price),
        borderColor: "#3ddc97",
        borderWidth: 1,
        borderDash: [5, 4],
        pointRadius: 0,
      });
    }
    if (info?.stop_loss) {
      priceDatasets.push({
        label: "손절가",
        data: flatLine(labels, info.stop_loss),
        borderColor: "#e5484d",
        borderWidth: 1,
        borderDash: [2, 3],
        pointRadius: 0,
      });
    }

    new Chart(document.getElementById("priceChart"), {
      type: "line",
      data: { labels, datasets: priceDatasets },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: { legend: { display: false } },
        scales: {
          x: { ticks: { color: "#7c869c", maxTicksLimit: 10 }, grid: { color: "#182137" } },
          y: { ticks: { color: "#7c869c" }, grid: { color: "#182137" } },
        },
      },
    });
  }

  function drawVolumeChart(history, labels) {
    new Chart(document.getElementById("volumeChart"), {
      type: "bar",
      data: {
        labels,
        datasets: [
          {
            label: "거래량",
            data: history.volume,
            backgroundColor: "#3b4a7566",
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: { legend: { display: false } },
        scales: {
          x: { ticks: { display: false }, grid: { display: false } },
          y: { ticks: { color: "#7c869c" }, grid: { color: "#182137" } },
        },
      },
    });
  }

  function drawMacdChart(history) {
    const macdXY = toXY(history.dates, history.macd);
    const signalXY = toXY(history.dates, history.macd_signal);
    const histData = history.dates.map((d, i) => {
      const m = history.macd[i], s = history.macd_signal[i];
      const diff = m !== null && s !== null ? m - s : null;
      return { x: new Date(d).valueOf(), y: diff };
    });

    new Chart(document.getElementById("macdChart"), {
      type: "bar",
      data: {
        datasets: [
          {
            label: "히스토그램",
            type: "bar",
            data: histData,
            backgroundColor: histData.map((p) => (p.y >= 0 ? "#e5484d66" : "#3b82f666")),
          },
          {
            label: "MACD",
            type: "line",
            data: macdXY,
            borderColor: "#f0b64d",
            borderWidth: 1.5,
            pointRadius: 0,
            tension: 0.1,
          },
          {
            label: "시그널",
            type: "line",
            data: signalXY,
            borderColor: "#8b93a7",
            borderWidth: 1.5,
            pointRadius: 0,
            tension: 0.1,
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: { legend: { display: false } },
        scales: {
          x: {
            type: "time",
            time: { unit: "week" },
            ticks: { color: "#7c869c", maxTicksLimit: 8 },
            grid: { color: "#182137" },
          },
          y: { ticks: { color: "#7c869c" }, grid: { color: "#182137" } },
        },
      },
    });
  }

  function drawRsiChart(history) {
    const rsiXY = toXY(history.dates, history.rsi);
    const refLine = (value) => history.dates.map((d) => ({ x: new Date(d).valueOf(), y: value }));

    new Chart(document.getElementById("rsiChart"), {
      type: "line",
      data: {
        datasets: [
          {
            label: "RSI",
            data: rsiXY,
            borderColor: "#f0b64d",
            borderWidth: 1.5,
            pointRadius: 0,
            tension: 0.1,
          },
          {
            label: "과매수(70)",
            data: refLine(70),
            borderColor: "#e5484d55",
            borderWidth: 1,
            borderDash: [4, 4],
            pointRadius: 0,
          },
          {
            label: "과매도(30)",
            data: refLine(30),
            borderColor: "#3b82f655",
            borderWidth: 1,
            borderDash: [4, 4],
            pointRadius: 0,
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: { legend: { display: false } },
        scales: {
          x: {
            type: "time",
            time: { unit: "week" },
            ticks: { color: "#7c869c", maxTicksLimit: 8 },
            grid: { color: "#182137" },
          },
          y: { min: 0, max: 100, ticks: { color: "#7c869c" }, grid: { color: "#182137" } },
        },
      },
    });
  }

  load();
})();
