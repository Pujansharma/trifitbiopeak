"""Shared health observation value serializer for analytics and timeline."""

from wearables.models import HealthObservation


def observation_value(observation: HealthObservation) -> dict:
    if observation.numeric_value is not None:
        return {"type": "number", "value": observation.numeric_value}
    if observation.text_value:
        return {"type": "text", "value": observation.text_value}
    if observation.boolean_value is not None:
        return {"type": "boolean", "value": observation.boolean_value}
    return {"type": "unavailable"}
