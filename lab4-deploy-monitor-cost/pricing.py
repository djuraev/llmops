"""Turn tokens into dollars using prices.yaml."""
import yaml

import bankbot as bb

PRICES = yaml.safe_load((bb.ROOT / "prices.yaml").read_text(encoding="utf-8"))


def cost(model, tokens_in, tokens_out):
    p = PRICES["models"].get(model, PRICES["default"])
    return tokens_in / 1e6 * p["input"] + tokens_out / 1e6 * p["output"]
