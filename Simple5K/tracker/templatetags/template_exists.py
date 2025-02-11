from django import template

register = template.Library()


@register.simple_tag
def template_exists():
    try:
        template.loader.get_template("tracking.html")
        return True
    except template.TemplateDoesNotExist:
        return False
