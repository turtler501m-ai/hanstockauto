const formatCurrency = (value) => {
    return new Intl.NumberFormat('ko-KR', {
        style: 'currency',
        currency: 'KRW',
        maximumFractionDigits: 0
    }).format(Number(value || 0));
};

const formatPercent = (value) => {
    const numeric = Number(value || 0);
    const sign = numeric > 0 ? '+' : '';
    return `${sign}${numeric.toFixed(2)}%`;
};

const formatNumber = (value, digits = 0) => {
    const numeric = Number(value || 0);
    return numeric.toLocaleString(undefined, { maximumFractionDigits: digits });
};

const escapeHtml = (value) => {
    return String(value ?? '')
        .replaceAll('&', '&amp;')
        .replaceAll('<', '&lt;')
        .replaceAll('>', '&gt;')
        .replaceAll('"', '&quot;')
        .replaceAll("'", '&#039;');
};

const ACTION_LABELS = {
    buy: '매수',
    sell: '매도',
    hold: '보유',
};

const STATUS_LABELS = {
    pending: '승인대기',
    executed: '처리완료',
    failed: '실패',
    rejected: '거절',
};

const toKorAction = (value) => {
    const key = String(value || 'hold').toLowerCase();
    return ACTION_LABELS[key] || value || '-';
};

const toKorStatus = (value) => {
    const key = String(value || '').toLowerCase();
    return STATUS_LABELS[key] || value || '-';
};

const translateReason = (value) => {
    const replacements = [
        ['stop loss', '손절 기준 도달'],
        ['take profit', '익절 기준 도달'],
        ['large profit split sell', '큰 수익 분할매도'],
        ['MACD bearish take profit', 'MACD 약세 익절'],
        ['split buy', '분할매수'],
        ['multi-strategy buy', '복합 전략 매수'],
        ['golden cross buy', '골든크로스 매수'],
        ['AI allocation target', 'AI 목표비중'],
        ['Portfolio optimizer target', '포트폴리오 목표비중'],
        ['score', '점수'],
        ['vol', '변동성'],
    ];
    let text = String(value || '-');
    replacements.forEach(([from, to]) => {
        text = text.replaceAll(from, to);
    });
    return text;
};

const strategyReasonLabel = (reason) => {
    const text = String(reason || '').trim();
    if (!text) {
        return '데이터 부족';
    }

    const mappings = [
        ['RSI recovery', '과매도 구간에서 반등 신호가 확인됐습니다.'],
        ['RSI pullback', '단기 조정 뒤 재진입을 검토할 수 있는 구간입니다.'],
        ['MACD bullish cross', 'MACD 골든크로스가 나와 상승 전환 가능성이 있습니다.'],
        ['MACD positive', 'MACD 흐름이 플러스라 단기 모멘텀이 유지되고 있습니다.'],
        ['Bollinger rebound', '볼린저 하단 반등이 나와 기술적 되돌림 가능성이 있습니다.'],
        ['near lower band', '주가가 볼린저 하단 부근이라 반등 관찰 구간입니다.'],
        ['trend pullback', '상승 추세 안에서 눌림목이 나온 모습입니다.'],
        ['long trend pullback', '중기 상승 추세 안에서 조정이 진행 중입니다.'],
        ['20-day breakout with volume', '거래량을 동반한 20일 돌파가 나왔습니다.'],
        ['volume spike', '거래량이 평소보다 강하게 증가했습니다.'],
        ['SMA20>SMA60', '단기 이동평균이 중기선 위에 있어 추세가 우호적입니다.']
    ];

    for (const [needle, label] of mappings) {
        if (text.includes(needle)) {
            return label;
        }
    }
    return translateReason(text);
};

const aiActionGuide = (action, name) => {
    if (action === 'buy') {
        return `${name} 비중을 조금 더 실어도 된다는 판단입니다.`;
    }
    if (action === 'sell') {
        return `${name} 비중이 현재 조건 대비 다소 크므로 줄이는 편이 낫다는 판단입니다.`;
    }
    return `${name}은 지금은 비중을 크게 바꾸지 않고 유지하는 편이 낫다는 판단입니다.`;
};

const aiDecisionLabel = (action) => {
    if (action === 'buy') {
        return '비중 확대';
    }
    if (action === 'sell') {
        return '비중 축소';
    }
    return '비중 유지';
};

function buildAiModalMarkup(payload) {
    const reasons = Array.isArray(payload.reasons) ? payload.reasons : [];
    const summary = payload.reasoning_kr || aiActionGuide(payload.action, payload.name);
    const reasonItems = reasons.length
        ? reasons.map((reason) => `<li>${escapeHtml(strategyReasonLabel(reason))}</li>`).join('')
        : '<li>뚜렷한 기술적 신호가 충분하지 않아 보수적으로 판단했습니다.</li>';

    const signalItems = [
        `AI 점수는 <strong>${escapeHtml(formatNumber(payload.score, 2))}</strong>점입니다.`,
        `현재 비중은 <strong>${escapeHtml(formatNumber(payload.currentWeight * 100, 1))}%</strong>, 목표 비중은 <strong>${escapeHtml(formatNumber(payload.targetWeight * 100, 1))}%</strong>입니다.`,
        `차이 금액은 <strong>${escapeHtml(formatCurrency(payload.deltaValue))}</strong>이며, 실행 액션은 <strong>${escapeHtml(aiDecisionLabel(payload.action))}</strong>입니다.`,
        `최근 변동성은 <strong>${escapeHtml(formatNumber(payload.volatility * 100, 1))}%</strong>로 계산되었습니다.`
    ].map((line) => `<li>${line}</li>`).join('');

    const rawReasons = reasons.length
        ? `<div class="ai-modal-raw">${escapeHtml(reasons.join(' | '))}</div>`
        : '';

    return `
        <div class="ai-modal-summary">
            <div class="ai-modal-badge ${escapeHtml(payload.action)}">${escapeHtml(aiDecisionLabel(payload.action))}</div>
            <p>${escapeHtml(summary)}</p>
        </div>
        <div class="ai-modal-section">
            <h3>한눈에 보기</h3>
            <ul class="ai-modal-list">${signalItems}</ul>
        </div>
        <div class="ai-modal-section">
            <h3>왜 이런 판단이 나왔나</h3>
            <ul class="ai-modal-list">${reasonItems}</ul>
            ${rawReasons}
        </div>
        <div class="ai-modal-section">
            <h3>읽는 법</h3>
            <p class="ai-modal-footnote">
                목표 비중은 “이 종목을 전체 자산에서 어느 정도까지 가져가면 좋은지”를 뜻합니다.
                현재 비중보다 목표 비중이 높으면 매수 쪽, 낮으면 축소 쪽으로 해석하면 됩니다.
            </p>
        </div>
    `;
}

