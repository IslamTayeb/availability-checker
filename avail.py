#!/usr/bin/env python3
"""
Availability Checker CLI
Gets free time slots from Google Calendar and Outlook calendars.
"""

import os
import sys
import json
import pickle
import datetime
from typing import List, Dict, Tuple, Optional, Set
from pathlib import Path

import click
import pytz
from dateutil import parser
from dateutil.relativedelta import relativedelta
from tzlocal import get_localzone
import pyperclip

# Google Calendar API imports
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

# Microsoft Outlook API imports
from O365 import Account
from O365.calendar import Schedule

# Constants
CONFIG_DIR = Path.home() / '.config' / 'avail'
GOOGLE_TOKEN_PATH = CONFIG_DIR / 'google_token.pickle'
OUTLOOK_TOKEN_PATH = CONFIG_DIR / 'outlook_token.pickle'
GOOGLE_CREDENTIALS_PATH = CONFIG_DIR / 'google_credentials.json'
OUTLOOK_CREDENTIALS_PATH = CONFIG_DIR / 'outlook_credentials.json'
CONFIG_PATH = CONFIG_DIR / 'config.json'

# Google Calendar API Scopes
SCOPES = ['https://www.googleapis.com/auth/calendar.readonly']

# Time block interval in minutes
TIME_BLOCK_INTERVAL = 15

# Default config
DEFAULT_CONFIG = {
    'default_timezone': 'EST'  # Can be 'EST' or 'PST'
}

def load_config():
    """Load configuration from file or create default if not exists."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)

    if not CONFIG_PATH.exists():
        with open(CONFIG_PATH, 'w') as f:
            json.dump(DEFAULT_CONFIG, f, indent=2)
        return DEFAULT_CONFIG

    try:
        with open(CONFIG_PATH, 'r') as f:
            return json.load(f)
    except Exception as e:
        print(f"Error loading config: {e}")
        return DEFAULT_CONFIG

def save_config(config):
    """Save configuration to file."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)

    try:
        with open(CONFIG_PATH, 'w') as f:
            json.dump(config, f, indent=2)
        return True
    except Exception as e:
        print(f"Error saving config: {e}")
        return False

