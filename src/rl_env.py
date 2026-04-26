import gymnasium as gym
import numpy as np
import yfinance as yf
from datetime import datetime, timedelta
import pandas as pd
from typing import List, Dict

def calc_rsi(prices: pd.Series, period: int = 14) -> pd.Series:
    delta = prices.diff()
    gain = delta.where(delta > 0, 0)
    loss = -delta.where(delta < 0, 0)
    avg_gain = gain.rolling(window=period, min_periods=period).mean()
    avg_loss = loss.rolling(window=period, min_periods=period).mean()
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))

def calc_macd(prices: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9):
    exp1 = prices.ewm(span=fast, adjust=False).mean()
    exp2 = prices.ewm(span=slow, adjust=False).mean()
    macd = exp1 - exp2
    sig = macd.ewm(span=signal, adjust=False).mean()
    hist = macd - sig
    return macd, sig, hist

class SimpleStockTradingEnv(gym.Env):
    """
    A simple Gym environment for multi-stock target weight allocation.
    Designed to easily train a PPO agent for Seven Split auto-trading.
    """
    def __init__(self, tickers: List[str], start_date: str, end_date: str, initial_capital: float = 1e7):
        super(SimpleStockTradingEnv, self).__init__()
        self.tickers = tickers
        self.initial_capital = initial_capital
        
        self.data = self._fetch_and_prepare_data(tickers, start_date, end_date)
        self.dates = sorted(list(self.data.index.unique()))
        
        # State space: For each stock [Price, RSI, MACD_hist, SMA_trend]
        self.state_dim_per_stock = 4
        total_state_dim = len(self.tickers) * self.state_dim_per_stock
        self.observation_space = gym.spaces.Box(low=-np.inf, high=np.inf, shape=(total_state_dim,), dtype=np.float32)
        
        # Action space: Target weights for each stock [-1, 1] mapped to proportions
        self.action_space = gym.spaces.Box(low=-1, high=1, shape=(len(self.tickers),), dtype=np.float32)
        
        self.current_step = 0
        self.portfolio_value = self.initial_capital
        self.weights = np.zeros(len(self.tickers))
        
    def _fetch_and_prepare_data(self, tickers: List[str], start_date: str, end_date: str):
        print(f"Downloading data for {tickers} from {start_date} to {end_date}...")
        df_list = []
        for ticker in tickers:
            symbol = f"{ticker}.KS"  # KOSPI format
            df = yf.download(symbol, start=start_date, end=end_date, progress=False)
            if df.empty:
                continue
            
            # Handle pandas MultiIndex if yfinance returns it
            if isinstance(df.columns, pd.MultiIndex):
                df = df.droplevel(1, axis=1)
                
            close_col = 'Close'
            if close_col not in df.columns:
                print(f"Warning: Close column not found for {ticker}")
                continue
                
            df['Ticker'] = ticker
            df['RSI'] = calc_rsi(df[close_col])
            macd, _, hist = calc_macd(df[close_col])
            df['MACD_hist'] = hist
            sma60 = df[close_col].rolling(window=60, min_periods=60).mean()
            df['SMA_trend'] = (df[close_col] - sma60) / sma60
            
            df = df.dropna()
            df_list.append(df)
            
        full_df = pd.concat(df_list)
        # Pivot so we have date index and multi-level columns
        return full_df.pivot(columns='Ticker')
        
    def reset(self, seed=None, options=None):
        super().reset(seed=seed)
        self.current_step = 0
        self.portfolio_value = self.initial_capital
        self.weights = np.zeros(len(self.tickers))
        return self._get_obs(), {}
        
    def _get_obs(self):
        current_date = self.dates[self.current_step]
        obs = []
        # Fallback for missing data at this date
        for ticker in self.tickers:
            try:
                # Need to handle potential KeyError if ticker missing on this date
                price = self.data.loc[current_date, ('Close', ticker)]
                rsi = self.data.loc[current_date, ('RSI', ticker)]
                macd = self.data.loc[current_date, ('MACD_hist', ticker)]
                trend = self.data.loc[current_date, ('SMA_trend', ticker)]
                
                # Check for nan
                if np.isnan(price) or np.isnan(rsi) or np.isnan(macd) or np.isnan(trend):
                    obs.extend([0.0, 50.0, 0.0, 0.0]) # fallback neutral state
                else:
                    # Normalize somewhat
                    obs.extend([price / 100000.0, rsi / 100.0, macd / 1000.0, trend])
            except (KeyError, IndexError):
                obs.extend([0.0, 50.0, 0.0, 0.0])
                
        return np.array(obs, dtype=np.float32)
        
    def step(self, action):
        current_date = self.dates[self.current_step]
        
        # Calculate returns for the next day
        returns = np.zeros(len(self.tickers))
        if self.current_step < len(self.dates) - 1:
            next_date = self.dates[self.current_step + 1]
            for i, ticker in enumerate(self.tickers):
                try:
                    curr_price = self.data.loc[current_date, ('Close', ticker)]
                    next_price = self.data.loc[next_date, ('Close', ticker)]
                    if curr_price > 0 and not np.isnan(curr_price) and not np.isnan(next_price):
                        returns[i] = (next_price / curr_price) - 1
                except (KeyError, IndexError):
                    pass
                    
        # Apply actions (softmax-like to ensure weights sum to 1 or less)
        exp_a = np.exp(action)
        target_weights = exp_a / np.sum(exp_a)
        
        # Calculate daily portfolio return based on target weights
        portfolio_return = np.sum(target_weights * returns)
        self.portfolio_value *= (1 + portfolio_return)
        
        # Reward is simply the log return
        reward = portfolio_return * 100 
        
        self.current_step += 1
        terminated = self.current_step >= len(self.dates) - 1
        truncated = False
        
        return self._get_obs(), reward, terminated, truncated, {"portfolio_value": self.portfolio_value}
