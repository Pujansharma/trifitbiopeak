from django.template.loader import get_template

from core.utils.emails import send_templated_email


def send_verification_phone_email(phone, code):
    print(f"OTP FOR PHONE: {phone} =  {code}")
    subject = f"One Time Passcode for {phone}"
    context = {
        "identifier": phone,
        "otp_code": code,
    }

    template = get_template("verifications/otp_email_template.html").render(
        context=context
    )
    send_templated_email(subject, template=template, email="otp@biopeak.local")
