from django.db import models

class runners(models.Model):
    first_name = models.CharField(max_length=50)
    last_name = models.CharField(max_length=50)
    number = models.IntegerField()
    race = models.ForeignKey(race, on_delete=models.PROTECT)
    type = models.CharField(max_length=64, null=True, blank=True)
    notes = models.CharField(max_length=512, null=True, blank=True)

    
class race(models.Model):
    is_current = models.BooleanField(null=True, blank=True)
    distance = models.IntegerField()
    laps = models.IntegerField()
    start_time = models.TimeField(auto_now=False, auto_now_add=False, null=True, blank=True)
    end_time = models.TimeField(auto_now=False, auto_now_add=False, null=True, blank=True)
    
class laps(models.Model):
    runner = models.ForeignKey(runners, on_delete=models.CASCADE)
    time = models.DateField(auto_now=False, auto_now_add=True)
    lap = models.IntegerField()