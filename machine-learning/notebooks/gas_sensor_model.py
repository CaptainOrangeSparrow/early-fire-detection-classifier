from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Deque, Dict, Iterable, List, Optional
import time
import numpy as np


@dataclass
class DetectionResult:
    sample_index: int
    is_calibrated: bool
    abnormal: bool
    fire_score: float
    adaptive_score: float
    threshold: float
    persistence_count: int
    pca_score: float
    delta_score: float
    pc1: float
    pc2: float
    pc3: float
    baseline_mean: float
    baseline_std: float


@dataclass
class FireDetectorConfig:
    # these is the signal inputs used at runtime
    feature_cols: List[str] = field(default_factory=lambda: [
        "adc0_ch0",
        "adc0_ch1",
        "adc0_ch2",
        "adc1_ch0",
        "adc1_ch1",
        "adc1_ch2",
        "hdc_temp",
        "hdc_humidity",
        "co2_ppm",
        "co_ppm",
    ])

    sample_rate_hz: float = 25.0

    # Calibration
    min_calibration_samples: int = 250   # about 10 seconds at 25 Hz

    # Fire score
    delta_weight: float = 8.0

    # Adaptive baseline
    baseline_window: int = 75           # about 10 seconds is 250
    threshold_sigma: float = 1.5         # 3.0 originally
    persistence_samples: int = 20        # ~0.8 seconds at 25 Hz
    freeze_baseline_when_alarm: bool = True

    # have this here so we don't divide by zero
    eps: float = 1e-6