const setTableMessage = (selector, colspan, message) => {
    const tbody = document.querySelector(selector);
    tbody.innerHTML = `<tr><td colspan="${colspan}" class="empty-state">${escapeHtml(message)}</td></tr>`;
};

const setStatus = (message, ok = false) => {
    const banner = document.getElementById('status-banner');
    banner.hidden = false;
    banner.className = `status-banner ${ok ? 'ok' : ''}`;
    banner.textContent = message;
};

const setButtonBusy = (id, busy) => {
    const button = document.getElementById(id);
    if (button) {
        button.disabled = busy;
    }
};

async function fetchJson(url) {
    const response = await fetch(url);
    const data = await response.json();
    if (!response.ok) {
        throw new Error(data.detail || `요청 실패: ${response.status}`);
    }
    return data;
}

async function postJson(url, payload = {}) {
    const response = await fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
    });
    const data = await response.json();
    if (!response.ok) {
        throw new Error(data.detail || `요청 실패: ${response.status}`);
    }
    return data;
}

function pill(value, kind = 'hold') {
    return `<span class="pill pill-${kind}">${escapeHtml(value)}</span>`;
}

function setAiModalOpen(open) {
    const modal = document.getElementById('aiModal');
    if (!modal) {
        return;
    }
    modal.style.display = open ? 'block' : 'none';
    modal.setAttribute('aria-hidden', open ? 'false' : 'true');
}

function setNoCandidatesModalOpen(open) {
    const modal = document.getElementById('noCandidatesModal');
    if (!modal) return;
    modal.style.display = open ? 'block' : 'none';
    modal.setAttribute('aria-hidden', open ? 'false' : 'true');
}

function buildScanErrorModalMarkup(errorMsg) {
    return `
        <div class="ai-modal-section">
            <h3>오류 내용</h3>
            <p class="ai-modal-footnote">${escapeHtml(errorMsg)}</p>
        </div>
        <div class="ai-modal-section">
            <h3>이렇게 해보세요</h3>
            <ul class="ai-modal-list">
                <li>잠시 후 다시 <strong>찾기</strong> 버튼을 눌러보세요.</li>
                <li>인터넷 연결 상태를 확인하세요.</li>
                <li>장 시간 중(09:00~15:30)에는 데이터가 더 안정적으로 수신됩니다.</li>
                <li>문제가 계속되면 YFINANCE_TIMEOUT_SECONDS 환경변수를 늘려보세요 (기본값: 8초).</li>
            </ul>
        </div>
    `;
}

function buildNoCandidatesModalMarkup(data) {
    const summary = data.scan_summary || [];
    const minScore = data.min_score || 2;
    const scanned = data.scanned || summary.length;

    // 점수 분포
    const scoreGroups = { 0: 0, 1: 0 };
    summary.forEach(item => {
        const s = item.score || 0;
        scoreGroups[s] = (scoreGroups[s] || 0) + 1;
    });

    // 가장 높은 점수 종목들 (상위 8개)
    const top = summary.slice(0, 8);

    const scoreDistItems = Object.entries(scoreGroups)
        .sort((a, b) => Number(b[0]) - Number(a[0]))
        .map(([score, count]) => `<li><strong>${score}점</strong>: ${count}종목</li>`)
        .join('');

    // 시그널 집계: 어떤 신호가 가장 많이 발생했나
    const signalCount = {};
    summary.forEach(item => {
        (item.reasons || []).forEach(r => {
            signalCount[r] = (signalCount[r] || 0) + 1;
        });
    });
    const topSignals = Object.entries(signalCount)
        .sort((a, b) => b[1] - a[1])
        .slice(0, 4)
        .map(([r, cnt]) => `<li>${escapeHtml(strategyReasonLabel(r))} <span class="muted">(${cnt}종목)</span></li>`)
        .join('');

    const topRows = top.map(item => {
        const scoreClass = item.score >= minScore ? 'buy' : (item.score > 0 ? 'warn' : 'sell');
        const reasonText = (item.reasons || []).map(r => strategyReasonLabel(r)).join(', ') || '신호 없음';
        const gap = minScore - item.score;
        const gapText = gap > 0 ? `<span class="muted">(${gap}점 부족)</span>` : '<span class="pill pill-buy">통과</span>';
        return `
            <tr>
                <td><span class="symbol-name">${escapeHtml(item.ticker)}</span></td>
                <td>${pill(item.score, scoreClass)} ${gapText}</td>
                <td>${formatNumber(item.rsi, 1)}</td>
                <td>${formatNumber(item.macd_hist, 1)}</td>
                <td><div class="reason-cell" title="${escapeHtml(reasonText)}">${escapeHtml(reasonText)}</div></td>
            </tr>`;
    }).join('');

    const marketMood = summary.length === 0
        ? '데이터를 수신하지 못했습니다.'
        : summary.every(i => i.score === 0)
            ? '분석한 모든 종목에서 매수 신호가 하나도 발생하지 않았습니다. 시장 전반이 관망 국면일 가능성이 높습니다.'
            : `일부 종목에서 약한 신호(${Math.max(...summary.map(i=>i.score))}점)가 있으나 기준(${minScore}점)에 미치지 못합니다. 시장 모멘텀이 아직 충분히 형성되지 않은 상태입니다.`;

    return `
        <div class="ai-modal-section">
            <h3>스캔 요약</h3>
            <ul class="ai-modal-list">
                <li>분석 종목 수: <strong>${scanned}종목</strong></li>
                <li>매수 기준 점수: <strong>${minScore}점 이상</strong></li>
                <li>매수 후보: <strong>0종목</strong></li>
            </ul>
        </div>
        <div class="ai-modal-section">
            <h3>시장 판단</h3>
            <p class="ai-modal-footnote">${escapeHtml(marketMood)}</p>
        </div>
        ${topSignals ? `
        <div class="ai-modal-section">
            <h3>감지된 부분 신호 (기준 미달)</h3>
            <ul class="ai-modal-list">${topSignals}</ul>
        </div>` : ''}
        <div class="ai-modal-section">
            <h3>점수별 종목 분포</h3>
            <ul class="ai-modal-list">${scoreDistItems || '<li>분석 데이터 없음</li>'}</ul>
        </div>
        ${topRows ? `
        <div class="ai-modal-section">
            <h3>상위 스코어 종목 상세</h3>
            <div class="table-responsive">
                <table>
                    <thead><tr><th>종목</th><th>점수</th><th>RSI</th><th>MACD</th><th>감지 신호</th></tr></thead>
                    <tbody>${topRows}</tbody>
                </table>
            </div>
        </div>` : ''}
        <div class="ai-modal-section">
            <h3>이렇게 해보세요</h3>
            <ul class="ai-modal-list">
                <li>잠시 후 다시 검색하거나, 장 시작 직후/마감 1시간 전에 시도해보세요.</li>
                <li>최소 점수를 1점으로 낮추면 더 많은 후보를 볼 수 있습니다.</li>
                <li>시장 전반이 하락 국면이라면 현금 비중을 유지하는 것이 유리합니다.</li>
            </ul>
        </div>
    `;
}

