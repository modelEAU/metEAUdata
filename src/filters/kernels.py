from dataclasses import dataclass
from typing import Tuple, Union

import numpy as np
import numpy.typing as npt
from scipy.optimize import minimize

from filters import utilities
from filters.exceptions import (InputShapeException, InvalidHorizonException,
                                WrongDimensionsError)
from filters.protocols import Kernel, Parameters
from filters.utilities import rmse


def auto_regresive(
    current_value: float, preceding_stat: float, forgetting_factor: float
) -> float:
    return forgetting_factor * current_value + (1 - forgetting_factor) * preceding_stat


def to_1item_array(item: Union[float, npt.NDArray]) -> npt.NDArray:
    if isinstance(item, float):
        return np.array([item])
    if len(item) == 1:
        return item.reshape(
            -1,
        )
    raise WrongDimensionsError(
        f"Passed an item that is longer than one element: {item}"
    )


@dataclass
class EwmaKernel3(Kernel):
    forgetting_factor: float

    def __post_init__(self):
        self.previous_s_stats = np.full(shape=3, fill_value=0)
        self.current_s_stats = np.full(shape=3, fill_value=0)
        self.input_shape: Tuple = (1,)
        self.max_prediction_horizon: int = 1  # feature of the prediciton algorithm
        if not (0 <= self.forgetting_factor <= 1):
            raise ValueError(
                f"forgetting factor should be between 0 and 1, received {self.forgetting_factor}"
            )
        self.initialized = False

    def compute_a(self) -> float:
        s1, s2, s3 = (
            self.current_s_stats[0],
            self.current_s_stats[1],
            self.current_s_stats[2],
        )
        return 3 * s1 - 3 * s2 + s3

    def compute_b(self) -> float:
        s1, s2, s3 = (
            self.current_s_stats[0],
            self.current_s_stats[1],
            self.current_s_stats[2],
        )
        forgetting_factor = self.forgetting_factor
        factor = forgetting_factor / (2 * (forgetting_factor - 1) ** 2)
        term_1 = (6 - 5 * forgetting_factor) * s1
        term_2 = -2 * (5 - 4 * forgetting_factor) * s2
        term_3 = (4 - 3 * forgetting_factor) * s3
        return factor * (term_1 + term_2 + term_3)

    def compute_c(self) -> float:
        s1, s2, s3 = (
            self.current_s_stats[0],
            self.current_s_stats[1],
            self.current_s_stats[2],
        )
        forgetting_factor = self.forgetting_factor
        factor = (forgetting_factor / (forgetting_factor - 1)) ** 2
        return factor * (s1 - 2 * s2 + s3)

    def compute_current_s_stats(self, current_value: float) -> npt.NDArray:
        previous_s1, previous_s2, previous_s3 = (
            self.previous_s_stats[0],
            self.previous_s_stats[1],
            self.previous_s_stats[2],
        )
        s1 = auto_regresive(current_value, previous_s1, self.forgetting_factor)
        s2 = auto_regresive(s1, previous_s2, self.forgetting_factor)
        s3 = auto_regresive(s2, previous_s3, self.forgetting_factor)
        result = np.array([s1, s2, s3])
        self.current_s_stats = result
        return result

    def update_s_stats(self, current_value: float) -> None:
        self.previous_s_stats = self.current_s_stats
        self.current_s_stats = self.compute_current_s_stats(current_value)

    def initialize_s_stats(self, seed_value: float) -> None:
        self.previous_s_stats = np.full(shape=3, fill_value=seed_value)
        self.current_s_stats = np.full(shape=3, fill_value=seed_value)

    def initialize(self, initial_values: npt.NDArray) -> None:
        self.initialize_s_stats(seed_value=initial_values[0])
        self.initialized = True

    def reset_state(self):
        self.__post_init__()

    def _predict_step(self, input_data: npt.NDArray, horizon: int) -> npt.NDArray:
        if not utilities.shapes_are_equivalent(input_data.shape, self.input_shape):
            raise InputShapeException(
                f"Prediction step requires shape (1,) and was given {input_data.shape}."
            )
        if not self.initialized:
            self.initialize(to_1item_array(input_data[0]))
        self.update_s_stats(input_data[0])
        a = self.compute_a()
        b = self.compute_b()
        c = self.compute_c()
        result = np.array([a + b + c / 2])  # predicted value
        return result[:horizon]

    def predict(self, input_data: npt.NDArray, horizon: int) -> npt.NDArray:
        if horizon > self.max_prediction_horizon:
            raise InvalidHorizonException(
                f"This kernel can only predict up to {self.max_prediction_horizon}, and was asked to predict {horizon}."
            )
        if len(input_data.shape) < 2:
            input_data = input_data.reshape(-1, 1)
        n_steps = input_data.shape[0]
        result_array = np.full(shape=(n_steps, horizon), fill_value=np.nan)
        for i in range(n_steps):
            result_array[i] = self._predict_step(input_data[i, :], horizon=horizon)
        return result_array

    def calibrate(
        self, input_data: npt.NDArray, initial_guesses: Parameters
    ) -> npt.NDArray:
        self.forgetting_factor = initial_guesses.get("forgetting_factor", self.forgetting_factor)
        forgetting_factor = optimize_forgetting_factor(input_data, self)
        self.reset_state()
        self.forgetting_factor = forgetting_factor
        return self.predict(input_data[1:], horizon=1)