class AvailabilityChecker:
    """Main class for checking availability across calendars."""

    def __init__(self, days: int, professional: bool = False, timezone: str = None):
        """Initialize the availability checker.

        Args:
            days: Number of days to look ahead
            professional: Whether to limit to professional hours (9AM-5PM, no weekends)
            timezone: Timezone to use ('EST' or 'PST'). If None, use default from config.
        """
        self.days = days
        self.professional = professional

        # Use specified timezone or load from config
        if timezone is None:
            config = load_config()
            timezone = config.get('default_timezone', 'EST')

        self.timezone = pytz.timezone('America/Los_Angeles') if timezone == 'PST' else pytz.timezone('America/New_York')

        # Set up start and end times for the search period
        self.start_time = datetime.datetime.now(self.timezone).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        self.end_time = self.start_time + datetime.timedelta(days=days)

        # Set up work hours
        self.work_start_hour = 9  # 9 AM
        self.work_end_hour = 17   # 5 PM
        self.day_end_hour = 1     # 1 AM (next day)

        # Initialize API clients
        self.google_service = self._setup_google_calendar()
        self.outlook_account = self._setup_outlook_calendar()

    def _setup_google_calendar(self):
        """Set up Google Calendar API client."""
        creds = None

        # Ensure config directory exists
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)

        # Check if we have stored credentials
        if GOOGLE_TOKEN_PATH.exists():
            with open(GOOGLE_TOKEN_PATH, 'rb') as token:
                creds = pickle.load(token)

        # If credentials don't exist or are invalid, get new ones
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                if not GOOGLE_CREDENTIALS_PATH.exists():
                    print("Google Calendar credentials file not found.")
                    print(f"Please download OAuth client ID credentials from Google Cloud Console")
                    print(f"and save them to {GOOGLE_CREDENTIALS_PATH}")
                    return None

                flow = InstalledAppFlow.from_client_secrets_file(
                    GOOGLE_CREDENTIALS_PATH, SCOPES)
                creds = flow.run_local_server(port=0)

            # Save the credentials for the next run
            with open(GOOGLE_TOKEN_PATH, 'wb') as token:
                pickle.dump(creds, token)

        try:
            return build('calendar', 'v3', credentials=creds)
        except Exception as e:
            print(f"Error setting up Google Calendar API: {e}")
            return None

    def _setup_outlook_calendar(self):
        """Set up Outlook/Office365 API client."""
        if not OUTLOOK_CREDENTIALS_PATH.exists():
            print("Outlook credentials file not found.")
            print(f"Please create a file at {OUTLOOK_CREDENTIALS_PATH} with your credentials.")
            print("Format: {'client_id': 'YOUR_CLIENT_ID', 'client_secret': 'YOUR_CLIENT_SECRET'}")
            return None

        try:
            with open(OUTLOOK_CREDENTIALS_PATH, 'r') as f:
                credentials = json.load(f)

            account = Account(credentials)

            # Check if we have a token file
            if OUTLOOK_TOKEN_PATH.exists():
                account.con.token_backend.token_path = str(OUTLOOK_TOKEN_PATH)

            # Authenticate and get a token
            if not account.is_authenticated:
                account.authenticate()

                # Save the token
                token_dict = account.con.token_backend.token
                with open(OUTLOOK_TOKEN_PATH, 'wb') as token_file:
                    pickle.dump(token_dict, token_file)

            return account
        except Exception as e:
            print(f"Error setting up Outlook Calendar API: {e}")
            return None

    def get_google_busy_slots(self) -> List[Tuple[datetime.datetime, datetime.datetime]]:
        """Get busy time slots from Google Calendar."""
        if not self.google_service:
            print("Google Calendar API not set up.")
            return []

        busy_slots = []

        try:
            # First get list of calendars
            calendar_list = self.google_service.calendarList().list().execute()

            for calendar_entry in calendar_list.get('items', []):
                calendar_id = calendar_entry['id']

                # Get events from this calendar
                events_result = self.google_service.events().list(
                    calendarId=calendar_id,
                    timeMin=self.start_time.isoformat(),
                    timeMax=self.end_time.isoformat(),
                    singleEvents=True,
                    orderBy='startTime'
                ).execute()

                events = events_result.get('items', [])

                for event in events:
                    # Skip all-day events or events without a start/end time
                    if 'dateTime' not in event.get('start', {}) or 'dateTime' not in event.get('end', {}):
                        continue

                    # Parse the event start and end times
                    start = parser.parse(event['start']['dateTime'])
                    end = parser.parse(event['end']['dateTime'])

                    busy_slots.append((start, end))

        except Exception as e:
            print(f"Error getting Google Calendar events: {e}")

        return busy_slots

    def get_outlook_busy_slots(self) -> List[Tuple[datetime.datetime, datetime.datetime]]:
        """Get busy time slots from Outlook Calendar."""
        if not self.outlook_account:
            print("Outlook Calendar API not set up.")
            return []

        busy_slots = []

        try:
            schedule = self.outlook_account.schedule()
            calendar = schedule.get_default_calendar()

            # Query events
            q = calendar.new_query('start').greater_equal(self.start_time)
            q = q.chain('and').on_attribute('end').less_equal(self.end_time)

            events = calendar.get_events(query=q, include_recurring=True)

            for event in events:
                start = event.start
                end = event.end

                # Convert to the desired timezone if needed
                if start.tzinfo != self.timezone:
                    start = start.astimezone(self.timezone)
                if end.tzinfo != self.timezone:
                    end = end.astimezone(self.timezone)

                busy_slots.append((start, end))

        except Exception as e:
            print(f"Error getting Outlook Calendar events: {e}")

        return busy_slots

    def get_available_slots(self) -> Dict[str, List[Tuple[datetime.datetime, datetime.datetime]]]:
        """Get available time slots by day."""
        # Combine busy slots from all sources
        all_busy_slots = self.get_google_busy_slots() + self.get_outlook_busy_slots()

        # Sort busy slots by start time
        all_busy_slots.sort(key=lambda slot: slot[0])

        # Merge overlapping busy slots
        merged_busy_slots = []
        if all_busy_slots:
            current_start, current_end = all_busy_slots[0]

            for start, end in all_busy_slots[1:]:
                if start <= current_end:
                    # Overlap found, merge by extending the current slot if needed
                    current_end = max(current_end, end)
                else:
                    # No overlap, add the current slot and start a new one
                    merged_busy_slots.append((current_start, current_end))
                    current_start, current_end = start, end

            # Add the last slot
            merged_busy_slots.append((current_start, current_end))

        # Find free slots by day
        available_slots_by_day = {}

        current_day = self.start_time

        while current_day < self.end_time:
            day_key = current_day.strftime("%a")
            is_weekend = current_day.weekday() >= 5  # Saturday or Sunday

            # Skip weekends if professional mode is enabled
            if self.professional and is_weekend:
                current_day += datetime.timedelta(days=1)
                continue

            # Set day start/end times based on settings
            if self.professional:
                day_start = current_day.replace(hour=self.work_start_hour, minute=0, second=0, microsecond=0)
                day_end = current_day.replace(hour=self.work_end_hour, minute=0, second=0, microsecond=0)
            else:
                day_start = current_day.replace(hour=self.work_start_hour, minute=0, second=0, microsecond=0)
                day_end = (current_day + datetime.timedelta(days=1)).replace(hour=self.day_end_hour, minute=0, second=0, microsecond=0)

            # Generate all possible time slots for the day
            all_slots = []
            slot_start = day_start

            while slot_start < day_end:
                slot_end = slot_start + datetime.timedelta(minutes=TIME_BLOCK_INTERVAL)
                all_slots.append((slot_start, slot_end))
                slot_start = slot_end

            # Filter out busy slots
            available_slots = []

            for slot in all_slots:
                slot_start, slot_end = slot

                # Check if slot overlaps with any busy slot
                is_available = True

                for busy_start, busy_end in merged_busy_slots:
                    # If there's any overlap, the slot is not available
                    if not (slot_end <= busy_start or slot_start >= busy_end):
                        is_available = False
                        break

                if is_available:
                    available_slots.append(slot)

            # Merge adjacent available slots
            merged_available_slots = []

            if available_slots:
                current_start, current_end = available_slots[0]

                for slot_start, slot_end in available_slots[1:]:
                    if slot_start == current_end:
                        # Slots are adjacent, merge them
                        current_end = slot_end
                    else:
                        # Slots are not adjacent, add the current slot and start a new one
                        merged_available_slots.append((current_start, current_end))
                        current_start, current_end = slot_start, slot_end

                # Add the last slot
                merged_available_slots.append((current_start, current_end))

            # Store the merged available slots for the day
            if merged_available_slots:
                day_short = current_day.strftime("%a")[:2]  # Mo, Tu, etc.
                if day_short not in available_slots_by_day:
                    available_slots_by_day[day_short] = []
                available_slots_by_day[day_short].extend(merged_available_slots)

            # Move to the next day
            current_day += datetime.timedelta(days=1)

        return available_slots_by_day

    def format_available_slots(self) -> str:
        """Format available slots in the desired output format."""
        available_slots = self.get_available_slots()

        if not available_slots:
            return "No available slots found."

        output = []

        # Create list of all days in the date range
        days_in_range = []
        current_day = self.start_time
        while current_day < self.end_time:
            day_short = current_day.strftime("%a")[:2]  # Mo, Tu, etc.
            if not (self.professional and current_day.weekday() >= 5):  # Skip weekends in professional mode
                days_in_range.append((day_short, current_day.date()))
            current_day += datetime.timedelta(days=1)

        # Process all days
        for day_short, day_date in days_in_range:
            slots_text = []

            # Get slots for this day
            day_slots = available_slots.get(day_short, [])

            # Filter slots to only include those for this specific date
            day_slots = [
                slot for slot in day_slots
                if slot[0].date() == day_date
            ]

            for start, end in day_slots:
                start_str = start.strftime("%-I:%M %p")
                end_str = end.strftime("%-I:%M %p")
                slots_text.append(f"{start_str} - {end_str}")

            if slots_text:
                output.append(f"{day_short} - {'; '.join(slots_text)}")
            else:
                output.append(f"{day_short} - No availability")

        return "\n".join(output)

