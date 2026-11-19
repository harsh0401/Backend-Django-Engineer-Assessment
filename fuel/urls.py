from django.urls import path

from fuel.views import (
    FuelPlanCollectionView,
    FuelPlanMapQueryView,
    FuelPlanMapView,
    FuelPlanRetrieveView,
)

urlpatterns = [
    path("fuel-plans/", FuelPlanCollectionView.as_view(), name="fuel-plan-list"),
    path("fuel-plans/map/", FuelPlanMapQueryView.as_view(), name="fuel-plan-map-query"),
    path("fuel-plans/<uuid:plan_id>/", FuelPlanRetrieveView.as_view(), name="fuel-plan-detail"),
    path("fuel-plans/<uuid:plan_id>/map/", FuelPlanMapView.as_view(), name="fuel-plan-map"),
]
