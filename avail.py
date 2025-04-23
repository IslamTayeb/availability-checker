#!/usr/bin/env python3
"""
Availability Checker - CLI tool to find free time slots across Google Calendar and Outlook.
Features include timezone switching, caching, and async API calls for performance.
Run with -h flag for usage information.
"""

import os
import sys
import json
import pickle
import datetime
import time
import asyncio
import aiohttp
import functools
from typing import List, Dict, Tuple, Optional, Set, Any
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

import click
import pytz
from dateutil import parser
from dateutil.relativedelta import relativedelta
from tzlocal import get_localzone
import pyperclip

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

from O365 import Account
from O365.calendar import Schedule

# Configuration and cache file paths
CONFIG_DIR = Path.home() / '.config' / 'avail'
GOOGLE_TOKEN_PATH = CONFIG_DIR / 'google_token.pickle'
OUTLOOK_TOKEN_PATH = CONFIG_DIR / 'outlook_token.pickle'
GOOGLE_CREDENTIALS_PATH = CONFIG_DIR / 'google_credentials.json'
OUTLOOK_CREDENTIALS_PATH = CONFIG_DIR / 'outlook_credentials.json'
CONFIG_PATH = CONFIG_DIR / 'config.json'
CACHE_DIR = CONFIG_DIR / 'cache'
GOOGLE_CACHE_PATH = CACHE_DIR / 'google_cache.json'
OUTLOOK_CACHE_PATH = CACHE_DIR / 'outlook_cache.json'

SCOPES = ['https://www.googleapis.com/auth/calendar.readonly']
TIME_BLOCK_INTERVAL = 15  # Minutes between time slots
CACHE_EXPIRATION = 300    # Cache validity in seconds (5 minutes)

# Default configuration settings
DEFAULT_CONFIG = {
    'default_timezone': 'EST',
    'quiet_mode': True,
    'use_google_calendar': True,
    'use_outlook_calendar': True,
    'use_cache': True,
    'cache_expiration': 300
}

def load_config():
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)

    if not CONFIG_PATH.exists():
        with open(CONFIG_PATH, 'w') as f:
            json.dump(DEFAULT_CONFIG, f, indent=2)
        return DEFAULT_CONFIG

    try:
        with open(CONFIG_PATH, 'r') as f:
            config = json.load(f)
            for key, value in DEFAULT_CONFIG.items():
                if key not in config:
                    config[key] = value
            return config
    except Exception as e:
        print(f"Error loading config: {e}")
        return DEFAULT_CONFIG

def save_config(config):
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)

    try:
        with open(CONFIG_PATH, 'w') as f:
            json.dump(config, f, indent=2)
        return True
    except Exception as e:
        print(f"Error saving config: {e}")
        return False

def save_cache(cache_data, cache_path):
    CACHE_DIR.mkdir(parents=True, exist_ok=True)

    try:
        with open(cache_path, 'w') as f:
            json.dump(cache_data, f, indent=2)
        return True
    except Exception:
        return False

def load_cache(cache_path, start_time, end_time, expiration=CACHE_EXPIRATION):
    if not cache_path.exists():
        return None

    try:
        mod_time = cache_path.stat().st_mtime
        if time.time() - mod_time > expiration:
            return None

        with open(cache_path, 'r') as f:
            cache_data = json.load(f)

        # Check if the cache includes metadata and covers the requested date range
        if not isinstance(cache_data, dict) or 'metadata' not in cache_data:
            return None

        cache_start = parser.parse(cache_data['metadata']['start_time'])
        cache_end = parser.parse(cache_data['metadata']['end_time'])

        # Only use cache if it fully covers the requested date range
        if cache_start <= start_time and cache_end >= end_time:
            # Filter events to only include those in the requested date range
            filtered_events = []
            for start, end in cache_data['events']:
                event_start = parser.parse(start)
                event_end = parser.parse(end)

                # Include events that overlap with the requested range
                if not (event_end <= start_time or event_start >= end_time):
                    filtered_events.append((start, end))

            return [(parser.parse(start), parser.parse(end)) for start, end in filtered_events]

        return None
    except Exception as e:
        return None

