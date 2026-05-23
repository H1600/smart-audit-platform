"""ML-based account classification using jieba + TfidfVectorizer + Naive Bayes.

Mirrors the approach from Gandedong/audit-python- 'sklearn自动建立会计分录'.
"""
from __future__ import annotations

import json
import logging
import os
import pickle
from pathlib import Path
from typing import Any

from .settings import STORAGE_DIR

logger = logging.getLogger(__name__)

MODEL_DIR = STORAGE_DIR / "models"
MODEL_DIR.mkdir(parents=True, exist_ok=True)

MODEL_PATH = MODEL_DIR / "account_clf.pkl"
VECTORIZER_PATH = MODEL_DIR / "account_vect.pkl"
META_PATH = MODEL_DIR / "account_meta.json"

# ── Tokenizer: jieba ──────────────────────────────────────────────
_jieba_available = False
try:
    import jieba

    _jieba_available = True
except ImportError:
    logger.warning("jieba not installed; account classifier will use character-level fallback")


def _tokenize(text: str) -> str:
    """Tokenize Chinese text using jieba if available, else character-level."""
    if _jieba_available:
        return " ".join(jieba.cut(str(text or "")))
    return " ".join(str(text or ""))


# ── Model loading / saving ────────────────────────────────────────
def classifier_exists() -> bool:
    return MODEL_PATH.exists() and VECTORIZER_PATH.exists()


def get_model_meta() -> dict[str, Any]:
    if META_PATH.exists():
        try:
            return json.loads(META_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"trained": False, "samples": 0, "accuracy": 0.0, "classes": []}


def load_classifier() -> tuple[Any, Any] | None:
    """Return (vectorizer, classifier) or None if no model exists."""
    if not classifier_exists():
        return None
    try:
        with VECTORIZER_PATH.open("rb") as f:
            vect = pickle.load(f)
        with MODEL_PATH.open("rb") as f:
            clf = pickle.load(f)
        return vect, clf
    except Exception as exc:
        logger.warning("Failed to load classifier: %s", exc)
        return None


def save_classifier(vect: Any, clf: Any, meta: dict[str, Any]) -> None:
    with VECTORIZER_PATH.open("wb") as f:
        pickle.dump(vect, f)
    with MODEL_PATH.open("wb") as f:
        pickle.dump(clf, f)
    META_PATH.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")


# ── Training ──────────────────────────────────────────────────────
def train_classifier(
    summaries: list[str],
    labels: list[str],
) -> dict[str, Any]:
    """Train a MultinomialNB classifier on (summary, account_label) pairs.

    Returns metadata dict with accuracy and class info.
    """
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.naive_bayes import MultinomialNB
    from sklearn.model_selection import cross_val_score

    if not summaries or not labels or len(summaries) != len(labels):
        raise ValueError("训练数据无效：摘要与标签数量不一致或为空")

    tokens = [_tokenize(s) for s in summaries]

    vect = TfidfVectorizer(
        analyzer="word",
        token_pattern=r"(?u)\b\w+\b",
        max_features=5000,
        ngram_range=(1, 2),
    )
    X = vect.fit_transform(tokens)

    clf = MultinomialNB(alpha=0.1)
    clf.fit(X, labels)

    # Cross-validation accuracy
    try:
        scores = cross_val_score(clf, X, labels, cv=min(5, len(set(labels))), scoring="accuracy")
        accuracy = round(float(scores.mean()), 4)
    except Exception:
        accuracy = round(float(clf.score(X, labels)), 4)

    classes = sorted(set(labels))
    meta: dict[str, Any] = {
        "trained": True,
        "samples": len(summaries),
        "accuracy": accuracy,
        "classes": classes,
    }
    save_classifier(vect, clf, meta)
    logger.info("Classifier trained: %d samples, accuracy=%.4f, %d classes", len(summaries), accuracy, len(classes))
    return meta


# ── Prediction ────────────────────────────────────────────────────
def predict_account(summary: str) -> tuple[str, float]:
    """Predict account name from summary text.

    Returns (predicted_label, confidence).
    Falls back to keyword matching if no model is available.
    """
    pair = load_classifier()
    if pair is None:
        return _keyword_fallback(summary)

    vect, clf = pair
    tokens = [_tokenize(summary)]
    X = vect.transform(tokens)
    probs = clf.predict_proba(X)[0]
    best_idx = int(probs.argmax())
    label = str(clf.classes_[best_idx])
    confidence = round(float(probs[best_idx]), 4)
    return label, confidence


def predict_account_with_code(summary: str, account_map: dict[str, tuple[str, str]] | None = None) -> tuple[str, str, float]:
    """Predict (code, name, confidence)."""
    name, conf = predict_account(summary)
    if account_map and name in account_map:
        code, std_name = account_map[name]
    else:
        code, std_name = _keyword_fallback(summary)
    return code, std_name, conf


# ── Keyword fallback (original ACCOUNT_HINTS logic) ────────────────
_KEYWORD_MAP = {
    "现金": ("1001", "库存现金"),
    "银行": ("1002", "银行存款"),
    "存款": ("1002", "银行存款"),
    "应收": ("1122", "应收账款"),
    "应付": ("2202", "应付账款"),
    "借款": ("2202", "应付账款"),
    "收入": ("6001", "主营业务收入"),
    "销售": ("6001", "主营业务收入"),
    "成本": ("6401", "主营业务成本"),
    "采购": ("6401", "主营业务成本"),
    "费用": ("6602", "管理费用"),
    "工资": ("6602", "管理费用"),
    "办公": ("6602", "管理费用"),
    "差旅": ("6602", "管理费用"),
    "招待": ("6602", "管理费用"),
    "折旧": ("6602", "管理费用"),
    "摊销": ("6602", "管理费用"),
    "税金": ("6602", "管理费用"),
    "税费": ("6602", "管理费用"),
    "房租": ("6602", "管理费用"),
    "快递": ("6602", "管理费用"),
    "水电": ("6602", "管理费用"),
    "物业": ("6602", "管理费用"),
    "维修": ("6602", "管理费用"),
    "咨询": ("6602", "管理费用"),
    "审计": ("6602", "管理费用"),
    "服务费": ("6602", "管理费用"),
    "手续费": ("6603", "财务费用"),
    "利息": ("6603", "财务费用"),
    "汇兑": ("6603", "财务费用"),
    "固定资产": ("1601", "固定资产"),
    "无形资产": ("1701", "无形资产"),
    "预付": ("1123", "预付账款"),
    "预收": ("2203", "预收账款"),
    "其他应收": ("1221", "其他应收款"),
    "其他应付": ("2241", "其他应付款"),
    "实收资本": ("4001", "实收资本"),
    "资本公积": ("4002", "资本公积"),
    "盈余公积": ("4101", "盈余公积"),
    "利润分配": ("4104", "利润分配"),
    "本年利润": ("4103", "本年利润"),
}


def _keyword_fallback(summary: str) -> tuple[str, str]:
    """Match summary against keyword map, return (code, name)."""
    if not summary:
        return ("", "未映射")
    text = str(summary)
    # Longest match first
    matches = []
    for keyword, (code, name) in _KEYWORD_MAP.items():
        if keyword in text:
            matches.append((len(keyword), code, name))
    if matches:
        matches.sort(key=lambda x: x[0], reverse=True)
        return matches[0][1], matches[0][2]
    return ("", "未映射")


def get_keyword_map() -> dict[str, tuple[str, str]]:
    return dict(_KEYWORD_MAP)


# ── Initialization ────────────────────────────────────────────────
os.environ.setdefault("JIEBA_DISABLE_PARALLEL", "1")
