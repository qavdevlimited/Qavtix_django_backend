from django.template.loader import render_to_string
from django.core.mail import EmailMultiAlternatives
from django.conf import settings


def send_templated_email(
    subject: str,
    to_email: str,
    template_name: str,
    context: dict,
):
    """
    Renders a Django HTML template and sends it as an email.
    """

    # Render HTML from template
    html_content = render_to_string(template_name, context)

    # Create email
    email = EmailMultiAlternatives(
        subject=subject,
        body="This email requires an HTML-compatible email client.",
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[to_email],
    )

    # Attach HTML version
    email.attach_alternative(html_content, "text/html")

    # Send email
    email.send()


def send_templated_email_multiple(
    subject: str,
    template_name: str,
    context: dict,
    recipient_list: list,
    from_email: str = None,
):
    """
    Render Django template and send HTML email.
    """

    html_content = render_to_string(template_name, context)

    email = EmailMultiAlternatives(
        subject=subject,
        body="This email requires an HTML-compatible email client.",
        from_email=from_email or settings.DEFAULT_FROM_EMAIL,
        to=recipient_list,
    )

    email.attach_alternative(html_content, "text/html")
    email.send()