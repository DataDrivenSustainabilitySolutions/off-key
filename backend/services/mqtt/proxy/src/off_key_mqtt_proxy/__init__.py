"""
MQTT proxy service.

Subscribes to the internal broker's ingress topics of the saved collection
catalogue and writes the received telemetry to TimescaleDB.
"""
