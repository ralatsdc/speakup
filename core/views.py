from django.contrib.auth.decorators import login_required
from django.shortcuts import render


@login_required
def help_page(request):
    template = "core/help_admin.html" if request.user.is_staff else "core/help_user.html"
    return render(request, template)
