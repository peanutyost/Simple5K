from django.db import models
    
class race(models.Model):
    name = models.CharField(max_length=255)
    is_current = models.BooleanField(null=True, blank=True)
    distance = models.IntegerField()
    laps_count = models.IntegerField()
    start_time = models.DateTimeField(auto_now=False, auto_now_add=False, null=True, blank=True)
    end_time = models.DateTimeField(auto_now=False, auto_now_add=False, null=True, blank=True)
    
    def __str__(self):
        return self.name
    
class runners(models.Model):
    first_name = models.CharField(max_length=50)
    last_name = models.CharField(max_length=50)
    number = models.IntegerField(unique=True)
    race = models.ForeignKey(race, on_delete=models.PROTECT)
    race_completed = models.BooleanField(null=True, blank=True)
    total_race_time = models.DurationField(blank=True, null=True)
    race_avg_speed = models.DecimalField(max_digits=5, decimal_places=2, blank=True, null=True)
    type = models.CharField(max_length=64, null=True, blank=True)
    notes = models.CharField(max_length=512, null=True, blank=True)
    
    
    def __str__(self):
        return self.first_name + " " + self.last_name
    
class laps(models.Model):
    runner = models.ForeignKey(runners, on_delete=models.CASCADE)
    time = models.DateTimeField(auto_now=False, auto_now_add=False)
    lap = models.IntegerField()
    attach_to_race = models.ForeignKey(race , on_delete=models.CASCADE)
    duration = models.DurationField()
    average_speed = models.DecimalField(max_digits=5, decimal_places=2)
    
    def __str__(self):
        return self.attach_to_race.name + "/" + str(self.runner.number)