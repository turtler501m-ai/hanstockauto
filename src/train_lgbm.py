import os
import sqlite3
import pandas as pd
import numpy as np
from pathlib import Path
from src.utils.logger import logger

# Note: 실습을 위해 가벼운 LightGBM 모델 훈련 스크립트 뼈대입니다.
# 실행 시 pip install lightgbm scikit-learn 이 필요합니다.

def fetch_decision_logs():
    db_path = ".runtime/trades.sqlite"
    if not os.path.exists(db_path):
        logger.error("DB 파일을 찾을 수 없습니다.")
        return None
    
    conn = sqlite3.connect(db_path)
    # 실제 환경에서는 decision_logs 의 수익률을 추적하여 target(y)을 만들어야 합니다.
    df = pd.read_sql_query("SELECT * FROM decision_logs", conn)
    conn.close()
    return df

def train_model():
    df = fetch_decision_logs()
    if df is None or df.empty:
        logger.warning("학습할 데이터(decision_logs)가 부족합니다.")
        return

    logger.info(f"{len(df)}건의 로그 데이터를 바탕으로 LightGBM 랭커 모델을 학습합니다...")
    
    # TODO: df['indicators'] (JSON)를 파싱하여 X_train을 만들고, 미래 수익률을 Y_train으로 만듭니다.
    # import lightgbm as lgb
    # model = lgb.LGBMRegressor()
    # model.fit(X_train, y_train)
    
    # 모델 저장 (MLOps 버저닝)
    models_dir = Path("data/models")
    models_dir.mkdir(parents=True, exist_ok=True)
    
    # with open(models_dir / "ranker_v1.pkl", "wb") as f:
    #     pickle.dump(model, f)
    logger.info("모델 학습 및 저장 완료 (data/models/ranker_v1.pkl)")

if __name__ == "__main__":
    train_model()
