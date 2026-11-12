"""Expected value: one feature fitted from the others, given as its residual.

The fitted-once step solves least squares on the training window; the
continuous one follows every observation with Aberrant's recursive least
squares. Both hold a constant beside one weight per feature the target is
expected from.
"""

from contextlib import contextmanager
from copy import deepcopy

import numpy as np
from aberrant.base.readiness import Readiness
from aberrant.forecast import RLSRegressor


class ExpectedValue:
    """Least squares on training data. The first column is the target.

    Inputs that are constant or repeat each other share their weight, the
    smallest that fits, so training data never fails to fit.
    """

    def fit_transform(self, matrix: np.ndarray) -> np.ndarray:
        inputs, target = matrix[:, 1:], matrix[:, 0]
        # Centred, so the constant is the target's mean and scales stay apart.
        self.centre = inputs.mean(axis=0)
        self.level = float(target.mean())
        self.weights = np.linalg.lstsq(
            inputs - self.centre, target - self.level, rcond=None
        )[0]
        return self.transform(matrix)

    def transform(self, matrix: np.ndarray) -> np.ndarray:
        expected = self.level + (matrix[:, 1:] - self.centre) @ self.weights
        return (matrix[:, 0] - expected)[:, None]


class OnlineExpectedValue:
    """Recursive least squares; the residual of the fit as it stands.

    Scoring reads the fit before the observation is learned. In a learning
    pass Aberrant transforms after the update, as for every continuous step.
    """

    def __init__(self, target: str, name: str, inputs: int, forgetting: float):
        self.target = target
        self.name = name
        # One observation per coefficient, and one more to measure an error.
        self.required = inputs + 2
        self.regressor = RLSRegressor(forgetting=forgetting)

    @property
    def readiness(self) -> Readiness:
        seen = min(self.regressor.n_samples_seen, self.required)
        return Readiness(self.regressor.is_ready, seen, self.required)

    def _inputs(self, data: dict[str, float]) -> dict[str, float]:
        return {name: value for name, value in data.items() if name != self.target}

    def learn_one(self, data: dict[str, float]) -> None:
        self.regressor.learn_one(self._inputs(data), data[self.target])

    def transform_one(self, data: dict[str, float]) -> dict[str, float]:
        expected = self.regressor.predict_one(self._inputs(data))
        if expected is None:
            raise RuntimeError("Expected value has not learned enough observations")
        return {self.name: data[self.target] - expected.mean[0]}

    @contextmanager
    def learning_transaction(self, _data: dict[str, float]):
        """Restore the fit when this or a later step rejects the observation."""
        previous = deepcopy(self.regressor)
        try:
            yield
        except BaseException:
            self.regressor = previous
            raise
