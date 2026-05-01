const decisions = [
    {
        symbol: "005930",
        name: "삼성전자",
        action: "buy",
        qty: 7,
        price: 78200,
        confidence: 0.74,
        expectedReturn: 3.8,
        risk: "통과",
        model: "ranker_lgbm_v3",
        factors: ["20일 거래량 1.8배", "MACD histogram 양전환", "RSI14 42 회복", "목표 비중 18%, 현재 12%"],
    },
    {
        symbol: "000660",
        name: "SK하이닉스",
        action: "hold",
        qty: 0,
        price: 188400,
        confidence: 0.61,
        expectedReturn: 1.2,
        risk: "관찰",
        model: "ensemble_v2",
        factors: ["상승 추세 유지", "단일 종목 비중 한도 근접", "추가 매수는 승인 대기"],
    },
    {
        symbol: "035420",
        name: "NAVER",
        action: "buy",
        qty: 2,
        price: 192600,
        confidence: 0.68,
        expectedReturn: 2.9,
        risk: "통과",
        model: "ranker_lgbm_v3",
        factors: ["Bollinger 하단 반등", "RSI2 과매도 해소", "포트폴리오 상관 완화 효과"],
    },
    {
        symbol: "051910",
        name: "LG화학",
        action: "sell",
        qty: 1,
        price: 412000,
        confidence: 0.72,
        expectedReturn: -1.5,
        risk: "통과",
        model: "allocator_v2",
        factors: ["목표 비중 축소", "변동성 20일 기준 상승", "현금 비중 회복 필요"],
    },
];

const riskChecks = [
    ["현금 버퍼", "목표 20%, 현재 24%", 34, "pass"],
    ["일일 손실 한도", "3.0% 중 0.54% 사용", 18, "pass"],
    ["종목 집중도", "최대 30%, 현재 21%", 70, "watch"],
    ["주문 금액", "1,000,000원 중 546,000원", 55, "pass"],
    ["API 상태", "최근 오류 0건", 0, "pass"],
];

const approvals = [
    ["삼성전자", "매수", "7주", "대기"],
    ["NAVER", "매수", "2주", "대기"],
    ["LG화학", "매도", "1주", "대기"],
];

const audits = [
    "14:29:12 ranker_lgbm_v3 후보 8건 생성",
    "14:29:14 risk engine 주문 후보 3건 통과",
    "14:29:16 신규 매수 후보 승인 큐 등록",
    "14:29:18 paper ledger 예상 주문 기록",
    "14:29:22 Slack 승인 요청 발송",
];

const formatCurrency = (value) => `${Number(value).toLocaleString("ko-KR")}원`;
const actionLabel = { buy: "매수", sell: "매도", hold: "보유" };

function iconize() {
    document.querySelectorAll("[data-icon]").forEach((element) => {
        if (element.querySelector("svg")) {
            return;
        }
        const icon = document.createElement("i");
        icon.setAttribute("data-lucide", element.dataset.icon);
        element.prepend(icon);
    });
    if (window.lucide) {
        window.lucide.createIcons();
    }
}

function renderDecisions() {
    const root = document.getElementById("decision-table");
    root.innerHTML = "";
    decisions.forEach((item, index) => {
        const row = document.createElement("button");
        row.type = "button";
        row.className = `decision-row ${index === 0 ? "selected" : ""}`;
        row.innerHTML = `
            <div class="symbol">
                <strong>${item.name}</strong>
                <span>${item.symbol} · ${item.model}</span>
            </div>
            <span class="action-pill ${item.action}">${actionLabel[item.action]}</span>
            <strong>${item.qty ? `${item.qty}주` : "-"}</strong>
            <span>${formatCurrency(item.price)}</span>
            <span>신뢰도 ${Math.round(item.confidence * 100)}%</span>
            <span class="subtle">예상 ${item.expectedReturn > 0 ? "+" : ""}${item.expectedReturn}%</span>
        `;
        row.addEventListener("click", () => {
            document.querySelectorAll(".decision-row").forEach((node) => node.classList.remove("selected"));
            row.classList.add("selected");
            renderExplain(item);
        });
        root.appendChild(row);
    });
}

