from integrations.sms.utils.sdk import send_sms_message


def send_login_otp_sms(phone, code):
    recipients = [
        {
            "mobiles": f"{phone.replace("-", "")}",
            "number": f"{code}",
        }
    ]
    send_sms_message(
        template_id="6abbb6667b160919e006c5e5",
        recipients=recipients
    )