class RealTimeFireDetector:
    """
    Jetson-friendly real-time fire detector.

    Overall flow of pipepline:
        raw sample
          - normalize using calibration mean/std
          - PCA projection (top 3 components)
          - pca_score = |PC1| + |PC2| + |PC3|
          - delta_score = sum(|z_t - z_{t-1}|)
          - fire_score = pca_score + delta_weight * delta_score
          - adaptive z-score on fire_score
          - persistence logic
    """

    def __init__(self, config: Optional[FireDetectorConfig] = None) -> None:
        self.cfg = config or FireDetectorConfig()
        self.reset()

    def reset(self) -> None:
        self.sample_index = 0
        self.is_calibrated = False

        self.sensor_mean: Optional[np.ndarray] = None
        self.sensor_std: Optional[np.ndarray] = None
        self.pca_components: Optional[np.ndarray] = None  # shape is (3, n_features)

        self.prev_z: Optional[np.ndarray] = None
        self.fire_score_window: Deque[float] = deque(maxlen=self.cfg.baseline_window)
        self.persistence_count = 0

        self.calibration_buffer: List[np.ndarray] = []

    def _extract_vector(self, sample: Dict[str, float]) -> np.ndarray:
        try:
            values = [float(sample[col]) for col in self.cfg.feature_cols]
        except KeyError as exc:
            raise KeyError(
                f"Missing required key {exc}. Expected: {self.cfg.feature_cols}"
            ) from exc

        return np.asarray(values, dtype=np.float64)

    def add_calibration_sample(self, sample: Dict[str, float]) -> int:
        x = self._extract_vector(sample)
        self.calibration_buffer.append(x)
        return len(self.calibration_buffer)

    def calibrate(self, calibration_samples: Optional[Iterable[Dict[str, float]]] = None) -> None:
        """
        Learn:
        - per-sensor mean/std
        - PCA basis (top 3)
        - initial fire_score baseline from room-normal data

        Pass either:
        - calibration_samples iterable, or
        - use samples already added with add_calibration_sample()
        """
        if calibration_samples is not None:
            self.calibration_buffer = [self._extract_vector(s) for s in calibration_samples]

        if len(self.calibration_buffer) < self.cfg.min_calibration_samples:
            raise ValueError(
                f"Need at least {self.cfg.min_calibration_samples} calibration samples, "
                f"got {len(self.calibration_buffer)}."
            )

        X = np.vstack(self.calibration_buffer)  # (N, D)

        # Normalize data
        mean = X.mean(axis=0)
        std = X.std(axis=0, ddof=0)
        std = np.where(std < self.cfg.eps, 1.0, std)

        Z = (X - mean) / std

        # PCA by covariance eigendecomposition
        cov = np.cov(Z, rowvar=False)
        eigvals, eigvecs = np.linalg.eigh(cov)
        order = np.argsort(eigvals)[::-1]
        eigvecs = eigvecs[:, order]

        # we get top 3 components
        components = eigvecs[:, :3].T  # (3, D)

        # use sign convention
        for i in range(components.shape[0]):
            j = np.argmax(np.abs(components[i]))
            if components[i, j] < 0:
                components[i] *= -1.0

        # building initial fire-score history from calibration set
        prev_z = None
        initial_scores: List[float] = []

        for z in Z:
            pcs = components @ z
            pca_score = float(np.abs(pcs[0]) + np.abs(pcs[1]) + np.abs(pcs[2]))

            if prev_z is None:
                delta_score = 0.0
            else:
                delta_score = float(np.abs(z - prev_z).sum())

            fire_score = pca_score + self.cfg.delta_weight * delta_score
            initial_scores.append(fire_score)
            prev_z = z

        self.sensor_mean = mean
        self.sensor_std = std
        self.pca_components = components
        self.prev_z = prev_z
        self.fire_score_window = deque(
            initial_scores[-self.cfg.baseline_window:],
            maxlen=self.cfg.baseline_window
        )
        self.persistence_count = 0
        self.is_calibrated = True
        self.sample_index = 0

    def _baseline_stats(self) -> tuple[float, float]:
        if len(self.fire_score_window) < 2:
            return 0.0, 1.0

        arr = np.asarray(self.fire_score_window, dtype=np.float64)
        mean = float(arr.mean())
        std = float(arr.std(ddof=0))
        std = max(std, self.cfg.eps)
        return mean, std

    def process_sample(self, sample: Dict[str, float]) -> DetectionResult:
        if not self.is_calibrated:
            raise RuntimeError("Detector is not calibrated. Call calibrate() first.")

        assert self.sensor_mean is not None
        assert self.sensor_std is not None
        assert self.pca_components is not None

        x = self._extract_vector(sample)

        # Normalize
        z = (x - self.sensor_mean) / self.sensor_std

        # PCA scores
        pcs = self.pca_components @ z
        pc1, pc2, pc3 = float(pcs[0]), float(pcs[1]), float(pcs[2])
        pca_score = abs(pc1) + abs(pc2) + abs(pc3)

        # Delta score
        if self.prev_z is None:
            delta_score = 0.0
        else:
            delta_score = float(np.abs(z - self.prev_z).sum())

        # Combined fire score
        fire_score = float(pca_score + self.cfg.delta_weight * delta_score)

        baseline_mean, baseline_std = self._baseline_stats()
        adaptive_score = (fire_score - baseline_mean) / baseline_std

        instant_abnormal = adaptive_score > self.cfg.threshold_sigma

        if instant_abnormal:
            self.persistence_count += 1
        else:
            self.persistence_count = 0

        confirmed_abnormal = self.persistence_count >= self.cfg.persistence_samples

        # Freeze baseline during active alarm if desired
        should_update_baseline = True
        if self.cfg.freeze_baseline_when_alarm and confirmed_abnormal:
            should_update_baseline = False

        if should_update_baseline:
            self.fire_score_window.append(fire_score)

        self.prev_z = z
        self.sample_index += 1

        return DetectionResult(
            sample_index=self.sample_index,
            is_calibrated=self.is_calibrated,
            abnormal=confirmed_abnormal,
            fire_score=fire_score,
            adaptive_score=adaptive_score,
            threshold=self.cfg.threshold_sigma,
            persistence_count=self.persistence_count,
            pca_score=pca_score,
            delta_score=delta_score,
            pc1=pc1,
            pc2=pc2,
            pc3=pc3,
            baseline_mean=baseline_mean,
            baseline_std=baseline_std,
        )

    def export_params(self) -> Dict[str, np.ndarray]:
        if not self.is_calibrated:
            raise RuntimeError("Detector is not calibrated.")

        assert self.sensor_mean is not None
        assert self.sensor_std is not None
        assert self.pca_components is not None

        return {
            "feature_cols": np.array(self.cfg.feature_cols, dtype=object),
            "sensor_mean": self.sensor_mean.copy(),
            "sensor_std": self.sensor_std.copy(),
            "pca_components": self.pca_components.copy(),
        }


def init_detector(
    calibration_stream: Iterable[Dict[str, float]],
    config: Optional[FireDetectorConfig] = None,
) -> RealTimeFireDetector:
    """
    One-shot initialization:
    - wee collect baseline room-normal samples
    - calibrate detector here
    """
    detector = RealTimeFireDetector(config=config)
    detector.calibrate(calibration_stream)
    return detector


def run_stream(
    detector: RealTimeFireDetector,
    sample_stream: Iterable[Dict[str, float]],
    verbose: bool = True,
) -> None:
    """
    Streaming loop for already-calibrated detector.
    """
    for sample in sample_stream:
        result = detector.process_sample(sample)

        if verbose:
            state = "ABNORMAL" if result.abnormal else "NORMAL"
            print(
                f"[{result.sample_index:06d}] {state} | "
                f"fire_score={result.fire_score:.3f} | "
                f"adaptive_score={result.adaptive_score:.3f} | "
                f"pca_score={result.pca_score:.3f} | "
                f"delta_score={result.delta_score:.3f} | "
                f"persist={result.persistence_count}"
            )


if __name__ == "__main__":
    pass