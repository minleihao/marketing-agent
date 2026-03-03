from strands.models import BedrockModel

def load_model():
    return BedrockModel(
        # Use the inference profile style identifier with regional prefix
        model_id="us.amazon.nova-micro-v1:0",
        max_tokens=2048,
        temperature=0.7,
        top_p=0.9,
    )