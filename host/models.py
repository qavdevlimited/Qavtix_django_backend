from django.db import models
from public.models import Category
from django.conf import settings




class Host(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="host_profile"
    )
    full_name=models.CharField(max_length=50)
    business_name=models.CharField(max_length=100)
    business_type=models.CharField(max_length=50)
    registration_number=models.CharField(max_length=50)
    tax_id=models.CharField(max_length=50)
    phone_number= models.CharField(max_length=16)
    companies_email=models.EmailField(max_length=254)
    country=models.CharField(max_length=30)
    state=models.CharField(max_length=30)
    city=models.CharField(max_length=30)
    postal_code=models.CharField(max_length=20)
    relevant_links = models.JSONField(default=list, blank=True)
    categories = models.ManyToManyField(Category,related_name="hosts", blank=True)
    registration_date=models.DateTimeField(auto_now_add=True)
    agree_to_terms=models.BooleanField(default=False)
    role=models.CharField(max_length=20, default="host")
    followers=models.IntegerField(default=0)

    def __str__(self):
        return self.full_name
    



class HostLink(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="links"
    )
    url = models.URLField(max_length=200)
    label = models.CharField(max_length=50, blank=True)  # e.g. Twitter, Website
    created_at = models.DateTimeField(auto_now_add=True)
