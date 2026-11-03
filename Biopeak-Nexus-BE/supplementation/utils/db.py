from django.db import IntegrityError, transaction

from supplementation.models import Brand


def get_or_create_brand(name: str) -> Brand:
    cleaned_name = Brand.objects.clean_spaces(name)
    brand = Brand.objects.filter(name__iexact=cleaned_name).first()
    if brand is not None:
        return brand
    try:
        with transaction.atomic():
            return Brand.objects.create(name=cleaned_name)
    except IntegrityError:
        brand = Brand.objects.filter(name__iexact=cleaned_name).first()
        if brand is None:
            raise
        return brand
