STAC_VERSION = "1.0.0"


def build_url(request, path):
    return request.build_absolute_uri(path)
