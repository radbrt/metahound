import pytest
import pandas as pd
import numpy as np
from metadog.outlierdetection import zIndex


def _make_df(values):
    """Helper to build a (ds, y) DataFrame."""
    return pd.DataFrame({
        "ds": pd.date_range("2024-01-01", periods=len(values), freq="D"),
        "y": values,
    })


class TestZIndex:
    def test_empty_dataframe_returns_empty(self):
        detector = zIndex()
        result = detector.get_outliers_in_df(pd.DataFrame(columns=["ds", "y"]))
        assert isinstance(result, pd.DataFrame)
        assert len(result) == 0

    def test_single_row_returns_empty(self):
        detector = zIndex()
        result = detector.get_outliers_in_df(_make_df([42]))
        assert isinstance(result, pd.DataFrame)
        assert len(result) == 0

    def test_constant_series_returns_empty(self):
        detector = zIndex()
        result = detector.get_outliers_in_df(_make_df([5, 5, 5, 5, 5]))
        assert isinstance(result, pd.DataFrame)
        assert len(result) == 0

    def test_known_outlier_detected(self):
        detector = zIndex(threshold=2.0)
        # The last value is a clear outlier
        values = [10, 10, 10, 10, 10, 10, 10, 10, 10, 100]
        result = detector.get_outliers_in_df(_make_df(values))
        assert len(result) == 1
        assert result.iloc[0]["y"] == 100

    def test_threshold_respected_no_outlier(self):
        # With a very high threshold, nothing should be flagged
        detector = zIndex(threshold=100.0)
        values = [10, 10, 10, 10, 10, 10, 10, 10, 10, 100]
        result = detector.get_outliers_in_df(_make_df(values))
        assert len(result) == 0

    def test_threshold_respected_more_outliers(self):
        # With a low threshold, more points get flagged
        detector_tight = zIndex(threshold=0.5)
        values = [10, 10, 10, 11, 10, 10, 10, 12, 10, 10]
        result = detector_tight.get_outliers_in_df(_make_df(values))
        assert len(result) > 0

    def test_output_columns(self):
        detector = zIndex(threshold=2.0)
        values = [10, 10, 10, 10, 10, 10, 10, 10, 10, 100]
        result = detector.get_outliers_in_df(_make_df(values))
        assert set(result.columns) == {"ds", "y", "z_index"}


class TestOutlierDetectorProphet:
    def test_prophet_skipped_if_not_installed(self):
        """Prophet is optional; skip the test if it isn't importable."""
        pytest.importorskip("prophet")

    def test_single_row_returns_empty(self):
        pytest.importorskip("prophet")
        from metadog.outlierdetection import OutlierDetector
        detector = OutlierDetector()
        result = detector.get_outliers_in_df(_make_df([42]))
        assert isinstance(result, pd.DataFrame)
        assert len(result) == 0
