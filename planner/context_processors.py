from .acting import get_view_as_user


def view_as_context(request):
    viewed = get_view_as_user(request)
    return {
        'view_as_user': viewed,
    }
