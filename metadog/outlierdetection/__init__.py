import pandas as pd
import numpy as np


class OutlierDetector:
    def __init__(self):
        pass


    def get_outliers_in_df(self, df: pd.DataFrame) -> pd.DataFrame:
        if len(df) < 2:
            return pd.DataFrame()
        from prophet import Prophet
        m = Prophet()
        m.fit(df)
        pred = m.predict(df)
        pred['observed'] = df['y']
        outliers = pred[(pred['yhat_lower'] > pred['observed']) | (pred['yhat_upper'] < pred['observed'])]

        return outliers[['ds', 'observed', 'yhat_lower', 'yhat_upper']]


    def get_warnings(self):
        pass


class zIndex:
    def __init__(self, threshold: float = 3.0):
        self.threshold = threshold


    def get_outliers_in_df(self, df: pd.DataFrame, column: str = 'y') -> pd.DataFrame:
        if len(df) < 2:
            return pd.DataFrame()
        std = df[column].std(ddof=0)
        if std == 0:
            return pd.DataFrame()
        df = df.copy()
        df['z_index'] = np.abs((df[column] - df[column].mean()) / std)
        return df[df['z_index'] > self.threshold][['ds', column, 'z_index']]