@dataclass
class EwmaKernel1(Kernel):
    forgetting_factor: float

    def __post_init__(self):
        self.last_prediction = np.full(shape=1, fill_value=0)
        self.input_shape: Tuple = (1,)
        self.max_prediction_horizon: int = 1  # feature of the prediction algorithm
        if not (0 <= self.forgetting_factor <= 1):
            raise ValueError(
                f"forgetting factor should be between 0 and 1, received {self.forgetting_factor}"
            )
        self.initialized = False

    def reset_state(self):
        self.__post_init__()

    def initialize(self, initial_values: npt.NDArray) -> None:
        self.last_prediction = initial_values
        self.initialized = True

    def _predict_step(self, input_data: npt.NDArray, horizon: int) -> npt.NDArray:
        if not utilities.shapes_are_equivalent(input_data.shape, self.input_shape):
            raise InputShapeException(
                f"Prediction step requires shape (1,) and was given {input_data.shape}."
            )
        if not self.initialized:
            self.initialize(to_1item_array(input_data[0]))
        prediction = to_1item_array(
            auto_regresive(input_data[0], self.last_prediction, self.forgetting_factor)
        )
        self.last_prediction = prediction
        return prediction[:horizon]

    def predict(self, input_data: npt.NDArray, horizon: int) -> npt.NDArray:
        if horizon > self.max_prediction_horizon:
            raise InvalidHorizonException(
                f"This kernel can only predict up to {self.max_prediction_horizon}, and was asked to predict {horizon}."
            )
        if len(input_data.shape) < 2:
            input_data = input_data.reshape(-1, 1)
        n_steps = input_data.shape[0]
        result_array = np.full(shape=(n_steps, horizon), fill_value=np.nan)
        for i in range(n_steps):
            result_array[i] = self._predict_step(input_data[i, :], horizon=horizon)
        return result_array

    def calibrate(
        self, input_data: npt.NDArray, initial_guesses: Parameters
    ) -> npt.NDArray:
        self.forgetting_factor = initial_guesses.get("forgetting_factor", self.forgetting_factor)
        forgetting_factor = optimize_forgetting_factor(input_data, self)
        self.reset_state()
        self.forgetting_factor = forgetting_factor
        return self.predict(input_data[1:], horizon=1)


def objective_forgetting_factor(
    log_transformed: npt.NDArray,
    input_values: npt.NDArray,
    kernel: Union[EwmaKernel1, EwmaKernel3],
) -> float:
    forgetting_factor = np.exp(-(log_transformed[0] ** 2))
    kernel.reset_state()
    kernel.forgetting_factor = forgetting_factor
    predictions = kernel.predict(input_values[:-1], horizon=1)
    return rmse(input_values[2:], predictions)


def optimize_forgetting_factor(
    input_data: npt.NDArray, kernel: Union[EwmaKernel1, EwmaKernel3]
) -> float:
    # The only parameter to optimize is the forgetting factor
    log_initial_guess = np.sqrt(-np.log(kernel.forgetting_factor))
    result = minimize(
        objective_forgetting_factor,
        x0=log_initial_guess,
        args=(input_data, kernel),
        method="Nelder-Mead",
    )
    log_forgetting_factor = result.x[0]
    return np.exp(-(log_forgetting_factor**2))
