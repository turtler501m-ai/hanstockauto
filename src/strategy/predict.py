import os
import pickle
from pathlib import Path
from src.config import config
from src.utils.logger import logger

class ModelPredictor:
    def __init__(self):
        self.version = getattr(config, "active_model_version", "v1")
        self.model_path = Path(f"data/models/ranker_{self.version}.pkl")
        self.model = self._load_model()

    def _load_model(self):
        if self.model_path.exists():
            try:
                with open(self.model_path, "rb") as f:
                    model = pickle.load(f)
                logger.info(f"[AI] Loaded model: {self.model_path}")
                return model
            except Exception as e:
                logger.error(f"[AI] Failed to load model {self.model_path}: {e}")
        else:
            logger.info(f"[AI] Model file not found: {self.model_path}. Using fallback rule-based mode.")
        return None

    def predict_score(self, features: dict) -> float:
        """
        AI 모델을 통해 종목의 점수(상승 확률 또는 기대 수익)를 예측합니다.
        features: rsi, macd_hist, sma20 등 보조지표 딕셔너리
        """
        if self.model is None:
            # Fallback: 기존 룰베이스 점수 반환
            return float(features.get("strategy_score", 0.0))
            
        try:
            # 실제 모델(LightGBM 등) 추론 로직
            # 추후 피처 파이프라인에서 추출된 1D 배열을 넘겨 추론합니다.
            # 예시:
            # import numpy as np
            # x = np.array([[features.get("rsi", 50), features.get("macd_hist", 0)]])
            # return float(self.model.predict(x)[0])
            
            # 현재는 Mock-up으로 기존 점수를 그대로 사용
            return float(features.get("strategy_score", 0.0))
        except Exception as e:
            logger.error(f"[AI] Prediction error: {e}")
            return 0.0
