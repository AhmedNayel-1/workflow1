PAGE_SIZES = (10, 25, 50, 100)


def page_size(request, default=25):
    """حجم الصفحة من معامل per_page (10 / 25 / 50 / 100)، وإلا الافتراضي."""
    try:
        n = int(request.GET.get("per_page", default))
    except (TypeError, ValueError):
        return default
    return n if n in PAGE_SIZES else default
