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
    buy: '留ㅼ닔',
    sell: '留ㅻ룄',
    hold: '蹂댁쑀',
};

const STATUS_LABELS = {
    pending: '?뱀씤?湲?,
    executed: '泥섎━?꾨즺',
    failed: '?ㅽ뙣',
    rejected: '嫄곗젅',
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
        ['stop loss', '?먯젅 湲곗? ?꾨떖'],
        ['take profit', '?듭젅 湲곗? ?꾨떖'],
        ['large profit split sell', '???섏씡 遺꾪븷留ㅻ룄'],
        ['MACD bearish take profit', 'MACD ?쎌꽭 ?듭젅'],
        ['split buy', '遺꾪븷留ㅼ닔'],
        ['multi-strategy buy', '蹂듯빀 ?꾨왂 留ㅼ닔'],
        ['golden cross buy', '怨⑤뱺?щ줈??留ㅼ닔'],
        ['AI allocation target', 'AI 紐⑺몴鍮꾩쨷'],
        ['Portfolio optimizer target', '?ы듃?대━??紐⑺몴鍮꾩쨷'],
    ];
    let text = String(value || '-');
    replacements.forEach(([from, to]) => {
        text = text.replaceAll(from, to);
    });
    text = text.replace(/\bscore\b/g, '?먯닔');
    text = text.replace(/\bvol\b/g, '蹂?숈꽦');
    return text;
};

const strategyReasonLabel = (reason) => {
    const text = String(reason || '').trim();
    if (!text) {
        return '?곗씠??遺議?;
    }

    const mappings = [
        ['RSI recovery', '怨쇰ℓ??援ш컙?먯꽌 諛섎벑 ?좏샇媛 ?뺤씤?먯뒿?덈떎.'],
        ['RSI pullback', '?④린 議곗젙 ???ъ쭊?낆쓣 寃?좏븷 ???덈뒗 援ш컙?낅땲??'],
        ['MACD bullish cross', 'MACD 怨⑤뱺?щ줈?ㅺ? ?섏? ?곸듅 ?꾪솚 媛?μ꽦???덉뒿?덈떎.'],
        ['MACD positive', 'MACD ?먮쫫???뚮윭?ㅻ씪 ?④린 紐⑤찘????좎??섍퀬 ?덉뒿?덈떎.'],
        ['Bollinger rebound', '蹂쇰┛? ?섎떒 諛섎벑???섏? 湲곗닠???섎룎由?媛?μ꽦???덉뒿?덈떎.'],
        ['near lower band', '二쇨?媛 蹂쇰┛? ?섎떒 遺洹쇱씠??諛섎벑 愿李?援ш컙?낅땲??'],
        ['trend pullback', '?곸듅 異붿꽭 ?덉뿉???뚮┝紐⑹씠 ?섏삩 紐⑥뒿?낅땲??'],
        ['long trend pullback', '以묎린 ?곸듅 異붿꽭 ?덉뿉??議곗젙??吏꾪뻾 以묒엯?덈떎.'],
        ['20-day breakout with volume', '嫄곕옒?됱쓣 ?숇컲??20???뚰뙆媛 ?섏솕?듬땲??'],
        ['volume spike', '嫄곕옒?됱씠 ?됱냼蹂대떎 媛뺥븯寃?利앷??덉뒿?덈떎.'],
        ['SMA20>SMA60', '?④린 ?대룞?됯퇏??以묎린???꾩뿉 ?덉뼱 異붿꽭媛 ?고샇?곸엯?덈떎.']
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
        return `${name} 鍮꾩쨷??議곌툑 ???ㅼ뼱???쒕떎???먮떒?낅땲??`;
    }
    if (action === 'sell') {
        return `${name} 鍮꾩쨷???꾩옱 議곌굔 ?鍮??ㅼ냼 ?щ?濡?以꾩씠???몄씠 ?ル떎???먮떒?낅땲??`;
    }
    return `${name}? 吏湲덉? 鍮꾩쨷???ш쾶 諛붽씀吏 ?딄퀬 ?좎??섎뒗 ?몄씠 ?ル떎???먮떒?낅땲??`;
};

const aiDecisionLabel = (action) => {
    if (action === 'buy') {
        return '鍮꾩쨷 ?뺣?';
    }
    if (action === 'sell') {
        return '鍮꾩쨷 異뺤냼';
    }
    return '鍮꾩쨷 ?좎?';
};

