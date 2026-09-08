from __future__ import annotations

import argparse
import json
from pathlib import Path

from .scoring import score_deal
from .store import CommerceStore
from .tiktok import normalize_product


def ingest_payload(payload: dict, store: CommerceStore | None = None):
    store = store or CommerceStore()
    item = normalize_product(payload)
    history = store.price_history(item.source, item.product_id)
    score = score_deal(item, history)
    observation_id = store.record(item)
    return observation_id, item, score


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest a captured TikTok Shop product payload")
    parser.add_argument("json_file", type=Path)
    args = parser.parse_args()
    payload = json.loads(args.json_file.read_text(encoding="utf-8"))
    observation_id, item, score = ingest_payload(payload)
    print(f"Recorded #{observation_id}: {item.title}")
    print(f"Effective price: {item.currency} {item.effective_price:.2f}")
    print(f"Pulse Deal Score: {score.total}/100")
    for reason in score.reasons:
        print(f"- {reason}")


if __name__ == "__main__":
    main()
