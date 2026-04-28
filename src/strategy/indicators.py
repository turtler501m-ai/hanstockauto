def calc_rsi(prices: list[float], period: int = 14) -> float:
    if len(prices) < period + 1:
        return 50.0
    gains, losses = [], []
    for i in range(1, len(prices)):
        diff = prices[i] - prices[i - 1]
        gains.append(max(diff, 0))
        losses.append(max(-diff, 0))
    avg_gain = sum(gains[-period:]) / period
    avg_loss = sum(losses[-period:]) / period
    if avg_loss == 0:
        return 100.0
    return round(100 - (100 / (1 + avg_gain / avg_loss)), 2)

def calc_sma(prices: list[float], period: int) -> float:
    if len(prices) < period:
        return prices[-1] if prices else 0
    return sum(prices[-period:]) / period

def calc_ema_series(values: list[float], period: int) -> list[float]:
    if not values:
        return []
    alpha = 2 / (period + 1)
    ema = [values[0]]
    for value in values[1:]:
        ema.append((value * alpha) + (ema[-1] * (1 - alpha)))
    return ema

def calc_macd(prices: list[float], fast: int = 12, slow: int = 26, signal: int = 9) -> dict:
    if len(prices) < slow + signal:
        return {"macd": 0.0, "signal": 0.0, "hist": 0.0, "bull_cross": False, "bear_cross": False}
    fast_ema = calc_ema_series(prices, fast)
    slow_ema = calc_ema_series(prices, slow)
    macd_line = [fast_ema[i] - slow_ema[i] for i in range(len(prices))]
    signal_line = calc_ema_series(macd_line, signal)
    macd_now, macd_prev = macd_line[-1], macd_line[-2]
    sig_now, sig_prev = signal_line[-1], signal_line[-2]
    return {
        "macd": round(macd_now, 4),
        "signal": round(sig_now, 4),
        "hist": round(macd_now - sig_now, 4),
        "bull_cross": macd_prev <= sig_prev and macd_now > sig_now,
        "bear_cross": macd_prev >= sig_prev and macd_now < sig_now,
    }

def calc_bollinger(prices: list[float], period: int = 20) -> tuple:
    if len(prices) < period:
        price = prices[-1] if prices else 0
        return price, price, price
    window = prices[-period:]
    mid = sum(window) / period
    std = (sum((x - mid) ** 2 for x in window) / period) ** 0.5
    return round(mid - 2 * std), round(mid), round(mid + 2 * std)