# Wrapper for the Google Calendar API to enable async operations
class AsyncGoogleCalendar:
    def __init__(self, credentials):
        self.credentials = credentials

    async def get_calendar_list(self):
        loop = asyncio.get_event_loop()
        service = build('calendar', 'v3', credentials=self.credentials)
        return await loop.run_in_executor(
            None,
            lambda: service.calendarList().list().execute().get('items', [])
        )

    async def get_events(self, calendar_id, time_min, time_max):
        loop = asyncio.get_event_loop()
        service = build('calendar', 'v3', credentials=self.credentials)
        return await loop.run_in_executor(
            None,
            lambda: service.events().list(
                calendarId=calendar_id,
                timeMin=time_min,
                timeMax=time_max,
                singleEvents=True,
                orderBy='startTime'
            ).execute().get('items', [])
        )

# Main class that handles fetching and processing calendar data
class AvailabilityChecker:
    def __init__(self, days: int, professional: bool = False, timezone: str = None, quiet: bool = False):
        self.days = days
        self.professional = professional
        self.quiet = quiet

        self.config = load_config()

        if timezone is None:
            timezone = self.config.get('default_timezone', 'EST')

        self.timezone = pytz.timezone('America/Los_Angeles') if timezone == 'PST' else pytz.timezone('America/New_York')

        self.start_time = datetime.datetime.now(self.timezone).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        self.end_time = self.start_time + datetime.timedelta(days=days)

        # Set up work hours
        self.work_start_hour = 9  # 9 AM
        self.work_end_hour = 17   # 5 PM
        self.day_end_hour = 0     # 12 AM (midnight)

        self.executor = ThreadPoolExecutor(max_workers=10)

        # Lazy-loaded API clients
        self._google_service = None
        self._outlook_account = None
        self._google_async = None

    @property
    def google_service(self):
        if self._google_service is None and self.config.get('use_google_calendar', True):
            self._google_service = self._setup_google_calendar()
        return self._google_service

    @property
    def google_async(self):
        if self._google_async is None and self.google_service:
            creds = self._get_google_credentials()
            if creds:
                self._google_async = AsyncGoogleCalendar(creds)
        return self._google_async

    @property
    def outlook_account(self):
        if self._outlook_account is None and self.config.get('use_outlook_calendar', True):
            self._outlook_account = self._setup_outlook_calendar()
        return self._outlook_account

    def _get_google_credentials(self):
        if not self.config.get('use_google_calendar', True):
            return None

        creds = None

        if GOOGLE_TOKEN_PATH.exists():
            try:
                with open(GOOGLE_TOKEN_PATH, 'rb') as token:
                    creds = pickle.load(token)
            except Exception:
                if not self.quiet:
                    print("Error loading Google Calendar token, will re-authenticate.")
                creds = None

        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                try:
                    creds.refresh(Request())
                except Exception as e:
                    if not self.quiet:
                        print(f"Error refreshing Google token: {e}")
                    return None
            else:
                if not GOOGLE_CREDENTIALS_PATH.exists():
                    if not self.quiet:
                        print("Google Calendar credentials file not found.")
                        print(f"Please download OAuth client ID credentials from Google Cloud Console")
                        print(f"and save them to {GOOGLE_CREDENTIALS_PATH}")
                    return None

                try:
                    flow = InstalledAppFlow.from_client_secrets_file(
                        GOOGLE_CREDENTIALS_PATH, SCOPES)
                    creds = flow.run_local_server(port=0)
                except Exception as e:
                    if not self.quiet:
                        print(f"Error during Google authentication: {e}")
                    return None

            try:
                with open(GOOGLE_TOKEN_PATH, 'wb') as token:
                    pickle.dump(creds, token)
            except Exception as e:
                if not self.quiet:
                    print(f"Error saving Google token: {e}")

        return creds

    def _setup_google_calendar(self):
        creds = self._get_google_credentials()
        if not creds:
            return None

        try:
            return build('calendar', 'v3', credentials=creds)
        except Exception as e:
            if not self.quiet:
                print(f"Error setting up Google Calendar API: {e}")
            return None

    def _setup_outlook_calendar(self):
        if not self.config.get('use_outlook_calendar', True):
            return None

        if not OUTLOOK_CREDENTIALS_PATH.exists():
            if not self.quiet:
                print("Outlook credentials file not found.")
                print(f"Please create a file at {OUTLOOK_CREDENTIALS_PATH} with your credentials.")
                print("Format: {'client_id': 'YOUR_CLIENT_ID', 'client_secret': 'YOUR_CLIENT_SECRET'}")
            return None

        try:
            with open(OUTLOOK_CREDENTIALS_PATH, 'r') as f:
                credentials = json.load(f)

            account = Account(credentials)

            if OUTLOOK_TOKEN_PATH.exists():
                account.con.token_backend.token_path = str(OUTLOOK_TOKEN_PATH)

            if not account.is_authenticated:
                account.authenticate()

                token_dict = account.con.token_backend.token
                with open(OUTLOOK_TOKEN_PATH, 'wb') as token_file:
                    pickle.dump(token_dict, token_file)

            return account
        except Exception as e:
            if not self.quiet:
                print(f"Error setting up Outlook Calendar API: {e}")
            return None

    # Fetch Google Calendar events using async to improve performance
    async def get_google_busy_slots_async(self):
        if not self.config.get('use_google_calendar', True):
            return []

        if not self.google_async:
            if not self.quiet:
                print("Google Calendar API not set up.")
            return []

        # Check cache before making API calls, now with date range
        if self.config.get('use_cache', True):
            cache_data = load_cache(
                GOOGLE_CACHE_PATH,
                self.start_time,
                self.end_time,
                self.config.get('cache_expiration', CACHE_EXPIRATION)
            )
            if cache_data:
                return cache_data

        busy_slots = []

        try:
            # Fetch calendars and events concurrently
            calendars = await self.google_async.get_calendar_list()

            event_tasks = []
            for calendar in calendars:
                task = self.google_async.get_events(
                    calendar['id'],
                    self.start_time.isoformat(),
                    self.end_time.isoformat()
                )
                event_tasks.append(task)

            all_events_results = await asyncio.gather(*event_tasks)

            for events in all_events_results:
                for event in events:
                    if 'dateTime' not in event.get('start', {}) or 'dateTime' not in event.get('end', {}):
                        continue

                    start = parser.parse(event['start']['dateTime'])
                    end = parser.parse(event['end']['dateTime'])

                    busy_slots.append((start, end))

            if self.config.get('use_cache', True):
                # New cache format with metadata and date range
                cache_data = {
                    'metadata': {
                        'start_time': self.start_time.isoformat(),
                        'end_time': self.end_time.isoformat(),
                        'created_at': datetime.datetime.now(self.timezone).isoformat()
                    },
                    'events': [(start.isoformat(), end.isoformat()) for start, end in busy_slots]
                }
                save_cache(cache_data, GOOGLE_CACHE_PATH)

        except Exception as e:
            if not self.quiet:
                print(f"Error getting Google Calendar events: {e}")

        return busy_slots

    def get_google_busy_slots(self):
        if not self.config.get('use_google_calendar', True):
            return []

        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

        return loop.run_until_complete(self.get_google_busy_slots_async())

    def get_outlook_busy_slots(self):
        if not self.config.get('use_outlook_calendar', True):
            return []

        if not self.outlook_account:
            if not self.quiet:
                print("Outlook Calendar API not set up.")
            return []

        # Check cache before making API calls, now with date range
        if self.config.get('use_cache', True):
            cache_data = load_cache(
                OUTLOOK_CACHE_PATH,
                self.start_time,
                self.end_time,
                self.config.get('cache_expiration', CACHE_EXPIRATION)
            )
            if cache_data:
                return cache_data

        busy_slots = []

        try:
            schedule = self.outlook_account.schedule()
            calendar = schedule.get_default_calendar()

            q = calendar.new_query('start').greater_equal(self.start_time)
            q = q.chain('and').on_attribute('end').less_equal(self.end_time)

            events = calendar.get_events(query=q, include_recurring=True)

            for event in events:
                start = event.start
                end = event.end

                if start.tzinfo != self.timezone:
                    start = start.astimezone(self.timezone)
                if end.tzinfo != self.timezone:
                    end = end.astimezone(self.timezone)

                busy_slots.append((start, end))

            if self.config.get('use_cache', True):
                # New cache format with metadata and date range
                cache_data = {
                    'metadata': {
                        'start_time': self.start_time.isoformat(),
                        'end_time': self.end_time.isoformat(),
                        'created_at': datetime.datetime.now(self.timezone).isoformat()
                    },
                    'events': [(start.isoformat(), end.isoformat()) for start, end in busy_slots]
                }
                save_cache(cache_data, OUTLOOK_CACHE_PATH)

        except Exception as e:
            if not self.quiet:
                print(f"Error getting Outlook Calendar events: {e}")

        return busy_slots

    # Fetch all calendar data in parallel for better performance
    async def get_all_busy_slots_async(self):
        tasks = []

        if self.config.get('use_google_calendar', True):
            tasks.append(self.get_google_busy_slots_async())

        if self.config.get('use_outlook_calendar', True):
            loop = asyncio.get_event_loop()
            outlook_future = loop.run_in_executor(self.executor, self.get_outlook_busy_slots)
            tasks.append(outlook_future)

        results = await asyncio.gather(*tasks)

        busy_slots = []
        for result in results:
            busy_slots.extend(result)

        return busy_slots

    # Core algorithm: Find available slots by inverting busy slots
    async def get_available_slots_async(self):
        busy_slots = await self.get_all_busy_slots_async()

        busy_slots.sort(key=lambda slot: slot[0])

        # Merge overlapping busy slots for efficiency
        merged_busy_slots = []
        if busy_slots:
            current_start, current_end = busy_slots[0]

            for start, end in busy_slots[1:]:
                if start <= current_end:
                    current_end = max(current_end, end)
                else:
                    merged_busy_slots.append((current_start, current_end))
                    current_start, current_end = start, end

            merged_busy_slots.append((current_start, current_end))

        available_slots_by_day = {}
        current_day = self.start_time

        # Iterate through each day in the range
        while current_day < self.end_time:
            day_key = current_day.strftime("%a")
            is_weekend = current_day.weekday() >= 5

            if self.professional and is_weekend:
                current_day += datetime.timedelta(days=1)
                continue

            # Set up day boundaries based on professional mode
            if self.professional:
                day_start = current_day.replace(hour=self.work_start_hour, minute=0, second=0, microsecond=0)
                day_end = current_day.replace(hour=self.work_end_hour, minute=0, second=0, microsecond=0)
            else:
                day_start = current_day.replace(hour=self.work_start_hour, minute=0, second=0, microsecond=0)
                day_end = (current_day + datetime.timedelta(days=1)).replace(hour=self.day_end_hour, minute=0, second=0, microsecond=0)

            # Generate all possible time slots for this day
            all_slots = []
            slot_start = day_start

            while slot_start < day_end:
                slot_end = slot_start + datetime.timedelta(minutes=TIME_BLOCK_INTERVAL)
                all_slots.append((slot_start, slot_end))
                slot_start = slot_end

            # Find which slots are available (not overlapping with busy slots)
            available_slots = []

            for slot in all_slots:
                slot_start, slot_end = slot
                is_available = True

                for busy_start, busy_end in merged_busy_slots:
                    if not (slot_end <= busy_start or slot_start >= busy_end):
                        is_available = False
                        break

                if is_available:
                    available_slots.append(slot)

            # Merge adjacent available slots for cleaner output
            merged_available_slots = []

            if available_slots:
                current_start, current_end = available_slots[0]

                for slot_start, slot_end in available_slots[1:]:
                    if slot_start == current_end:
                        current_end = slot_end
                    else:
                        merged_available_slots.append((current_start, current_end))
                        current_start, current_end = slot_start, slot_end

                merged_available_slots.append((current_start, current_end))

            if merged_available_slots:
                day_short = current_day.strftime("%a")[:2]
                if day_short not in available_slots_by_day:
                    available_slots_by_day[day_short] = []
                available_slots_by_day[day_short].extend(merged_available_slots)

            current_day += datetime.timedelta(days=1)

        return available_slots_by_day

    def get_available_slots(self):
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

        return loop.run_until_complete(self.get_available_slots_async())

    # Format availability into human-readable form with different formats based on date range
    def format_available_slots(self):
        available_slots = self.get_available_slots()

        if not available_slots:
            return "No available slots found."

        output = []
        days_in_range = []
        current_day = self.start_time
        while current_day < self.end_time:
            day_short = current_day.strftime("%a")[:2]
            if not (self.professional and current_day.weekday() >= 5):
                days_in_range.append((day_short, current_day.date()))
            current_day += datetime.timedelta(days=1)

        # Check if dates span different months for better formatting
        start_month = self.start_time.month
        cross_month = any(day_date.month != start_month for _, day_date in days_in_range)

        def get_ordinal_suffix(day):
            if 11 <= day <= 13:
                return 'th'
            else:
                return {1: 'st', 2: 'nd', 3: 'rd'}.get(day % 10, 'th')

        for day_short, day_date in days_in_range:
            slots_text = []
            day_slots = available_slots.get(day_short, [])
            day_slots = [slot for slot in day_slots if slot[0].date() == day_date]

            for start, end in day_slots:
                start_str = start.strftime("%-I:%M %p")
                end_str = end.strftime("%-I:%M %p")
                slots_text.append(f"{start_str} - {end_str}")

            # Use different formatting based on date range
            if self.days < 7:
                day_label = f"{day_short}"
            elif cross_month:
                day_label = f"{day_date.strftime('%B %-d')} {day_short}"
            else:
                day_ordinal = day_date.day
                suffix = get_ordinal_suffix(day_ordinal)
                day_label = f"{day_short} {day_ordinal}{suffix}"

            if slots_text:
                output.append(f"{day_label} - {' // '.join(slots_text)}")
            else:
                output.append(f"{day_label} - No availability")

        return "\n".join(output)

