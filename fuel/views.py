from uuid import UUID

from django.shortcuts import render
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from fuel.models import FuelPlan
from fuel.serializers import FuelPlanRequestSerializer
from fuel.services.planning import PlanningError, build_fuel_plan


def error_response(
    code: str, message: str, details: dict | None = None, status_code: int = 400
) -> Response:
    return Response(
        {"error": {"code": code, "message": message, "details": details or {}}}, status=status_code
    )


def _validated_request(data):
    serializer = FuelPlanRequestSerializer(data=data)
    if not serializer.is_valid():
        return None, error_response(
            "validation_error", "Invalid fuel-plan request", serializer.errors
        )
    return serializer.validated_data, None


def _compact_output(output):
    route = output["route"]
    geometry = route["geometry"]
    coordinates = geometry["coordinates"]
    if len(coordinates) > 4:
        coordinates = [coordinates[index * (len(coordinates) - 1) // 3] for index in range(4)]
    return {
        **output,
        "route": {**route, "geometry": {**geometry, "coordinates": coordinates}},
    }


def _create_plan(data):
    try:
        output, _ = build_fuel_plan(data["start"], data["finish"])
        return Response(_compact_output(output), status=status.HTTP_201_CREATED)
    except PlanningError as error:
        return error_response(error.code, str(error), error.details, error.status)


class FuelPlanCollectionView(APIView):
    @extend_schema(
        operation_id="create_fuel_plan",
        request=FuelPlanRequestSerializer,
        responses={201: dict},
    )
    def post(self, request):
        data, error = _validated_request(request.data)
        return error or _create_plan(data)

    @extend_schema(
        operation_id="get_fuel_plan_by_query",
        parameters=[],
        responses={201: dict},
    )
    def get(self, request):
        data, error = _validated_request(
            {
                "start": request.query_params.get("start"),
                "finish": request.query_params.get("finish"),
            }
        )
        return error or _create_plan(data)


class FuelPlanRetrieveView(APIView):
    @extend_schema(
        operation_id="retrieve_fuel_plan",
        responses={200: OpenApiTypes.OBJECT},
    )
    def get(self, request, plan_id):
        try:
            plan = FuelPlan.objects.get(id=UUID(str(plan_id)))
        except (FuelPlan.DoesNotExist, ValueError):
            return error_response("plan_not_found", "Fuel plan was not found", {}, 404)
        return Response(_compact_output(plan.output_json))


def _render_map(request, output):
    return render(
        request,
        "fuel/map.html",
        {
            "route": output["route"]["geometry"],
            "stops": output["stops"],
        },
    )


class FuelPlanMapView(APIView):
    @extend_schema(
        operation_id="render_saved_fuel_plan_map",
        responses={
            200: OpenApiResponse(response=OpenApiTypes.STR, description="Standalone HTML map")
        },
    )
    def get(self, request, plan_id):
        try:
            plan = FuelPlan.objects.get(id=UUID(str(plan_id)))
        except (FuelPlan.DoesNotExist, ValueError):
            return error_response("plan_not_found", "Fuel plan was not found", {}, 404)
        return _render_map(request, plan.output_json)


class FuelPlanMapQueryView(APIView):
    @extend_schema(
        operation_id="render_fuel_plan_map_by_query",
        responses={
            200: OpenApiResponse(response=OpenApiTypes.STR, description="Standalone HTML map")
        },
    )
    def get(self, request):
        data, error = _validated_request(
            {
                "start": request.query_params.get("start"),
                "finish": request.query_params.get("finish"),
            }
        )
        if error:
            return error
        try:
            output, _ = build_fuel_plan(data["start"], data["finish"])
            return _render_map(request, output)
        except PlanningError as error:
            return error_response(error.code, str(error), error.details, error.status)
