from integrations.communications.whatsapp import send_template


def send_verification_code_whatsapp(phone: str, code: str):
    send_template(
        to_phone=phone,
        template_name="auth",
        language_code="en_US",
        body_parameters=[
            code, "login"
        ],
        buttons=[
            {
                "sub_type": "url",
                "index": "0",
                "parameters": [{"type": "text", "text": str(code)}],
            }
        ],
    )