@click.command()
@click.argument('days', type=int)
@click.option('-p', '--professional', is_flag=True, help='Limit to professional hours (9AM-5PM, no weekends)')
@click.option('-pst', '--pst', is_flag=True, help='Use PST timezone')
@click.option('-est', '--est', is_flag=True, help='Use EST timezone')
@click.option('-default', '--set-default-timezone', type=click.Choice(['EST', 'PST']),
              help='Set default timezone for future use')
def main(days: int, professional: bool, pst: bool, est: bool, set_default_timezone: str):
    """Check calendar availability for the next DAYS days."""
    if days <= 0:
        print("Error: 'days' must be a positive integer.")
        sys.exit(1)

    # Handle setting default timezone
    if set_default_timezone:
        config = load_config()
        config['default_timezone'] = set_default_timezone
        if save_config(config):
            print(f"Default timezone set to {set_default_timezone}")
        else:
            print(f"Failed to set default timezone")
        return

    # Load current config
    config = load_config()
    default_timezone = config.get('default_timezone', 'EST')

    # Determine which timezone to use
    timezone = None
    if pst and est:
        print("Error: Cannot specify both -pst and -est flags.")
        sys.exit(1)
    elif pst:
        timezone = 'PST'
    elif est:
        timezone = 'EST'
    else:
        timezone = default_timezone

    # Display which timezone is being used
    tz_display = "PST (Pacific)" if timezone == 'PST' else "EST (Eastern)"
    print(f"Using {tz_display} timezone")

    checker = AvailabilityChecker(days, professional, timezone)
    result = checker.format_available_slots()

    # Copy to clipboard
    try:
        pyperclip.copy(result)
        print(result)
        print("\nAvailability copied to clipboard!")
    except Exception as e:
        print(result)
        print(f"\nFailed to copy to clipboard: {e}")

if __name__ == '__main__':
    main()
