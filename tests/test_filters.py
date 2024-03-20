import numpy as np
import pandas as pd
import pytest
from data_filters.plots import UnivariatePlotter
from data_filters.processing_steps.alferes_outlier.filter_algorithms import (
    AlferesAlgorithm,
)
from data_filters.processing_steps.alferes_outlier.filters import AlferesFilter
from data_filters.processing_steps.smoothers import HKernelSmoother
from data_filters.protocols import FilterRow
from test_models import get_model


def get_data(series_name, path="tests/sample_data/test_data.csv") -> pd.Series:
    df = pd.read_csv(path, index_col=0)
    df.index = pd.to_datetime(df.index)
    return df[series_name]


def get_control_parameters(threshold: int = 5, steps_back: int = 10, warmup: int = 2):
    return {
        "n_outlier_threshold": threshold,
        "n_steps_back": steps_back,
        "n_warmup_steps": warmup,
    }


def test_expand_filter_row():
    row = FilterRow(
        index=1,
        input_values=np.array([1, 2, 3]),
        inputs_are_outliers=np.array([True, False, True]),
        accepted_values=np.array([2, 3, 1]),
        predicted_values=np.array([2, 3, 4]),
        predicted_upper_limits=np.array([2]),
        predicted_lower_limits=np.array([2, 3, 4]),
    )
    expanded_row = AlferesFilter.expand_filter_row(row)
    assert expanded_row["input_values_2"] == 2
    assert expanded_row["predicted_upper_limits"] == 2


def test_input_data():
    data = get_data("dirty sine").to_numpy()
    control_parameters = get_control_parameters()
    filter_on_input = AlferesFilter(
        input_data=data,
        algorithm=None,
        signal_model=None,
        uncertainty_model=None,
        control_parameters=control_parameters,
    )

    filter_add_array = AlferesFilter(
        input_data=None,
        algorithm=None,
        signal_model=None,
        uncertainty_model=None,
        control_parameters=control_parameters,
    )
    filter_add_array.add_array_to_input(data)

    filter_add_individual_array_item = AlferesFilter(
        input_data=None,
        algorithm=None,
        signal_model=None,
        uncertainty_model=None,
        control_parameters=control_parameters,
    )
    for row in data:
        filter_add_individual_array_item.add_array_to_input(row)

    try:
        np.testing.assert_array_equal(
            filter_on_input.input_data, filter_add_array.input_data
        )
        np.testing.assert_array_equal(
            filter_on_input.input_data, filter_add_individual_array_item.input_data
        )
    except AssertionError:
        assert False
    assert True


@pytest.mark.parametrize(
    "outlier,steps_back,warmup,succeeds",
    [
        (1, 5, 2, True),  # normal run, back > max outlier
        (5, 5, 2, True),  # normal run, back=max outliers
        (6, 3, 2, True),  # normal run, back < max outliers
        (7, 3, 0, True),  # normal run, no warmup
        (1, 5, 0, True),  # no warmup
        (0, 5, 2, False),  # immediately triggers
        (1, 0, 2, True),  # goes back 0 steps, with warmup
        # (should just continue without triggering backward passes)
        (1, 0, 0, True),  # goes back zero steps, no warmup
    ],
)
def test_alferes_filter_in_batch(
    outlier: int, steps_back: int, warmup: int, succeeds: bool
):
    # initialize models
    signal_model = get_model("signal", order=3, forgetting_factor=0.25)
    error_model = get_model("uncertainty", order=3, forgetting_factor=0.25)
    control_parameters = get_control_parameters(outlier, steps_back, warmup)
    # prepare data
    signal_name = "dirty sine jump"
    raw_data = get_data(signal_name).to_numpy()

    try:
        filter_obj = AlferesFilter(
            algorithm=AlferesAlgorithm(),
            signal_model=signal_model,
            uncertainty_model=error_model,
            control_parameters=control_parameters,
        )
        filter_obj.add_array_to_input(raw_data)
        filter_obj.calibrate_models(raw_data[: len(raw_data) // 5])

        filter_obj.update_filter()
        df = filter_obj.to_dataframe()
        plotter = UnivariatePlotter(signal_name=signal_name, df=df)
        plotter.plot_outlier_results(title=f"Smoother results: {signal_name}").show()
    except ValueError as e:
        print(e)
        assert not succeeds
    # if you got here, it worked
    assert True


@pytest.mark.parametrize(
    "outlier,steps_back,warmup,succeeds",
    [
        (1, 5, 2, True),  # normal run, back > max outlier
    ],
)
def test_alferes_in_bits(outlier: int, steps_back: int, warmup: int, succeeds: bool):
    # initialize models
    signal_model = get_model("signal", order=3, forgetting_factor=0.25)
    error_model = get_model("uncertainty", order=3, forgetting_factor=0.25)
    control_parameters = get_control_parameters(outlier, steps_back, warmup)
    # prepare data
    signal_name = "dirty sine jump"
    raw_data = get_data(signal_name).to_numpy()
    try:
        filter_obj = AlferesFilter(
            algorithm=AlferesAlgorithm(),
            signal_model=signal_model,
            uncertainty_model=error_model,
            control_parameters=control_parameters,
        )
        filter_obj.calibrate_models(raw_data[: len(raw_data) // 5])

        for row in raw_data:
            filter_obj.add_array_to_input(row)
            filter_obj.update_filter()

        df = filter_obj.to_dataframe()
        df.to_csv("tests/test_filter_results.csv")
        plotter = UnivariatePlotter(signal_name=signal_name, df=df)
        plotter.plot_outlier_results(title=f"Smoother results: {signal_name}").show()
        succeeded = True
    except Exception:
        succeeded = False
    assert succeeds is succeeded


def test_kernel_smoother_in_batch():
    should_succeed = True
    # initialize models
    control_parameters = {"size": 2}
    # prepare data
    signal_name = "dirty sine jump"
    raw_data = get_data(signal_name).to_numpy()
    try:
        filter_obj = HKernelSmoother(
            algorithm=None,
            signal_model=None,
            uncertainty_model=None,
            control_parameters=control_parameters,
        )
        filter_obj.add_array_to_input(raw_data)
        filter_obj.update_filter()
        df = filter_obj.to_dataframe()
        plotter = UnivariatePlotter(signal_name=signal_name, df=df)
        plotter.plot_outlier_results(title=f"Smoother results: {signal_name}").show()
        succeeded = True
    except Exception:
        succeeded = False
    assert should_succeed is succeeded