@click.command()
@click.argument('days', type=int, required=False, default=3)
@click.option('-p', '--professional', is_flag=True, help='Limit to professional hours (9AM-5PM, no weekends)')
@click.option('-pst', '--pst', is_flag=True, help='Use PST timezone')
@click.option('-est', '--est', is_flag=True, help='Use EST timezone')
@click.option('-default', '--set-default-timezone', type=click.Choice(['EST', 'PST']))
@click.option('-q', '--quiet', is_flag=True, help='Toggle quiet mode')
@click.option('-toggle', '--toggle-timezone', is_flag=True, help='Toggle timezone')
@click.option('--google/--no-google', default=None)
@click.option('--outlook/--no-outlook', default=None)
@click.option('--cache/--no-cache', default=None)
@click.option('--cache-time', type=int)
@click.option('--clear-cache', is_flag=True)
def main(days: int, professional: bool, pst: bool, est: bool, set_default_timezone: str,
         quiet: bool, toggle_timezone: bool, google: bool, outlook: bool,
         cache: bool, cache_time: int, clear_cache: bool):
    config = load_config()

    # Handle configuration commands
    if clear_cache:
        try:
            if GOOGLE_CACHE_PATH.exists():
                GOOGLE_CACHE_PATH.unlink()
            if OUTLOOK_CACHE_PATH.exists():
                OUTLOOK_CACHE_PATH.unlink()
            print("Cache cleared successfully")
        except Exception as e:
            print(f"Error clearing cache: {e}")
        return

    if cache is not None:
        config['use_cache'] = cache
        if save_config(config):
            status = "enabled" if cache else "disabled"
            print(f"API response caching {status}")
        else:
            print(f"Failed to update cache setting")
        return

    if cache_time is not None:
        config['cache_expiration'] = cache_time
        if save_config(config):
            print(f"Cache expiration set to {cache_time} seconds")
        else:
            print(f"Failed to update cache expiration time")
        return

    if google is not None:
        config['use_google_calendar'] = google
        if save_config(config):
            status = "enabled" if google else "disabled"
            print(f"Google Calendar integration {status}")
        else:
            print(f"Failed to update Google Calendar setting")
        return

    if outlook is not None:
        config['use_outlook_calendar'] = outlook
        if save_config(config):
            status = "enabled" if outlook else "disabled"
            print(f"Outlook Calendar integration {status}")
        else:
            print(f"Failed to update Outlook Calendar setting")
        return

    if quiet:
        config['quiet_mode'] = not config.get('quiet_mode', True)
        if save_config(config):
            quiet_status = "disabled" if not config['quiet_mode'] else "enabled"
            print(f"Quiet mode {quiet_status}")
        else:
            print(f"Failed to toggle quiet mode")
        return

    if toggle_timezone:
        current_tz = config.get('default_timezone', 'EST')
        new_tz = 'PST' if current_tz == 'EST' else 'EST'
        config['default_timezone'] = new_tz
        if save_config(config):
            print(f"Default timezone switched to {new_tz}")
        else:
            print(f"Failed to switch default timezone")
        return

    if set_default_timezone:
        config['default_timezone'] = set_default_timezone
        if save_config(config):
            print(f"Default timezone set to {set_default_timezone}")
        else:
            print(f"Failed to set default timezone")
        return

    if days <= 0:
        print("Error: 'days' must be a positive integer.")
        sys.exit(1)

    use_quiet_mode = config.get('quiet_mode', True)
    default_timezone = config.get('default_timezone', 'EST')

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

    if not use_quiet_mode:
        tz_display = "PST (Pacific)" if timezone == 'PST' else "EST (Eastern)"
        print(f"Using {tz_display} timezone")

    # Performance measurement and availability calculation
    start_time = time.time()
    checker = AvailabilityChecker(days, professional, timezone, use_quiet_mode)
    result = checker.format_available_slots()
    end_time = time.time()

    try:
        pyperclip.copy(result)
        print(result)
        if not use_quiet_mode:
            print(f"\nAvailability copied to clipboard! ({end_time - start_time:.2f}s)")
    except Exception as e:
        print(result)
        if not use_quiet_mode:
            print(f"\nFailed to copy to clipboard: {e}")

if __name__ == '__main__':
    main()