let portfolioChartInstance = null;
let latestConfig = null;

function renderPortfolioChart(labels, data, colors) {
    if (typeof Chart === 'undefined') {
        return;
    }

    const ctx = document.getElementById('portfolioChart').getContext('2d');
    if (portfolioChartInstance) {
        portfolioChartInstance.destroy();
    }

    Chart.defaults.color = '#94a3b8';
    Chart.defaults.font.family = "'Noto Sans KR', 'Inter', sans-serif";

    portfolioChartInstance = new Chart(ctx, {
        type: 'doughnut',
        data: {
            labels,
            datasets: [{
                data,
                backgroundColor: colors,
                borderWidth: 0,
                hoverOffset: 4
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: {
                    position: 'right',
                    labels: { boxWidth: 12, padding: 15 }
                }
            },
            cutout: '65%'
        }
    });
}

async function renderRuntime() {
    const health = await fetchJson('/api/health');
    const circuit = health.circuit_breaker || {};
    document.getElementById('runtime-env').textContent = health.trading_env === 'real' ? '실전' : '모의';
    document.getElementById('runtime-dry-run').innerHTML = health.dry_run ? pill('켜짐', 'warn') : pill('꺼짐', 'buy');
    document.getElementById('runtime-order').innerHTML = health.order_submission_enabled ? pill('가능', 'buy') : pill('차단', 'warn');
    document.getElementById('runtime-real').innerHTML = health.real_orders_enabled ? pill('가능', 'sell') : pill('차단', 'hold');
    document.getElementById('runtime-circuit').innerHTML = circuit.opened
        ? pill(`차단 ${circuit.retry_after_seconds || 0}초`, 'sell')
        : pill(`정상 ${circuit.error_count || 0}/${circuit.max_errors || 5}`, 'buy');
        
    const btnSyncTrades = document.getElementById('btn-sync-trades');
    if (btnSyncTrades) {
        if (health.dry_run) {
            btnSyncTrades.disabled = true;
            btnSyncTrades.textContent = '동기화 불가 (모의 실행)';
            btnSyncTrades.title = '모의 실행(DRY_RUN) 중에는 증권사 실계좌와 동기화할 수 없습니다.';
        } else {
            btnSyncTrades.disabled = false;
            btnSyncTrades.textContent = '증권사 기록 동기화';
            btnSyncTrades.title = '';
        }
    }
}

async function resetCircuitBreaker() {
    setButtonBusy('btn-reset-circuit', true);
    try {
        await postJson('/api/circuit-breaker/reset', {});
        setStatus('API 차단기를 초기화했습니다. 계좌 정보를 다시 불러옵니다.', true);
        await Promise.all([renderRuntime(), renderBalance()]);
    } catch (err) {
        setStatus(`API 차단기 초기화 실패: ${err.message}`);
    } finally {
        setButtonBusy('btn-reset-circuit', false);
    }
}

async function renderConfig() {
    const config = await fetchJson('/api/config');
    latestConfig = config;
    const items = [
        ['분할 횟수', `${config.split_n}회`],
        ['손절 기준', `${config.stop_loss_pct}%`],
        ['익절 기준', `${config.take_profit}%`],
        ['RSI 매수선', config.rsi_buy],
        ['RSI 매도선', config.rsi_sell],
        ['기준 자본', formatCurrency(config.total_capital)],
        ['최대 보유종목', `${config.max_positions}개`],
        ['종목당 최대비중', `${formatNumber(config.max_single_weight * 100, 1)}%`],
        ['현금 보유비중', `${formatNumber(config.cash_buffer * 100, 1)}%`],
        ['일 손실 제한', `${config.max_daily_loss_pct}%`],
        ['관심종목', `${config.watchlist.length}개`],
        ['전략 묶음', `${(config.strategy_sources || []).length}개`],
    ];
    document.getElementById('settings-grid').innerHTML = items.map(([label, value]) => `
        <div class="setting-item">
            <span class="label">${escapeHtml(label)}</span>
            <strong>${escapeHtml(value)}</strong>
        </div>
    `).join('');
}

function renderRisk(balance) {
    const total = Number(balance.total_eval || 0);
    const cash = Number(balance.cash || 0);
    const exposure = Math.max(0, total - cash);
    const cashRatio = total > 0 ? cash / total : 0;
    const maxPosition = Math.max(0, ...balance.holdings.map((holding) => Number(holding.value || 0)));
    const concentration = total > 0 ? maxPosition / total : 0;
    const pnl = Number(balance.pnl || 0);
    const capital = Number(latestConfig?.total_capital || total || 1);
    const lossUsage = pnl < 0 && latestConfig?.max_daily_loss_pct
        ? Math.min(999, Math.abs(pnl) / capital * 100 / latestConfig.max_daily_loss_pct * 100)
        : 0;

    document.getElementById('risk-exposure').textContent = formatCurrency(exposure);
    document.getElementById('risk-cash-ratio').textContent = `${formatNumber(cashRatio * 100, 1)}%`;
    document.getElementById('risk-concentration').textContent = `${formatNumber(concentration * 100, 1)}%`;
    document.getElementById('risk-loss-usage').textContent = lossUsage > 0 ? `${formatNumber(lossUsage, 1)}% 사용` : '정상';
}

async function renderBalance() {
    try {
        const balance = await fetchJson('/api/balance');

        document.getElementById('val-total').textContent = formatCurrency(balance.total_eval);
        document.getElementById('val-cash').textContent = formatCurrency(balance.cash);
        document.getElementById('val-holdings').textContent = balance.holdings.length;

        const pnlEl = document.getElementById('val-pnl');
        pnlEl.textContent = formatCurrency(balance.pnl);
        pnlEl.className = `value ${balance.pnl >= 0 ? 'text-success' : 'text-danger'}`;

        const tbodyHoldings = document.querySelector('#table-holdings tbody');
        tbodyHoldings.innerHTML = '';

        const chartLabels = ['현금'];
        const chartData = [balance.cash];
        const chartColors = ['rgba(148, 163, 184, 0.7)'];
        const colors = [
            'rgba(59, 130, 246, 0.7)',
            'rgba(16, 185, 129, 0.7)',
            'rgba(139, 92, 246, 0.7)',
            'rgba(245, 158, 11, 0.7)',
            'rgba(236, 72, 153, 0.7)',
            'rgba(14, 165, 233, 0.7)'
        ];

        if (!balance.holdings.length) {
            setTableMessage('#table-holdings tbody', 5, '보유 종목이 없습니다');
        }

        balance.holdings.forEach((holding, idx) => {
            const rtClass = holding.rt >= 0 ? 'text-success' : 'text-danger';
            const tr = document.createElement('tr');
            tr.innerHTML = `
                <td>
                    <div class="symbol-name">${escapeHtml(holding.name)}</div>
                    <div class="symbol-code">${escapeHtml(holding.symbol)}</div>
                </td>
                <td>${Number(holding.qty).toLocaleString()}</td>
                <td>${formatCurrency(holding.price)}</td>
                <td class="${rtClass}">${formatPercent(holding.rt)}</td>
                <td class="${rtClass}">${formatCurrency(holding.pnl)}</td>
            `;
            tbodyHoldings.appendChild(tr);

            chartLabels.push(holding.name || holding.symbol);
            chartData.push(holding.value || holding.qty * holding.price);
            chartColors.push(colors[idx % colors.length]);
        });

        renderPortfolioChart(chartLabels, chartData, chartColors);
        renderRisk(balance);
        document.getElementById('last-updated').textContent = `마지막 갱신 ${new Date().toLocaleTimeString('ko-KR')}`;
        if (balance._cache?.stale) {
            setStatus(`KIS 계좌 API가 일시 실패해 최근 정상 데이터(${balance._cache.cached_at || '저장됨'})를 표시합니다.`);
        } else {
            setStatus('대시보드 연결 완료. 계좌 정보를 불러왔습니다.', true);
        }
    } catch (err) {
        console.error('Failed to fetch balance data', err);
        document.getElementById('val-total').textContent = '불러오기 실패';
        document.getElementById('val-cash').textContent = '불러오기 실패';
        document.getElementById('val-pnl').textContent = '불러오기 실패';
        document.getElementById('val-holdings').textContent = '-';
        setStatus(`계좌 API 오류: ${err.message}`);
        setTableMessage('#table-holdings tbody', 5, err.message);
    }
}

async function renderOptimizer() {
    setButtonBusy('btn-optimizer', true);
    setTableMessage('#table-optimizer tbody', 7, '포트폴리오 최적 비중을 계산하고 있습니다...');
    try {
        const data = await fetchJson('/api/portfolio-optimizer');
        const tbody = document.querySelector('#table-optimizer tbody');
        tbody.innerHTML = '';
        if (!data.positions.length) {
            setTableMessage('#table-optimizer tbody', 7, '계산할 보유 종목이 없습니다');
            return;
        }

        data.positions.forEach((row) => {
            const action = String(row.rebalance_action || 'hold').toLowerCase();
            const kind = action === 'buy' ? 'buy' : (action === 'sell' ? 'sell' : 'hold');
            const reason = `포트폴리오 목표비중 ${formatNumber(row.target_weight * 100, 1)}%; 점수=${formatNumber(row.score, 1)}, 변동성=${formatNumber(row.volatility * 100, 1)}%`;
            const queueButton = action === 'hold'
                ? `<button type="button" class="button-ghost" disabled title="비중 유지 상태이므로 주문할 내역이 없습니다." style="opacity:0.3; cursor:not-allowed;">변경없음</button>`
                : `<button type="button" class="button-ghost queue-order"
                    data-symbol="${escapeHtml(row.symbol)}"
                    data-name="${escapeHtml(row.name)}"
                    data-action="${escapeHtml(action)}"
                    data-qty="${Number(row.rebalance_qty || 0)}"
                    data-price="${Number(row.price || 0)}"
                    data-reason="${escapeHtml(reason)}"
                    data-source="portfolio-optimizer">승인대기</button>`;
            const tr = document.createElement('tr');
            tr.innerHTML = `
                <td>
                    <div class="symbol-name">${escapeHtml(row.name)}</div>
                    <div class="symbol-code">${escapeHtml(row.symbol)}</div>
                </td>
                <td>${pill(formatNumber(row.score, 1), Number(row.score || 0) >= 3 ? 'buy' : 'hold')}</td>
                <td>${formatNumber(row.volatility * 100, 1)}%</td>
                <td>${formatNumber(row.current_weight * 100, 1)}%</td>
                <td>${formatNumber(row.target_weight * 100, 1)}%</td>
                <td>${pill(toKorAction(action), kind)}</td>
                <td>${queueButton}</td>
            `;
            tbody.appendChild(tr);
        });
        bindQueueButtons();
    } catch (err) {
        setTableMessage('#table-optimizer tbody', 7, err.message);
    } finally {
        setButtonBusy('btn-optimizer', false);
    }
}

async function renderSignals() {
    setButtonBusy('btn-signals', true);
    setTableMessage('#table-signals tbody', 7, '보유 종목을 진단하고 있습니다...');
    try {
        const data = await fetchJson('/api/signals');
        const tbody = document.querySelector('#table-signals tbody');
        tbody.innerHTML = '';
        if (!data.signals.length) {
            setTableMessage('#table-signals tbody', 7, '보유 종목이 없습니다');
            return;
        }

        data.signals.forEach((row) => {
            const action = String(row.action || 'hold').toLowerCase();
            const kind = action === 'buy' ? 'buy' : (action === 'sell' ? 'sell' : 'hold');
            const queueButton = action === 'hold'
                ? `<button type="button" class="button-ghost" disabled title="관망 신호이므로 주문할 내역이 없습니다." style="opacity:0.3; cursor:not-allowed;">보유(관망)</button>`
                : `<button type="button" class="button-ghost queue-order"
                    data-symbol="${escapeHtml(row.symbol)}"
                    data-name="${escapeHtml(row.name)}"
                    data-action="${escapeHtml(action)}"
                    data-qty="${Number(row.signal_qty || 0)}"
                    data-price="${Number(row.signal_price || 0)}"
                    data-reason="${escapeHtml(row.reason)}"
                    data-source="signal">승인대기</button>`;
            const reason = translateReason(row.reason);
            const tr = document.createElement('tr');
            tr.innerHTML = `
                <td>
                    <div class="symbol-name">${escapeHtml(row.name)}</div>
                    <div class="symbol-code">${escapeHtml(row.symbol)}</div>
                </td>
                <td>${pill(toKorAction(action), kind)}</td>
                <td>${pill(formatNumber(row.strategy_score), Number(row.strategy_score || 0) >= 5 ? 'buy' : 'hold')}</td>
                <td>${Number(row.signal_qty || 0).toLocaleString()}</td>
                <td>${formatNumber(row.rsi, 1)} / ${formatNumber(row.rsi2, 1)}</td>
                <td>${formatNumber(row.macd_hist, 2)}</td>
                <td>
                    <div class="reason-cell" title="${escapeHtml(reason)}">${escapeHtml(reason)}</div>
                    ${queueButton}
                </td>
            `;
            tbody.appendChild(tr);
        });
        bindQueueButtons();
    } catch (err) {
        setTableMessage('#table-signals tbody', 7, err.message);
    } finally {
        setButtonBusy('btn-signals', false);
    }
}

async function renderCandidates() {
    setButtonBusy('btn-candidates', true);
    setTableMessage('#table-candidates tbody', 8, '관심종목에서 매수 후보를 찾고 있습니다...');
    try {
        const data = await fetchJson('/api/candidates?min_score=2');
        const tbody = document.querySelector('#table-candidates tbody');
        tbody.innerHTML = '';
        if (!data.candidates.length) {
            const scanned = data.scanned || 0;
            const scanError = data.scan_error || null;
            const tableMsg = scanned === 0
                ? (scanError ? `데이터 수신 실패 — 잠시 후 다시 시도해 주세요` : '분석 대상 종목이 없습니다')
                : `조건을 만족한 후보가 없습니다 — ${scanned}종목 분석 완료`;
            setTableMessage('#table-candidates tbody', 8, tableMsg);
            // 분석 근거 팝업
            const titleEl = document.getElementById('noCandidatesTitle');
            const subtitleEl = document.getElementById('noCandidatesSubtitle');
            const bodyEl = document.getElementById('noCandidatesBody');
            if (scanned === 0 && scanError) {
                if (titleEl) titleEl.textContent = '⚠️ 데이터 수신 실패';
                if (subtitleEl) subtitleEl.textContent = '시세 데이터를 가져오지 못해 분석을 진행할 수 없었습니다.';
                if (bodyEl) bodyEl.innerHTML = buildScanErrorModalMarkup(scanError);
            } else {
                if (titleEl) titleEl.textContent = '📊 매수 후보 없음 — 분석 결과';
                if (subtitleEl) subtitleEl.textContent =
                    `${scanned}종목을 분석했으나 기준 점수(${data.min_score || 2}점) 이상인 종목이 없습니다.`;
                if (bodyEl) bodyEl.innerHTML = buildNoCandidatesModalMarkup(data);
            }
            setNoCandidatesModalOpen(true);
            if (data._cache?.cached_at) {
                setStatus(`최근 후보 검색 결과를 표시합니다. 기준 시각 ${data._cache.cached_at}`, true);
            } else {
                setStatus('분석 완료 — 매수 기준을 충족하는 종목이 없습니다.', true);
            }
            return;
        }

        const displayedCandidates = data.candidates.slice(0, 10);
        displayedCandidates.forEach((row) => {
            const stockName = row.name && row.name !== row.ticker ? row.name : '';
            const queueButton = Number(row.planned_qty || 0) > 0
                ? `<button type="button" class="button-ghost queue-order"
                    data-symbol="${escapeHtml(row.ticker)}"
                    data-name="${escapeHtml(row.name || row.ticker)}"
                    data-action="buy"
                    data-qty="${Number(row.planned_qty || 0)}"
                    data-price="${Number(row.limit_price || row.current_price || 0)}"
                    data-reason="${escapeHtml((row.reasons || []).join(', '))}"
                    data-source="candidate">승인대기</button>`
                : `<button type="button" class="button-ghost" disabled title="잔고 부족 또는 최대 보유 종목 수(MAX_POSITIONS) 초과로 매수할 수 없습니다." style="opacity:0.5; cursor:not-allowed;">승인불가</button>`;

            // 상세 근거 빌드
            const reasonLines = (row.reasons || []).map(r => strategyReasonLabel(r));
            const detailParts = [];
            if (row.rsi != null) detailParts.push(`RSI ${formatNumber(row.rsi,1)}`);
            if (row.rsi2 != null) detailParts.push(`RSI2 ${formatNumber(row.rsi2,1)}`);
            if (row.macd_hist != null) detailParts.push(`MACD ${formatNumber(row.macd_hist,2)}`);
            if (row.sma20 != null && row.sma60 != null) {
                const trend = row.sma20 > row.sma60 ? '단기↑중기선 위' : '단기↓중기선 아래';
                detailParts.push(trend);
            }
            if (row.bb_lo != null && row.current_price != null) {
                const bbDist = ((row.current_price - row.bb_lo) / row.bb_lo * 100).toFixed(1);
                detailParts.push(`볼밴하단+${bbDist}%`);
            }
            const detailSuffix = detailParts.length ? ` (${detailParts.join(' | ')})` : '';
            const reasonText = reasonLines.join(' · ') + detailSuffix;

            const tr = document.createElement('tr');
            tr.innerHTML = `
                <td>
                    <span class="symbol-name">${escapeHtml(stockName || row.ticker)}</span>
                    <span class="symbol-code">${stockName ? row.ticker : ''}</span>
                </td>
                <td>${pill(row.score, row.score >= 3 ? 'buy' : 'warn')}</td>
                <td>${formatNumber(row.rsi, 1)} / ${formatNumber(row.rsi2, 1)}</td>
                <td>${formatNumber(row.macd_hist, 2)}</td>
                <td>${formatCurrency(row.current_price)}</td>
                <td>${Number(row.planned_qty || 0).toLocaleString()}</td>
                <td>${formatCurrency(row.estimated_cost)}</td>
                <td>
                    <div class="reason-detail">${escapeHtml(reasonText)}</div>
                    ${queueButton}
                </td>
            `;
            tbody.appendChild(tr);
        });
        bindQueueButtons();
        if (data._cache?.cached_at) {
            setStatus(`최근 후보 검색 결과를 표시합니다. 기준 시각 ${data._cache.cached_at}`, true);
        } else {
            setStatus('매수 후보 검색을 완료했습니다.', true);
        }
    } catch (err) {
        setTableMessage('#table-candidates tbody', 8, err.message);
    } finally {
        setButtonBusy('btn-candidates', false);
    }
}

async function renderAiAllocation() {
    setButtonBusy('btn-ai-allocation', true);
    setTableMessage('#table-ai-allocation tbody', 8, 'AI 목표 비중을 계산하고 있습니다...');
    try {
        const data = await fetchJson('/api/ai-allocation');
        const tbody = document.querySelector('#table-ai-allocation tbody');
        tbody.innerHTML = '';
        if (!data.positions.length) {
            setTableMessage('#table-ai-allocation tbody', 8, '계산할 보유 종목이 없습니다');
            return;
        }

        data.positions.forEach((row) => {
            const action = String(row.rebalance_action || 'hold').toLowerCase();
            const kind = action === 'buy' ? 'buy' : (action === 'sell' ? 'sell' : 'hold');
            const reason = `AI 목표비중 ${formatNumber(row.target_weight * 100, 1)}%; ${translateReason(((row.reasons || []).slice(0, 3)).join(', '))}`;
            const modalPayload = encodeURIComponent(JSON.stringify({
                symbol: row.symbol,
                name: row.name,
                action,
                score: Number(row.score || 0),
                currentWeight: Number(row.current_weight || 0),
                targetWeight: Number(row.target_weight || 0),
                deltaValue: Number(row.delta_value || 0),
                volatility: Number(row.volatility || 0),
                reasoning_kr: row.reasoning_kr || '',
                ai_strategy_name: row.ai_strategy_name || 'AI 전략 상세',
                reasons: Array.isArray(row.reasons) ? row.reasons : []
            }));
            const queueButton = action === 'hold'
                ? `<button type="button" class="button-ghost" disabled title="AI가 현재 비중을 유지할 것을 권장합니다." style="opacity:0.3; cursor:not-allowed;">유지</button>`
                : `<button type="button" class="button-ghost queue-order"
                    data-symbol="${escapeHtml(row.symbol)}"
                    data-name="${escapeHtml(row.name)}"
                    data-action="${escapeHtml(action)}"
                    data-qty="${Number(row.rebalance_qty || 0)}"
                    data-price="${Number(row.price || 0)}"
                    data-reason="${escapeHtml(reason)}"
                    data-source="ai-allocation">승인대기</button>`;
            const tr = document.createElement('tr');
            const aiReasonText = String(row.reasoning_kr || row.reasons?.join(', ') || '-');
            tr.innerHTML = `
                <td>
                    <div class="symbol-name">${escapeHtml(row.name)}</div>
                    <div class="symbol-code">${escapeHtml(row.symbol)}</div>
                </td>
                <td>${pill(formatNumber(row.score, 2), Number(row.score || 0) > 0 ? 'buy' : 'hold')}</td>
                <td>${formatNumber(row.current_weight * 100, 1)}%</td>
                <td>${formatNumber(row.target_weight * 100, 1)}%</td>
                <td>${formatCurrency(row.delta_value)}</td>
                <td>${pill(toKorAction(action), kind)}</td>
                <td>
                    <button type="button" class="clickable-reason"
                        data-ai-payload="${modalPayload}"
                        data-reason="${escapeHtml(aiReasonText)}"
                        onclick="showAiModal(this)">
                        ${escapeHtml(row.ai_strategy_name || "전략 상세 내역 보기")}
                    </button>
                </td>
                <td>${queueButton}</td>
            `;
            tbody.appendChild(tr);
        });
        bindQueueButtons();
    } catch (err) {
        setTableMessage('#table-ai-allocation tbody', 8, err.message);
    } finally {
        setButtonBusy('btn-ai-allocation', false);
    }
}

async function createApprovalFromButton(button) {
    const payload = {
        symbol: button.dataset.symbol,
        name: button.dataset.name,
        action: button.dataset.action,
        qty: Number(button.dataset.qty || 0),
        price: Number(button.dataset.price || 0),
        reason: button.dataset.reason || '',
        source: button.dataset.source || 'dashboard'
    };
    button.disabled = true;
    try {
        await postJson('/api/approvals', payload);
        setStatus(`${toKorAction(payload.action)} ${payload.symbol} 주문을 승인 대기에 올렸습니다.`, true);
        await renderApprovals();
    } catch (err) {
        setStatus(`승인 대기 등록 실패: ${err.message}`);
        button.disabled = false;
    }
}

function bindQueueButtons() {
    document.querySelectorAll('.queue-order').forEach((button) => {
        button.addEventListener('click', () => createApprovalFromButton(button), { once: true });
    });
}

async function renderApprovals() {
    try {
        const data = await fetchJson('/api/approvals?limit=50');
        const tbody = document.querySelector('#table-approvals tbody');
        tbody.innerHTML = '';
        if (!data.approvals.length) {
            setTableMessage('#table-approvals tbody', 7, '승인 대기 주문이 없습니다');
            return;
        }

        data.approvals.forEach((row) => {
            const status = String(row.status || '');
            const statusKind = status === 'pending' ? 'warn' : (status === 'executed' ? 'buy' : (status === 'failed' ? 'sell' : 'hold'));
            const controls = status === 'pending'
                ? `<div class="button-row">
                    <button type="button" class="approve-order" data-id="${row.id}">승인</button>
                    <button type="button" class="button-danger reject-order" data-id="${row.id}">거절</button>
                   </div>`
                : `<span class="time-muted">${escapeHtml(row.response_msg || '')}</span>`;

            const tr = document.createElement('tr');
            tr.innerHTML = `
                <td>
                    <div>${escapeHtml(String(row.created_at || '').split(' ')[0])}</div>
                    <div class="time-muted">${escapeHtml(String(row.created_at || '').split(' ')[1] || '')}</div>
                </td>
                <td>${pill(toKorAction(row.action), row.action === 'buy' ? 'buy' : 'sell')}</td>
                <td>
                    <div class="symbol-name">${escapeHtml(row.name || row.symbol)}</div>
                    <div class="symbol-code">${escapeHtml(row.symbol)}</div>
                </td>
                <td>${Number(row.qty || 0).toLocaleString()}</td>
                <td>${formatCurrency(row.price)}</td>
                <td>${pill(toKorStatus(status), statusKind)}</td>
                <td>${controls}</td>
            `;
            tbody.appendChild(tr);
        });

        document.querySelectorAll('.approve-order').forEach((button) => {
            button.addEventListener('click', () => handleApprovalAction(button, 'approve'));
        });
        document.querySelectorAll('.reject-order').forEach((button) => {
            button.addEventListener('click', () => handleApprovalAction(button, 'reject'));
        });
    } catch (err) {
        setTableMessage('#table-approvals tbody', 7, err.message);
    }
}

async function handleApprovalAction(button, action) {
    button.disabled = true;
    try {
        const result = await postJson(`/api/approvals/${button.dataset.id}/${action}`, {});
        setStatus(`승인 처리 결과: ${toKorStatus(result.status)} #${result.id}`, result.status !== 'failed');
        await Promise.all([renderApprovals(), renderTrades(), renderBalance()]);
    } catch (err) {
        setStatus(`승인 처리 실패: ${err.message}`);
        button.disabled = false;
    }
}

async function renderTrades() {
    try {
        // 성과 요약 (Performance)
        try {
            const perf = await fetchJson('/api/performance');
            document.getElementById('perf-total-trades').textContent = `${perf.total_trades}회`;
            document.getElementById('perf-success-rate').textContent = `${perf.success_rate}%`;
            
            const pnlEl = document.getElementById('perf-realized-pnl');
            pnlEl.textContent = formatCurrency(perf.realized_pnl);
            pnlEl.className = perf.realized_pnl > 0 ? 'text-success' : (perf.realized_pnl < 0 ? 'text-danger' : '');
            
            const evalPnlEl = document.getElementById('perf-eval-pnl');
            if (evalPnlEl) {
                const evalPnl = perf.total_eval_pnl || 0;
                evalPnlEl.textContent = formatCurrency(evalPnl);
                evalPnlEl.className = evalPnl > 0 ? 'text-success' : (evalPnl < 0 ? 'text-danger' : '');
            }
            
            const tbodyEval = document.querySelector('#table-eval-details tbody');
            if (tbodyEval) {
                tbodyEval.innerHTML = '';
                const details = perf.eval_details || [];
                if (!details.length) {
                    setTableMessage('#table-eval-details tbody', 6, '자동매매로 매수한 보유종목이 없습니다.');
                } else {
                    details.forEach((item) => {
                        const tr = document.createElement('tr');
                        const pnlClass = item.eval_pnl > 0 ? 'text-success' : (item.eval_pnl < 0 ? 'text-danger' : '');
                        tr.innerHTML = `
                            <td>
                                <span class="symbol-name">${escapeHtml(item.name || item.symbol)}</span>
                                ${item.diff_reason ? `<div style="font-size: 0.75rem; color: #ffc107; margin-top: 2px;">⚠️ ${escapeHtml(item.diff_reason)}</div>` : ''}
                            </td>
                            <td>${Number(item.qty || 0).toLocaleString()}</td>
                            <td>${formatCurrency(item.avg_cost)}</td>
                            <td>${formatCurrency(item.current_price)}</td>
                            <td class="${pnlClass}">${item.return_rate > 0 ? '+' : ''}${item.return_rate.toFixed(2)}%</td>
                            <td class="${pnlClass}">${item.eval_pnl > 0 ? '+' : ''}${formatCurrency(item.eval_pnl)}</td>
                        `;
                        tbodyEval.appendChild(tr);
                    });
                }
            }

            const diffContainer = document.getElementById('pnl-diff-container');
            const diffList = document.getElementById('pnl-diff-list');
            const brokerPnlSpan = document.getElementById('perf-broker-pnl');
            
            if (diffContainer && diffList && brokerPnlSpan && typeof perf.total_broker_pnl !== 'undefined') {
                const autoPnl = perf.total_eval_pnl || 0;
                const brokerPnl = perf.total_broker_pnl || 0;
                
                if (autoPnl !== brokerPnl) {
                    diffContainer.hidden = false;
                    brokerPnlSpan.textContent = formatCurrency(brokerPnl);
                    
                    let diffHtml = '';
                    const details = perf.eval_details || [];
                    details.forEach(item => {
                        if (item.diff_reason) {
                            const diffAmt = (item.broker_pnl || 0) - (item.eval_pnl || 0);
                            const sign = diffAmt > 0 ? '+' : '';
                            diffHtml += `<li><strong>${escapeHtml(item.name)}</strong>: ${escapeHtml(item.diff_reason)} (평가손익 차액: ${sign}${formatCurrency(diffAmt)})</li>`;
                        }
                    });
                    
                    const untracked = perf.untracked_details || [];
                    untracked.forEach(item => {
                        const sign = item.broker_pnl > 0 ? '+' : '';
                        diffHtml += `<li><strong>${escapeHtml(item.name)}</strong>: ${escapeHtml(item.diff_reason)} (증권사 평가손익 전체 합산: ${sign}${formatCurrency(item.broker_pnl)})</li>`;
                    });
                    
                    diffList.innerHTML = diffHtml || '<li>차이 원인을 분석할 수 없는 오차가 있습니다. (API 지연 등)</li>';
                } else {
                    diffContainer.hidden = true;
                }
            }
        } catch (e) {
            console.error('Failed to fetch performance summary', e);
        }

        const trades = await fetchJson('/api/trades?limit=20');
        const tbodyTrades = document.querySelector('#table-trades tbody');
        tbodyTrades.innerHTML = '';

        if (!trades.trades.length) {
            setTableMessage('#table-trades tbody', 6, '주문 기록이 없습니다');
        }

        trades.trades.forEach((trade) => {
            const action = String(trade.action || '').toLowerCase();
            const badge = action === 'buy'
                ? '<span class="badge badge-buy">매수</span>'
                : '<span class="badge badge-sell">매도</span>';
            const [datePart = '-', timePart = '-'] = String(trade.ts || '').split(' ');
            const reason = escapeHtml(translateReason(trade.reason || '-'));

            const tr = document.createElement('tr');
            tr.innerHTML = `
                <td>
                    <div>${escapeHtml(datePart)}</div>
                    <div class="time-muted">${escapeHtml(timePart.substring(0, 5))}</div>
                </td>
                <td>${badge}</td>
                <td><span class="symbol-name">${escapeHtml(trade.name || trade.symbol)}</span></td>
                <td>${formatCurrency(trade.price)}</td>
                <td>${Number(trade.qty || 0).toLocaleString()}</td>
                <td><div class="reason-cell" title="${reason}">${reason}</div></td>
            `;
            tbodyTrades.appendChild(tr);
        });
    } catch (err) {
        console.error('Failed to fetch trade history', err);
        setTableMessage('#table-trades tbody', 6, err.message);
    }
}

async function fetchDashboardData() {
    await Promise.all([renderRuntime(), renderConfig(), renderBalance(), renderTrades(), renderApprovals()]);
}
document.getElementById('btn-reset-circuit').addEventListener('click', resetCircuitBreaker);
document.getElementById('btn-signals').addEventListener('click', renderSignals);

const btnSyncTrades = document.getElementById('btn-sync-trades');
if (btnSyncTrades) {
    btnSyncTrades.addEventListener('click', async () => {
        btnSyncTrades.disabled = true;
        btnSyncTrades.textContent = '동기화 중...';
        btnSyncTrades.style.backgroundColor = '#f59e0b'; // warning yellow
        btnSyncTrades.style.color = 'white';
        try {
            const result = await postJson('/api/trades/sync', {});
            setStatus(`증권사 기록 동기화 완료 (누락된 ${result.synced_count}건 추가됨)`, true);
            await renderTrades();
            
            btnSyncTrades.textContent = result.synced_count > 0 ? `동기화 완료 (${result.synced_count}건)` : '동기화 완료 ✔️';
            btnSyncTrades.style.backgroundColor = '#10b981'; // success green
            btnSyncTrades.style.color = 'white';
            
            setTimeout(() => {
                btnSyncTrades.disabled = false;
                btnSyncTrades.textContent = '증권사 기록 동기화';
                btnSyncTrades.style.backgroundColor = '';
                btnSyncTrades.style.color = '';
            }, 3000);
            
        } catch (err) {
            setStatus(`동기화 실패: ${err.message}`);
            btnSyncTrades.textContent = '동기화 실패';
            btnSyncTrades.style.backgroundColor = '#ef4444'; // error red
            btnSyncTrades.style.color = 'white';
            
            setTimeout(() => {
                btnSyncTrades.disabled = false;
                btnSyncTrades.textContent = '증권사 기록 동기화';
                btnSyncTrades.style.backgroundColor = '';
                btnSyncTrades.style.color = '';
            }, 3000);
        }
    });
}

window.showAiModal = function(element) {
    const payloadText = element.getAttribute('data-ai-payload');
    const titleEl = document.getElementById('aiModalTitle');
    const subtitleEl = document.getElementById('aiModalSubtitle');
    const bodyEl = document.getElementById('aiModalBody');

    if (!titleEl || !bodyEl) {
        return;
    }

    if (payloadText) {
        try {
            const payload = JSON.parse(decodeURIComponent(payloadText));
            titleEl.textContent = `${payload.name || payload.symbol || 'AI 전략'} 상세 근거`;
            if (subtitleEl) {
                subtitleEl.textContent = payload.ai_strategy_name || '';
            }
            bodyEl.innerHTML = buildAiModalMarkup(payload);
        } catch (_err) {
            const reasonText = element.getAttribute('data-reason') || '-';
            titleEl.textContent = 'AI 전략 상세 근거';
            if (subtitleEl) {
                subtitleEl.textContent = '';
            }
            bodyEl.textContent = reasonText;
        }
    } else {
        const reasonText = element.getAttribute('data-reason') || '-';
        titleEl.textContent = 'AI 전략 상세 근거';
        if (subtitleEl) {
            subtitleEl.textContent = '';
        }
        bodyEl.textContent = reasonText;
    }
    setAiModalOpen(true);
};

window.addEventListener('load', () => {
    const aiModal = document.getElementById('aiModal');
    const ncModal = document.getElementById('noCandidatesModal');

    // 닫기 버튼 — 모든 .close-modal 버튼을 각 모달 컨텍스트로 연결
    document.querySelectorAll('.close-modal').forEach(btn => {
        btn.addEventListener('click', () => {
            setAiModalOpen(false);
            setNoCandidatesModalOpen(false);
        });
    });

    window.addEventListener('click', (event) => {
        if (event.target === aiModal) setAiModalOpen(false);
        if (event.target === ncModal) setNoCandidatesModalOpen(false);
    });

    window.addEventListener('keydown', (event) => {
        if (event.key === 'Escape') {
            setAiModalOpen(false);
            setNoCandidatesModalOpen(false);
        }
    });
});
document.getElementById('btn-candidates').addEventListener('click', renderCandidates);
document.getElementById('btn-approvals').addEventListener('click', renderApprovals);
document.getElementById('btn-ai-allocation').addEventListener('click', renderAiAllocation);
document.getElementById('btn-optimizer').addEventListener('click', renderOptimizer);
setTableMessage('#table-signals tbody', 7, '진단하기를 누르면 보유 종목 신호를 확인합니다');
setTableMessage('#table-candidates tbody', 8, '찾기를 누르면 관심종목에서 매수 후보를 검색합니다');
setTableMessage('#table-approvals tbody', 7, '승인 대기 주문이 없습니다');
setTableMessage('#table-ai-allocation tbody', 8, '계산을 누르면 AI 목표 비중을 확인합니다');
setTableMessage('#table-optimizer tbody', 7, '최적화를 누르면 리스크 기반 목표 비중을 확인합니다');
fetchDashboardData();
setInterval(() => Promise.all([renderRuntime(), renderBalance(), renderTrades(), renderApprovals()]), 30000);
