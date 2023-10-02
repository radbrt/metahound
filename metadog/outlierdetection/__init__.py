from prophet import Prophet
import pandas as pd
import numpy as np


class OutlierDetector:
    def __init__(self):
        pass


    def get_outliers_in_df(self, df):
        m = Prophet()
        m.fit(df)
        pred = m.predict(df)
        pred['observed'] = df['y']
        outliers = pred[ (pred['yhat_lower'] > pred['observed'])  | (pred['yhat_upper'] < pred['observed']) ]


        return outliers[['ds', 'observed', 'yhat_lower', 'yhat_upper']]


    def get_warnings(self):
        pass

class zIndex:
    def __init__(self, threshold=3):
        self.threshold = threshold
        

    def get_outliers_in_df(self, df, column='y'):
        df = df.copy()
        df['z_index'] = np.abs((df[column] - df[column].mean())/df[column].std(ddof=0))
        return df[df['z_index'] > self.threshold][['ds', column, 'z_index']]
