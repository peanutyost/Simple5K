# Race Tracking System

A Django-based web application for managing and tracking races, runners, and lap times.

## Features
- Race management (create, edit, list)
- Runner registration
- Lap time tracking
- Real-time race overview
- PDF report generation
- Shirt size tracking
- Race countdown timer
- Banner management

## Installation

1. Clone the repository:
```bash
git clone [repository-url]
```

2. Create a virtual environment and activate it:
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

3. Install dependencies:
```bash
pip install -r requirements.txt
```

4. Apply migrations:
```bash
python manage.py migrate
```

5. Create a superuser:
```bash
python manage.py createsuperuser
```

## Usage

### Admin Features (Login Required)
- **Add Race**: Create new races with details like distance, laps, and entry fee
- **Edit Race**: Modify existing race details
- **List Races**: View all races with pagination
- **Track Laps**: Record lap times for runners during races
- **View Statistics**: Generate PDF reports with runner statistics
- **Manage Shirts**: Track shirt size distribution for races

### Public Features
- **Race Overview**: View current race progress and runner standings
- **Race Signup**: Register for upcoming races
- **Race List**: View list of upcoming races with countdown timers
- **Race Countdown**: Real-time countdown for upcoming races

## Models
- **Race**: Stores race information (name, distance, laps, status, etc.)
- **Runners**: Manages runner information and race participation
- **Laps**: Records individual lap times and statistics
- **Banner**: Handles promotional banners for the website

## Views

### Admin Views
- `RaceAdd`: Add new races
- `RaceEdit`: Edit existing races
- `ListRaces`: View all races
- `laps_view`: Record lap times
- `runner_stats`: Generate runner statistics

### Public Views
- `race_overview`: Display current race status
- `race_signup`: Handle runner registration
- `race_countdown`: Show countdown for upcoming races
- `race_list`: List all races

## Forms
- `RaceForm`: Race creation/editing
- `SignupForm`: Runner registration
- `LapForm`: Lap time recording
- `runnerStats`: Runner statistics generation

## Contributing
1. Fork the repository
2. Create your feature branch (`git checkout -b feature/AmazingFeature`)
3. Commit your changes (`git commit -m 'Add some AmazingFeature'`)
4. Push to the branch (`git push origin feature/AmazingFeature`)
5. Open a Pull Request

## License
 - GPL-3.0 License

## Requirements
- Python 3.x
- Django
- Other dependencies listed in requirements.txt

## Notes
- Ensure proper timezone settings in Django settings.py
- Configure your database settings accordingly
- Set up proper security measures for production deployment

## Page View Tracking
 - add tracking code in a page at Simple5K/tracker/templates/tracker.html. This gets included in the header on all pages and tracks visits to the site.