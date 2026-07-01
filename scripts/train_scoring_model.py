"""
Train an ML model to predict pour viability from weather conditions.

Uses historical job data + weather to learn which conditions actually
lead to good vs problematic jobs, rather than relying solely on
hardcoded ACI thresholds.

The model outputs a probability (0-1) that a given set of conditions
is viable for pouring, which supplements the rule-based scoring.
"""

import os
import sys
import json
import logging
import pickle
import psycopg2
import psycopg2.extras
import numpy as np

logging.basicConfig(
    level=logging.INFO,
    format='{"time":"%(asctime)s","level":"%(levelname)s","module":"ml","message":"%(message)s"}',
    datefmt="%Y-%m-%dT%H:%M:%S",
)
logger = logging.getLogger("ml")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))
from config import DB_CONFIG

MODEL_PATH = os.path.join(os.path.dirname(__file__), "..", "app", "pour_model.pkl")


def load_training_data():
    """Load daily weather data with pour scores as training labels."""
    conn = psycopg2.connect(**DB_CONFIG)
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("""
            SELECT temp_max_f, temp_min_f, precip_in, wind_max_mph,
                   pour_score
            FROM daily_weather
            WHERE temp_max_f IS NOT NULL
              AND temp_min_f IS NOT NULL
              AND precip_in IS NOT NULL
              AND pour_score IS NOT NULL
        """)
        rows = cur.fetchall()
    conn.close()
    return rows


def prepare_features(rows):
    """Convert rows to numpy arrays for training."""
    X = []
    y = []
    for row in rows:
        features = [
            float(row["temp_max_f"]),
            float(row["temp_min_f"]),
            float(row["temp_max_f"]) - float(row["temp_min_f"]),  # temp range
            float(row["precip_in"]),
            float(row["wind_max_mph"]) if row["wind_max_mph"] else 0,
        ]
        X.append(features)
        y.append(1 if row["pour_score"] == "green" else 0)
    return np.array(X), np.array(y)


class SimpleLogisticRegression:
    """Minimal logistic regression — no sklearn dependency."""

    def __init__(self, lr=0.01, epochs=1000):
        self.lr = lr
        self.epochs = epochs
        self.weights = None
        self.bias = 0
        self.mean = None
        self.std = None
        self.feature_names = ["temp_max_f", "temp_min_f", "temp_range", "precip_in", "wind_max_mph"]

    def _sigmoid(self, z):
        return 1 / (1 + np.exp(-np.clip(z, -500, 500)))

    def _normalize(self, X):
        return (X - self.mean) / (self.std + 1e-8)

    def fit(self, X, y):
        self.mean = X.mean(axis=0)
        self.std = X.std(axis=0)
        X_norm = self._normalize(X)

        n_samples, n_features = X_norm.shape
        self.weights = np.zeros(n_features)
        self.bias = 0

        for epoch in range(self.epochs):
            z = np.dot(X_norm, self.weights) + self.bias
            predictions = self._sigmoid(z)
            dw = (1 / n_samples) * np.dot(X_norm.T, (predictions - y))
            db = (1 / n_samples) * np.sum(predictions - y)
            self.weights -= self.lr * dw
            self.bias -= self.lr * db

            if epoch % 200 == 0:
                loss = -np.mean(y * np.log(predictions + 1e-8) + (1 - y) * np.log(1 - predictions + 1e-8))
                logger.info("Epoch %d — loss: %.4f", epoch, loss)

    def predict_proba(self, X):
        X_norm = self._normalize(X)
        return self._sigmoid(np.dot(X_norm, self.weights) + self.bias)

    def predict(self, X):
        return (self.predict_proba(X) >= 0.5).astype(int)

    def accuracy(self, X, y):
        return np.mean(self.predict(X) == y)

    def feature_importance(self):
        importance = sorted(
            zip(self.feature_names, np.abs(self.weights)),
            key=lambda x: x[1],
            reverse=True,
        )
        return importance


def train():
    logger.info("Loading training data...")
    rows = load_training_data()
    logger.info("Loaded %d weather days", len(rows))

    X, y = prepare_features(rows)
    logger.info("Feature matrix: %s, Labels: %d green / %d not-green",
                X.shape, y.sum(), len(y) - y.sum())

    # Train/test split (80/20)
    split = int(len(X) * 0.8)
    X_train, X_test = X[:split], X[split:]
    y_train, y_test = y[:split], y[split:]

    logger.info("Training on %d samples, testing on %d", len(X_train), len(X_test))

    model = SimpleLogisticRegression(lr=0.1, epochs=2000)
    model.fit(X_train, y_train)

    train_acc = model.accuracy(X_train, y_train)
    test_acc = model.accuracy(X_test, y_test)
    logger.info("Train accuracy: %.3f", train_acc)
    logger.info("Test accuracy: %.3f", test_acc)

    logger.info("Feature importance:")
    for name, weight in model.feature_importance():
        logger.info("  %s: %.4f", name, weight)

    # Save model
    with open(MODEL_PATH, "wb") as f:
        pickle.dump(model, f)
    logger.info("Model saved to %s", MODEL_PATH)

    # Example predictions
    logger.info("Example predictions:")
    examples = [
        [70, 55, 15, 0.0, 5],    # perfect day
        [85, 65, 20, 0.0, 8],    # warm, calm
        [45, 30, 15, 0.2, 15],   # cold, rainy, windy
        [75, 60, 15, 0.5, 20],   # rain + wind
    ]
    for ex in examples:
        prob = model.predict_proba(np.array([ex]))[0]
        logger.info("  temp=%d/%d precip=%.1f wind=%d → %.1f%% viable",
                    ex[0], ex[1], ex[3], ex[4], prob * 100)

    return model


if __name__ == "__main__":
    train()
