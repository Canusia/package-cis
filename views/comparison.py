"""Comparison endpoint: one route, every dimension, JSON."""
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response

from cis.services.comparison import build_payload, get_dimension, parse_filters
from cis.utils import CIS_user_only


@api_view(['GET'])
@permission_classes([CIS_user_only])
def comparison_data(request, dimension):
    """Compare up to 3 records of `dimension` across the six metrics.

    Unknown dimension -> 404. Bad filters -> 400.
    """
    dim = get_dimension(dimension)
    filters = parse_filters(request, dim)

    return Response(build_payload(filters))