function renderExplain(item = decisions[0]) {
    const root = document.getElementById("explain-card");
    const score = Math.round(item.confidence * 100);
    root.innerHTML = `
        <div class="score-ring" style="--score: ${score}%">
            <div>
                <strong>${score}</strong>
                <span>confidence</span>
            </div>
        </div>
        <div>
            <strong>${item.name} ${actionLabel[item.action]} 판단</strong>
            <p class="subtle">${item.model} · 리스크 ${item.risk} · 예상 20거래일 수익률 ${item.expectedReturn > 0 ? "+" : ""}${item.expectedReturn}%</p>
        </div>
        <ul class="factor-list">
            ${item.factors.map((factor) => `<li>${factor}</li>`).join("")}
        </ul>
    `;
}

function renderRiskChecks() {
    const root = document.getElementById("risk-checks");
    root.innerHTML = riskChecks.map(([name, detail, value, status]) => `
        <div class="risk-check">
            <div>
                <strong>${name}</strong>
                <span>${detail}</span>
            </div>
            <div class="bar"><i style="width: ${Math.max(value, 4)}%"></i></div>
            <em class="risk-status ${status}">${status === "pass" ? "통과" : "주의"}</em>
        </div>
    `).join("");
}

function renderApprovals() {
    const root = document.getElementById("approval-list");
    root.innerHTML = approvals.map(([name, action, qty, status]) => `
        <div class="approval-row">
            <strong>${name}</strong>
            <span class="action-pill ${action === "매수" ? "buy" : "sell"}">${action}</span>
            <span>${qty}</span>
            <button type="button" class="mini-button">${status}</button>
        </div>
    `).join("");
}

function renderAudits() {
    const root = document.getElementById("audit-list");
    root.innerHTML = audits.map((event) => `<li>${event}</li>`).join("");
}

function renderChart() {
    const ctx = document.getElementById("performance-chart");
    if (!ctx || !window.Chart) {
        return;
    }
    new Chart(ctx, {
        type: "line",
        data: {
            labels: ["3/18", "3/25", "4/1", "4/8", "4/15", "4/22", "4/28"],
            datasets: [
                {
                    label: "Paper 수익률",
                    data: [0, 1.2, 2.1, 1.8, 4.4, 6.1, 7.8],
                    borderColor: "#22c55e",
                    backgroundColor: "rgba(34, 197, 94, 0.14)",
                    fill: true,
                    tension: 0.35,
                },
                {
                    label: "최대 낙폭",
                    data: [0, -0.4, -0.8, -1.7, -1.1, -0.9, -1.3],
                    borderColor: "#f59e0b",
                    backgroundColor: "rgba(245, 158, 11, 0.08)",
                    fill: true,
                    tension: 0.35,
                },
            ],
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: { legend: { labels: { color: "#c5d1df" } } },
            scales: {
                x: { ticks: { color: "#96a4b6" }, grid: { color: "rgba(255,255,255,0.05)" } },
                y: { ticks: { color: "#96a4b6", callback: (value) => `${value}%` }, grid: { color: "rgba(255,255,255,0.05)" } },
            },
        },
    });
}

function bindControls() {
    document.getElementById("btn-refresh").addEventListener("click", () => {
        document.getElementById("metric-candidates").textContent = "8종목";
    });
    document.getElementById("btn-kill-switch").addEventListener("click", (event) => {
        event.currentTarget.innerHTML = "";
        event.currentTarget.dataset.icon = "shield-alert";
        iconize();
        event.currentTarget.append("Kill Switch Armed");
    });
}

iconize();
renderDecisions();
renderExplain();
renderRiskChecks();
renderApprovals();
renderAudits();
renderChart();
bindControls();
