from django.contrib.auth import login, logout
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm
from django.shortcuts import render, redirect
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme


def register_view(request):
    form = UserCreationForm(request.POST or None)
    if form.is_valid():
        form.save()
        return redirect(reverse('login'))
    context = {"form": form}
    return render(request, "accounts/register.html", context)


def login_view(request):

    if request.method == "POST":
        form = AuthenticationForm(request, data=request.POST)
        if form.is_valid():
            nxt = request.GET.get("next", None)
            user = form.get_user()
            login(request, user)
            if nxt and url_has_allowed_host_and_scheme(nxt, allowed_hosts=request.get_host()):
                return redirect(nxt)
            return redirect(reverse('tracker:race-overview'))
    else:
        form = AuthenticationForm(request)
    context = {
        "form": form
    }
    return render(request, "accounts/login.html", context)


def logout_view(request):
    if request.method == "POST":
        logout(request)
        return redirect(reverse('login'))
    return render(request, "accounts/logout.html", {})