function buildAiModalMarkup(payload) {
    const reasons = Array.isArray(payload.reasons) ? payload.reasons : [];
    const summary = payload.reasoning_kr || aiActionGuide(payload.action, payload.name);
    const reasonItems = reasons.length
        ? reasons.map((reason) => `<li>${escapeHtml(strategyReasonLabel(reason))}</li>`).join('')
        : '<li>?쒕졆??湲곗닠???좏샇媛 異⑸텇?섏? ?딆븘 蹂댁닔?곸쑝濡??먮떒?덉뒿?덈떎.</li>';

    const signalItems = [
        `AI ?먯닔??<strong>${escapeHtml(formatNumber(payload.score, 2))}</strong>?먯엯?덈떎.`,
        `?꾩옱 鍮꾩쨷? <strong>${escapeHtml(formatNumber(payload.currentWeight * 100, 1))}%</strong>, 紐⑺몴 鍮꾩쨷? <strong>${escapeHtml(formatNumber(payload.targetWeight * 100, 1))}%</strong>?낅땲??`,
        `李⑥씠 湲덉븸? <strong>${escapeHtml(formatCurrency(payload.deltaValue))}</strong>?대ŉ, ?ㅽ뻾 ?≪뀡? <strong>${escapeHtml(aiDecisionLabel(payload.action))}</strong>?낅땲??`,
        `理쒓렐 蹂?숈꽦? <strong>${escapeHtml(formatNumber(payload.volatility * 100, 1))}%</strong>濡?怨꾩궛?섏뿀?듬땲??`
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
            <h3>?쒕늿??蹂닿린</h3>
            <ul class="ai-modal-list">${signalItems}</ul>
        </div>
        <div class="ai-modal-section">
            <h3>???대윴 ?먮떒???섏솕??/h3>
            <ul class="ai-modal-list">${reasonItems}</ul>
            ${rawReasons}
        </div>
        <div class="ai-modal-section">
            <h3>?쎈뒗 踰?/h3>
            <p class="ai-modal-footnote">
                紐⑺몴 鍮꾩쨷? ?쒖씠 醫낅ぉ???꾩껜 ?먯궛?먯꽌 ?대뒓 ?뺣룄源뚯? 媛?멸?硫?醫뗭?吏?앸? ?삵빀?덈떎.
                ?꾩옱 鍮꾩쨷蹂대떎 紐⑺몴 鍮꾩쨷???믪쑝硫?留ㅼ닔 履? ??쑝硫?異뺤냼 履쎌쑝濡??댁꽍?섎㈃ ?⑸땲??
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
        throw new Error(data.detail || `?붿껌 ?ㅽ뙣: ${response.status}`);
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
        throw new Error(data.detail || `?붿껌 ?ㅽ뙣: ${response.status}`);
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
            <h3>?ㅻ쪟 ?댁슜</h3>
            <p class="ai-modal-footnote">${escapeHtml(errorMsg)}</p>
        </div>
        <div class="ai-modal-section">
            <h3>?대젃寃??대낫?몄슂</h3>
            <ul class="ai-modal-list">
                <li>?좎떆 ???ㅼ떆 <strong>李얘린</strong> 踰꾪듉???뚮윭蹂댁꽭??</li>
                <li>?명꽣???곌껐 ?곹깭瑜??뺤씤?섏꽭??</li>
                <li>???쒓컙 以?09:00~15:30)?먮뒗 ?곗씠?곌? ???덉젙?곸쑝濡??섏떊?⑸땲??</li>
                <li>臾몄젣媛 怨꾩냽?섎㈃ YFINANCE_TIMEOUT_SECONDS ?섍꼍蹂?섎? ?섎젮蹂댁꽭??(湲곕낯媛? 8珥?.</li>
            </ul>
        </div>
    `;
}

function buildNoCandidatesModalMarkup(data) {
    const summary = data.scan_summary || [];
    const minScore = data.min_score || 2;
    const scanned = data.scanned || summary.length;

    // ?먯닔 遺꾪룷
    const scoreGroups = { 0: 0, 1: 0 };
    summary.forEach(item => {
        const s = item.score || 0;
        scoreGroups[s] = (scoreGroups[s] || 0) + 1;
    });

    // 媛???믪? ?먯닔 醫낅ぉ??(?곸쐞 8媛?
    const top = summary.slice(0, 8);

    const scoreDistItems = Object.entries(scoreGroups)
        .sort((a, b) => Number(b[0]) - Number(a[0]))
        .map(([score, count]) => `<li><strong>${score}??/strong>: ${count}醫낅ぉ</li>`)
        .join('');

    // ?쒓렇??吏묎퀎: ?대뼡 ?좏샇媛 媛??留롮씠 諛쒖깮?덈굹
    const signalCount = {};
    summary.forEach(item => {
        (item.reasons || []).forEach(r => {
            signalCount[r] = (signalCount[r] || 0) + 1;
        });
    });
    const topSignals = Object.entries(signalCount)
        .sort((a, b) => b[1] - a[1])
        .slice(0, 4)
        .map(([r, cnt]) => `<li>${escapeHtml(strategyReasonLabel(r))} <span class="muted">(${cnt}醫낅ぉ)</span></li>`)
        .join('');

    const topRows = top.map(item => {
        const scoreClass = item.score >= minScore ? 'buy' : (item.score > 0 ? 'warn' : 'sell');
        const reasonText = (item.reasons || []).map(r => strategyReasonLabel(r)).join(', ') || '?좏샇 ?놁쓬';
        const gap = minScore - item.score;
        const gapText = gap > 0 ? `<span class="muted">(${gap}??遺議?</span>` : '<span class="pill pill-buy">?듦낵</span>';
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
        ? '?곗씠?곕? ?섏떊?섏? 紐삵뻽?듬땲??'
        : summary.every(i => i.score === 0)
            ? '遺꾩꽍??紐⑤뱺 醫낅ぉ?먯꽌 留ㅼ닔 ?좏샇媛 ?섎굹??諛쒖깮?섏? ?딆븯?듬땲?? ?쒖옣 ?꾨컲??愿留?援?㈃??媛?μ꽦???믪뒿?덈떎.'
            : `?쇰? 醫낅ぉ?먯꽌 ?쏀븳 ?좏샇(${Math.max(...summary.map(i=>i.score))}??媛 ?덉쑝??湲곗?(${minScore}????誘몄튂吏 紐삵빀?덈떎. ?쒖옣 紐⑤찘????꾩쭅 異⑸텇???뺤꽦?섏? ?딆? ?곹깭?낅땲??`;

    return `
        <div class="ai-modal-section">
            <h3>?ㅼ틪 ?붿빟</h3>
            <ul class="ai-modal-list">
                <li>遺꾩꽍 醫낅ぉ ?? <strong>${scanned}醫낅ぉ</strong></li>
                <li>留ㅼ닔 湲곗? ?먯닔: <strong>${minScore}???댁긽</strong></li>
                <li>留ㅼ닔 ?꾨낫: <strong>0醫낅ぉ</strong></li>
            </ul>
        </div>
        <div class="ai-modal-section">
            <h3>?쒖옣 ?먮떒</h3>
            <p class="ai-modal-footnote">${escapeHtml(marketMood)}</p>
        </div>
        ${topSignals ? `
        <div class="ai-modal-section">
            <h3>媛먯???遺遺??좏샇 (湲곗? 誘몃떖)</h3>
            <ul class="ai-modal-list">${topSignals}</ul>
        </div>` : ''}
        <div class="ai-modal-section">
            <h3>?먯닔蹂?醫낅ぉ 遺꾪룷</h3>
            <ul class="ai-modal-list">${scoreDistItems || '<li>遺꾩꽍 ?곗씠???놁쓬</li>'}</ul>
        </div>
        ${topRows ? `
        <div class="ai-modal-section">
            <h3>?곸쐞 ?ㅼ퐫??醫낅ぉ ?곸꽭</h3>
            <div class="table-responsive">
                <table>
                    <thead><tr><th>醫낅ぉ</th><th>?먯닔</th><th>RSI</th><th>MACD</th><th>媛먯? ?좏샇</th></tr></thead>
                    <tbody>${topRows}</tbody>
                </table>
            </div>
        </div>` : ''}
        <div class="ai-modal-section">
            <h3>?대젃寃??대낫?몄슂</h3>
            <ul class="ai-modal-list">
                <li>?좎떆 ???ㅼ떆 寃?됲븯嫄곕굹, ???쒖옉 吏곹썑/留덇컧 1?쒓컙 ?꾩뿉 ?쒕룄?대낫?몄슂.</li>
                <li>理쒖냼 ?먯닔瑜?1?먯쑝濡???텛硫???留롮? ?꾨낫瑜?蹂????덉뒿?덈떎.</li>
                <li>?쒖옣 ?꾨컲???섎씫 援?㈃?대씪硫??꾧툑 鍮꾩쨷???좎??섎뒗 寃껋씠 ?좊━?⑸땲??</li>
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
    document.getElementById('runtime-env').textContent = health.trading_env === 'real' ? '?ㅼ쟾' : '紐⑥쓽';
    document.getElementById('runtime-dry-run').innerHTML = health.dry_run ? pill('二쇰Ц李⑤떒', 'warn') : pill('?꾩넚?덉슜', 'buy');
    document.getElementById('runtime-order').innerHTML = health.order_submission_enabled ? pill('API ?꾩넚 媛??, 'buy') : pill('API ?꾩넚 李⑤떒', 'warn');
    document.getElementById('runtime-real').innerHTML = health.real_orders_enabled ? pill('?ㅼ＜臾?媛??, 'sell') : pill('?ㅼ＜臾?李⑤떒', 'hold');
    document.getElementById('runtime-circuit').innerHTML = circuit.opened
        ? pill(`李⑤떒 ${circuit.retry_after_seconds || 0}珥?, 'sell')
        : pill(`?뺤긽 ${circuit.error_count || 0}/${circuit.max_errors || 5}`, 'buy');
        
    const btnSyncTrades = document.getElementById('btn-sync-trades');
    if (btnSyncTrades) {
        if (health.dry_run) {
            btnSyncTrades.disabled = true;
            btnSyncTrades.textContent = '?숆린??遺덇? (紐⑥쓽 ?ㅽ뻾)';
            btnSyncTrades.title = '紐⑥쓽 ?ㅽ뻾(DRY_RUN) 以묒뿉??利앷텒???ㅺ퀎醫뚯? ?숆린?뷀븷 ???놁뒿?덈떎.';
        } else {
            btnSyncTrades.disabled = false;
            btnSyncTrades.textContent = '利앷텒??湲곕줉 ?숆린??;
            btnSyncTrades.title = '';
        }
    }
}

async function resetCircuitBreaker() {
    setButtonBusy('btn-reset-circuit', true);
    try {
        await postJson('/api/circuit-breaker/reset', {});
        setStatus('API 李⑤떒湲곕? 珥덇린?뷀뻽?듬땲?? 怨꾩쥖 ?뺣낫瑜??ㅼ떆 遺덈윭?듬땲??', true);
        await Promise.all([renderRuntime(), renderBalance()]);
    } catch (err) {
        setStatus(`API 李⑤떒湲?珥덇린???ㅽ뙣: ${err.message}`);
    } finally {
        setButtonBusy('btn-reset-circuit', false);
    }
}

async function renderConfig() {
    const config = await fetchJson('/api/config');
    latestConfig = config;
    const items = [
        ['遺꾪븷 ?잛닔', `${config.split_n}??],
        ['?먯젅 湲곗?', `${config.stop_loss_pct}%`],
        ['?듭젅 湲곗?', `${config.take_profit}%`],
        ['RSI 留ㅼ닔??, config.rsi_buy],
        ['RSI 留ㅻ룄??, config.rsi_sell],
        ['湲곗? ?먮낯', formatCurrency(config.total_capital)],
        ['理쒕? 蹂댁쑀醫낅ぉ', `${config.max_positions}媛?],
        ['醫낅ぉ??理쒕?鍮꾩쨷', `${formatNumber(config.max_single_weight * 100, 1)}%`],
        ['?꾧툑 蹂댁쑀鍮꾩쨷', `${formatNumber(config.cash_buffer * 100, 1)}%`],
        ['???먯떎 ?쒗븳', `${config.max_daily_loss_pct}%`],
        ['愿?ъ쥌紐?, `${config.watchlist.length}媛?],
        ['?꾨왂 臾띠쓬', `${(config.strategy_sources || []).length}媛?],
    ];
    document.getElementById('settings-grid').innerHTML = items.map(([label, value]) => `
        <div class="setting-item">
            <span class="label">${escapeHtml(label)}</span>
            <strong>${escapeHtml(value)}</strong>
        </div>
    `).join('');
}

function renderRisk(balance) {
    const holdingValue = (balance.holdings || []).reduce((sum, holding) => {
        return sum + Number(holding.value || (Number(holding.qty || 0) * Number(holding.price || 0)));
    }, 0);
    const reportedTotal = Number(balance.total_eval || 0);
    const cash = Number(balance.cash || 0);
    const exposure = Number(balance.stock_eval || holdingValue || 0);
    const total = exposure > 0 && reportedTotal < Math.max(cash, exposure)
        ? cash + exposure
        : reportedTotal;
    const cashRatio = typeof balance.cash_ratio === 'number'
        ? balance.cash_ratio
        : (total > 0 ? Math.min(1, Math.max(0, cash / total)) : 0);
    const maxPosition = Math.max(0, ...balance.holdings.map((holding) => Number(holding.value || 0)));
    const concentration = total > 0 ? Math.min(1, Math.max(0, maxPosition / total)) : 0;
    const pnl = Number(balance.pnl || 0);
    const capital = Number(latestConfig?.total_capital || total || 1);
    const lossUsage = pnl < 0 && latestConfig?.max_daily_loss_pct
        ? Math.min(999, Math.abs(pnl) / capital * 100 / latestConfig.max_daily_loss_pct * 100)
        : 0;

    document.getElementById('risk-exposure').textContent = formatCurrency(exposure);
    document.getElementById('risk-cash-ratio').textContent = `${formatNumber(cashRatio * 100, 1)}%`;
    document.getElementById('risk-concentration').textContent = `${formatNumber(concentration * 100, 1)}%`;
    document.getElementById('risk-loss-usage').textContent = lossUsage > 0 ? `${formatNumber(lossUsage, 1)}% ?ъ슜` : '?뺤긽';
}

async function renderBalance() {
    try {
        const balance = await fetchJson('/api/balance');
        const holdingValue = (balance.holdings || []).reduce((sum, holding) => {
            return sum + Number(holding.value || (Number(holding.qty || 0) * Number(holding.price || 0)));
        }, 0);
        const displayTotal = holdingValue > 0 && Number(balance.total_eval || 0) < Math.max(Number(balance.cash || 0), holdingValue)
            ? Number(balance.cash || 0) + holdingValue
            : Number(balance.total_eval || 0);

        document.getElementById('val-total').textContent = formatCurrency(displayTotal);
        document.getElementById('val-cash').textContent = formatCurrency(balance.cash);
        document.getElementById('val-holdings').textContent = balance.holdings.length;

        const pnlEl = document.getElementById('val-pnl');
        pnlEl.textContent = formatCurrency(balance.pnl);
        pnlEl.className = `value ${balance.pnl >= 0 ? 'text-success' : 'text-danger'}`;

        const tbodyHoldings = document.querySelector('#table-holdings tbody');
        tbodyHoldings.innerHTML = '';

        const chartLabels = ['?꾧툑'];
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
            setTableMessage('#table-holdings tbody', 5, '蹂댁쑀 醫낅ぉ???놁뒿?덈떎');
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
        document.getElementById('last-updated').textContent = `留덉?留?媛깆떊 ${new Date().toLocaleTimeString('ko-KR')}`;
        if (balance._cache?.stale) {
            setStatus(`KIS 怨꾩쥖 API媛 ?쇱떆 ?ㅽ뙣??理쒓렐 ?뺤긽 ?곗씠??${balance._cache.cached_at || '??λ맖'})瑜??쒖떆?⑸땲??`);
        } else {
            setStatus('??쒕낫???곌껐 ?꾨즺. 怨꾩쥖 ?뺣낫瑜?遺덈윭?붿뒿?덈떎.', true);
        }
    } catch (err) {
        console.error('Failed to fetch balance data', err);
        document.getElementById('val-total').textContent = '遺덈윭?ㅺ린 ?ㅽ뙣';
        document.getElementById('val-cash').textContent = '遺덈윭?ㅺ린 ?ㅽ뙣';
        document.getElementById('val-pnl').textContent = '遺덈윭?ㅺ린 ?ㅽ뙣';
        document.getElementById('val-holdings').textContent = '-';
        setStatus(`怨꾩쥖 API ?ㅻ쪟: ${err.message}`);
        setTableMessage('#table-holdings tbody', 5, err.message);
    }
}

async function renderOptimizer() {
    setButtonBusy('btn-optimizer', true);
    setTableMessage('#table-optimizer tbody', 7, '?ы듃?대━??理쒖쟻 鍮꾩쨷??怨꾩궛?섍퀬 ?덉뒿?덈떎...');
    try {
        const data = await fetchJson('/api/portfolio-optimizer');
        const tbody = document.querySelector('#table-optimizer tbody');
        tbody.innerHTML = '';
        if (!data.positions.length) {
            setTableMessage('#table-optimizer tbody', 7, '怨꾩궛??蹂댁쑀 醫낅ぉ???놁뒿?덈떎');
            return;
        }

        data.positions.forEach((row) => {
            const action = String(row.rebalance_action || 'hold').toLowerCase();
            const kind = action === 'buy' ? 'buy' : (action === 'sell' ? 'sell' : 'hold');
            const reason = `?ы듃?대━??紐⑺몴鍮꾩쨷 ${formatNumber(row.target_weight * 100, 1)}%; ?먯닔=${formatNumber(row.score, 1)}, 蹂?숈꽦=${formatNumber(row.volatility * 100, 1)}%`;
            const queueButton = action === 'hold'
                ? `<button type="button" class="button-ghost" disabled title="鍮꾩쨷 ?좎? ?곹깭?대?濡?二쇰Ц???댁뿭???놁뒿?덈떎." style="opacity:0.3; cursor:not-allowed;">蹂寃쎌뾾??/button>`
                : `<button type="button" class="button-ghost queue-order"
                    data-symbol="${escapeHtml(row.symbol)}"
                    data-name="${escapeHtml(row.name)}"
                    data-action="${escapeHtml(action)}"
                    data-qty="${Number(row.rebalance_qty || 0)}"
                    data-price="${Number(row.price || 0)}"
                    data-reason="${escapeHtml(reason)}"
                    data-source="portfolio-optimizer">?뱀씤?湲?/button>`;
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
    setTableMessage('#table-signals tbody', 7, '蹂댁쑀 醫낅ぉ??吏꾨떒?섍퀬 ?덉뒿?덈떎...');
    try {
        const data = await fetchJson('/api/signals');
        const tbody = document.querySelector('#table-signals tbody');
        tbody.innerHTML = '';
        if (!data.signals.length) {
            setTableMessage('#table-signals tbody', 7, '蹂댁쑀 醫낅ぉ???놁뒿?덈떎');
            return;
        }

        data.signals.forEach((row) => {
            const action = String(row.action || 'hold').toLowerCase();
            const kind = action === 'buy' ? 'buy' : (action === 'sell' ? 'sell' : 'hold');
            const queueButton = action === 'hold'
                ? `<button type="button" class="button-ghost" disabled title="愿留??좏샇?대?濡?二쇰Ц???댁뿭???놁뒿?덈떎." style="opacity:0.3; cursor:not-allowed;">蹂댁쑀(愿留?</button>`
                : `<button type="button" class="button-ghost queue-order"
                    data-symbol="${escapeHtml(row.symbol)}"
                    data-name="${escapeHtml(row.name)}"
                    data-action="${escapeHtml(action)}"
                    data-qty="${Number(row.signal_qty || 0)}"
                    data-price="${Number(row.signal_price || 0)}"
                    data-reason="${escapeHtml(row.reason)}"
                    data-source="signal">?뱀씤?湲?/button>`;
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
    setTableMessage('#table-candidates tbody', 8, '愿?ъ쥌紐⑹뿉??留ㅼ닔 ?꾨낫瑜?李얘퀬 ?덉뒿?덈떎...');
    try {
        const data = await fetchJson('/api/candidates?min_score=2');
        const tbody = document.querySelector('#table-candidates tbody');
        tbody.innerHTML = '';
        if (!data.candidates.length) {
            const scanned = data.scanned || 0;
            const scanError = data.scan_error || null;
            const tableMsg = scanned === 0
                ? (scanError ? `?곗씠???섏떊 ?ㅽ뙣 ???좎떆 ???ㅼ떆 ?쒕룄??二쇱꽭?? : '遺꾩꽍 ???醫낅ぉ???놁뒿?덈떎')
                : `議곌굔??留뚯”???꾨낫媛 ?놁뒿?덈떎 ??${scanned}醫낅ぉ 遺꾩꽍 ?꾨즺`;
            setTableMessage('#table-candidates tbody', 8, tableMsg);
            // 遺꾩꽍 洹쇨굅 ?앹뾽
            const titleEl = document.getElementById('noCandidatesTitle');
            const subtitleEl = document.getElementById('noCandidatesSubtitle');
            const bodyEl = document.getElementById('noCandidatesBody');
            if (scanned === 0 && scanError) {
                if (titleEl) titleEl.textContent = '?좑툘 ?곗씠???섏떊 ?ㅽ뙣';
                if (subtitleEl) subtitleEl.textContent = '?쒖꽭 ?곗씠?곕? 媛?몄삤吏 紐삵빐 遺꾩꽍??吏꾪뻾?????놁뿀?듬땲??';
                if (bodyEl) bodyEl.innerHTML = buildScanErrorModalMarkup(scanError);
            } else {
                if (titleEl) titleEl.textContent = '?뱤 留ㅼ닔 ?꾨낫 ?놁쓬 ??遺꾩꽍 寃곌낵';
                if (subtitleEl) subtitleEl.textContent =
                    `${scanned}醫낅ぉ??遺꾩꽍?덉쑝??湲곗? ?먯닔(${data.min_score || 2}?? ?댁긽??醫낅ぉ???놁뒿?덈떎.`;
                if (bodyEl) bodyEl.innerHTML = buildNoCandidatesModalMarkup(data);
            }
            setNoCandidatesModalOpen(true);
            if (data._cache?.cached_at) {
                setStatus(`理쒓렐 ?꾨낫 寃??寃곌낵瑜??쒖떆?⑸땲?? 湲곗? ?쒓컖 ${data._cache.cached_at}`, true);
            } else {
                setStatus('遺꾩꽍 ?꾨즺 ??留ㅼ닔 湲곗???異⑹”?섎뒗 醫낅ぉ???놁뒿?덈떎.', true);
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
                    data-source="candidate">?뱀씤?湲?/button>`
                : `<button type="button" class="button-ghost" disabled title="?붽퀬 遺議??먮뒗 理쒕? 蹂댁쑀 醫낅ぉ ??MAX_POSITIONS) 珥덇낵濡?留ㅼ닔?????놁뒿?덈떎." style="opacity:0.5; cursor:not-allowed;">?뱀씤遺덇?</button>`;

            // ?곸꽭 洹쇨굅 鍮뚮뱶
            const reasonLines = (row.reasons || []).map(r => strategyReasonLabel(r));
            const detailParts = [];
            if (row.rsi != null) detailParts.push(`RSI ${formatNumber(row.rsi,1)}`);
            if (row.rsi2 != null) detailParts.push(`RSI2 ${formatNumber(row.rsi2,1)}`);
            if (row.macd_hist != null) detailParts.push(`MACD ${formatNumber(row.macd_hist,2)}`);
            if (row.sma20 != null && row.sma60 != null) {
                const trend = row.sma20 > row.sma60 ? '?④린?묒쨷湲곗꽑 ?? : '?④린?볦쨷湲곗꽑 ?꾨옒';
                detailParts.push(trend);
            }
            if (row.bb_lo != null && row.current_price != null) {
                const bbDist = ((row.current_price - row.bb_lo) / row.bb_lo * 100).toFixed(1);
                detailParts.push(`蹂쇰객?섎떒+${bbDist}%`);
            }
            const detailSuffix = detailParts.length ? ` (${detailParts.join(' | ')})` : '';
            const reasonText = reasonLines.join(' 쨌 ') + detailSuffix;

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
            setStatus(`理쒓렐 ?꾨낫 寃??寃곌낵瑜??쒖떆?⑸땲?? 湲곗? ?쒓컖 ${data._cache.cached_at}`, true);
        } else {
            setStatus('留ㅼ닔 ?꾨낫 寃?됱쓣 ?꾨즺?덉뒿?덈떎.', true);
        }
    } catch (err) {
        setTableMessage('#table-candidates tbody', 8, err.message);
    } finally {
        setButtonBusy('btn-candidates', false);
    }
}

async function renderAiAllocation() {
    setButtonBusy('btn-ai-allocation', true);
    setTableMessage('#table-ai-allocation tbody', 8, 'AI 紐⑺몴 鍮꾩쨷??怨꾩궛?섍퀬 ?덉뒿?덈떎...');
    try {
        const data = await fetchJson('/api/ai-allocation');
        const tbody = document.querySelector('#table-ai-allocation tbody');
        tbody.innerHTML = '';
        if (!data.positions.length) {
            setTableMessage('#table-ai-allocation tbody', 8, '怨꾩궛??蹂댁쑀 醫낅ぉ???놁뒿?덈떎');
            return;
        }

        data.positions.forEach((row) => {
            const action = String(row.rebalance_action || 'hold').toLowerCase();
            const kind = action === 'buy' ? 'buy' : (action === 'sell' ? 'sell' : 'hold');
            const reason = `AI 紐⑺몴鍮꾩쨷 ${formatNumber(row.target_weight * 100, 1)}%; ${translateReason(((row.reasons || []).slice(0, 3)).join(', '))}`;
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
                ai_strategy_name: row.ai_strategy_name || 'AI ?꾨왂 ?곸꽭',
                reasons: Array.isArray(row.reasons) ? row.reasons : []
            }));
            const queueButton = action === 'hold'
                ? `<button type="button" class="button-ghost" disabled title="AI媛 ?꾩옱 鍮꾩쨷???좎???寃껋쓣 沅뚯옣?⑸땲??" style="opacity:0.3; cursor:not-allowed;">?좎?</button>`
                : `<button type="button" class="button-ghost queue-order"
                    data-symbol="${escapeHtml(row.symbol)}"
                    data-name="${escapeHtml(row.name)}"
                    data-action="${escapeHtml(action)}"
                    data-qty="${Number(row.rebalance_qty || 0)}"
                    data-price="${Number(row.price || 0)}"
                    data-reason="${escapeHtml(reason)}"
                    data-source="ai-allocation">?뱀씤?湲?/button>`;
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
                        ${escapeHtml(row.ai_strategy_name || "?꾨왂 ?곸꽭 ?댁뿭 蹂닿린")}
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
        setStatus(`${toKorAction(payload.action)} ${payload.symbol} 二쇰Ц???뱀씤 ?湲곗뿉 ?щ졇?듬땲??`, true);
        await renderApprovals();
    } catch (err) {
        setStatus(`?뱀씤 ?湲??깅줉 ?ㅽ뙣: ${err.message}`);
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
            setTableMessage('#table-approvals tbody', 7, '?뱀씤 ?湲?二쇰Ц???놁뒿?덈떎');
            return;
        }

        data.approvals.forEach((row) => {
            const status = String(row.status || '');
            const statusKind = status === 'pending' ? 'warn' : (status === 'executed' ? 'buy' : (status === 'failed' ? 'sell' : 'hold'));
            const controls = status === 'pending'
                ? `<div class="button-row">
                    <button type="button" class="approve-order" data-id="${row.id}">?뱀씤</button>
                    <button type="button" class="button-danger reject-order" data-id="${row.id}">嫄곗젅</button>
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
        setStatus(`?뱀씤 泥섎━ 寃곌낵: ${toKorStatus(result.status)} #${result.id}`, result.status !== 'failed');
        await Promise.all([renderApprovals(), renderTrades(), renderBalance()]);
    } catch (err) {
        setStatus(`?뱀씤 泥섎━ ?ㅽ뙣: ${err.message}`);
        button.disabled = false;
    }
}

async function renderTrades() {
    try {
        // ?깃낵 ?붿빟 (Performance)
        try {
            const perf = await fetchJson('/api/performance');
            document.getElementById('perf-total-trades').textContent = `${perf.total_trades}??;
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
                    setTableMessage('#table-eval-details tbody', 6, '?먮룞留ㅻℓ濡?留ㅼ닔??蹂댁쑀醫낅ぉ???놁뒿?덈떎.');
                } else {
                    details.forEach((item) => {
                        const tr = document.createElement('tr');
                        const pnlClass = item.eval_pnl > 0 ? 'text-success' : (item.eval_pnl < 0 ? 'text-danger' : '');
                        tr.innerHTML = `
                            <td>
                                <span class="symbol-name">${escapeHtml(item.name || item.symbol)}</span>
                                ${item.diff_reason ? `<div style="font-size: 0.75rem; color: #ffc107; margin-top: 2px;">?좑툘 ${escapeHtml(item.diff_reason)}</div>` : ''}
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
                            diffHtml += `<li><strong>${escapeHtml(item.name)}</strong>: ${escapeHtml(item.diff_reason)} (?됯??먯씡 李⑥븸: ${sign}${formatCurrency(diffAmt)})</li>`;
                        }
                    });
                    
                    const untracked = perf.untracked_details || [];
                    untracked.forEach(item => {
                        const sign = item.broker_pnl > 0 ? '+' : '';
                        diffHtml += `<li><strong>${escapeHtml(item.name)}</strong>: ${escapeHtml(item.diff_reason)} (利앷텒???됯??먯씡 ?꾩껜 ?⑹궛: ${sign}${formatCurrency(item.broker_pnl)})</li>`;
                    });
                    
                    diffList.innerHTML = diffHtml || '<li>李⑥씠 ?먯씤??遺꾩꽍?????녿뒗 ?ㅼ감媛 ?덉뒿?덈떎. (API 吏????</li>';
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
            setTableMessage('#table-trades tbody', 6, '二쇰Ц 湲곕줉???놁뒿?덈떎');
        }

        trades.trades.forEach((trade) => {
            const action = String(trade.action || '').toLowerCase();
            const badge = action === 'buy'
                ? '<span class="badge badge-buy">留ㅼ닔</span>'
                : '<span class="badge badge-sell">留ㅻ룄</span>';
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
        btnSyncTrades.textContent = '?숆린??以?..';
        btnSyncTrades.style.backgroundColor = '#f59e0b'; // warning yellow
        btnSyncTrades.style.color = 'white';
        try {
            const result = await postJson('/api/trades/sync', {});
            setStatus(`利앷텒??湲곕줉 ?숆린???꾨즺 (?꾨씫??${result.synced_count}嫄?異붽???`, true);
            await renderTrades();
            
            btnSyncTrades.textContent = result.synced_count > 0 ? `?숆린???꾨즺 (${result.synced_count}嫄?` : '?숆린???꾨즺 ?뷂툘';
            btnSyncTrades.style.backgroundColor = '#10b981'; // success green
            btnSyncTrades.style.color = 'white';
            
            setTimeout(() => {
                btnSyncTrades.disabled = false;
                btnSyncTrades.textContent = '利앷텒??湲곕줉 ?숆린??;
                btnSyncTrades.style.backgroundColor = '';
                btnSyncTrades.style.color = '';
            }, 3000);
            
        } catch (err) {
            setStatus(`?숆린???ㅽ뙣: ${err.message}`);
            btnSyncTrades.textContent = '?숆린???ㅽ뙣';
            btnSyncTrades.style.backgroundColor = '#ef4444'; // error red
            btnSyncTrades.style.color = 'white';
            
            setTimeout(() => {
                btnSyncTrades.disabled = false;
                btnSyncTrades.textContent = '利앷텒??湲곕줉 ?숆린??;
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
            titleEl.textContent = `${payload.name || payload.symbol || 'AI ?꾨왂'} ?곸꽭 洹쇨굅`;
            if (subtitleEl) {
                subtitleEl.textContent = payload.ai_strategy_name || '';
            }
            bodyEl.innerHTML = buildAiModalMarkup(payload);
        } catch (_err) {
            const reasonText = element.getAttribute('data-reason') || '-';
            titleEl.textContent = 'AI ?꾨왂 ?곸꽭 洹쇨굅';
            if (subtitleEl) {
                subtitleEl.textContent = '';
            }
            bodyEl.textContent = reasonText;
        }
    } else {
        const reasonText = element.getAttribute('data-reason') || '-';
        titleEl.textContent = 'AI ?꾨왂 ?곸꽭 洹쇨굅';
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

    // ?リ린 踰꾪듉 ??紐⑤뱺 .close-modal 踰꾪듉??媛?紐⑤떖 而⑦뀓?ㅽ듃濡??곌껐
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
setTableMessage('#table-signals tbody', 7, '吏꾨떒?섍린瑜??꾨Ⅴ硫?蹂댁쑀 醫낅ぉ ?좏샇瑜??뺤씤?⑸땲??);
setTableMessage('#table-candidates tbody', 8, '李얘린瑜??꾨Ⅴ硫?愿?ъ쥌紐⑹뿉??留ㅼ닔 ?꾨낫瑜?寃?됲빀?덈떎');
setTableMessage('#table-approvals tbody', 7, '?뱀씤 ?湲?二쇰Ц???놁뒿?덈떎');
setTableMessage('#table-ai-allocation tbody', 8, '怨꾩궛???꾨Ⅴ硫?AI 紐⑺몴 鍮꾩쨷???뺤씤?⑸땲??);
setTableMessage('#table-optimizer tbody', 7, '理쒖쟻?붾? ?꾨Ⅴ硫?由ъ뒪??湲곕컲 紐⑺몴 鍮꾩쨷???뺤씤?⑸땲??);
fetchDashboardData();
setInterval(() => Promise.all([renderRuntime(), renderBalance(), renderTrades(), renderApprovals()]), 30000);
