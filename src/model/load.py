from strands.models import BedrockModel

DEFAULT_MODEL_ID = "us.amazon.nova-micro-v1:0"


def load_model(model_id: str = DEFAULT_MODEL_ID):
    return BedrockModel(
        # Use the inference profile style identifier with regional prefix
        model_id=model_id,
        max_tokens=2048,
        temperature=0.7,
        top_p=0.9,
    )
