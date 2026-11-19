import math

from rest_framework import serializers


class LocationSerializer(serializers.Serializer):
    lat = serializers.FloatField(min_value=-90, max_value=90)
    lon = serializers.FloatField(min_value=-180, max_value=180)

    def validate(self, attrs):
        if not math.isfinite(attrs["lat"]) or not math.isfinite(attrs["lon"]):
            raise serializers.ValidationError("Coordinates must be finite numbers")
        return attrs


class FuelPlanRequestSerializer(serializers.Serializer):
    start = serializers.JSONField()
    finish = serializers.JSONField()

    def validate_start(self, value):
        return self._validate_location(value, "start")

    def validate_finish(self, value):
        return self._validate_location(value, "finish")

    @staticmethod
    def _validate_location(value, field):
        if isinstance(value, str):
            value = value.strip()
            if value:
                return value
            raise serializers.ValidationError("Provide a non-empty US place name")
        if isinstance(value, dict):
            serializer = LocationSerializer(data=value)
            if serializer.is_valid():
                return serializer.validated_data
            raise serializers.ValidationError(serializer.errors)
        raise serializers.ValidationError("Expected a place name or an object with lat and lon")
