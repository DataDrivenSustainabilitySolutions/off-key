"""
MQTT proxy service.

Subscribes to the internal EMQX ingress topics of the saved collection
catalogue and writes the received telemetry to TimescaleDB.
"""
