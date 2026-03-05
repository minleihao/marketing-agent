from strands.models import BedrockModel

DEFAULT_MODEL_ID = "us.anthropic.claude-sonnet-4-6"
DEFAULT_MAX_TOKENS = 8192


def load_model(model_id: str = DEFAULT_MODEL_ID):
    kwargs = {
        "model_id": model_id,
        "max_tokens": DEFAULT_MAX_TOKENS,
        "temperature": 0.7,
        "top_p": 0.9,
    }
    # Claude Sonnet 4.6 profile rejects requests that include both temperature and top_p.
    if "claude-sonnet-4-6" in model_id:
        kwargs.pop("top_p", None)
    return BedrockModel(
        # Use the inference profile style identifier with regional prefix
        **kwargs,
    )
