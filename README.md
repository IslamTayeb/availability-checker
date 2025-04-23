# Availability Checker

A CLI tool to check your availability across Google Calendar and Outlook calendars.

## Installation

1. Clone this repository:
   ```
   git clone https://github.com/yourusername/availability-checker.git
   cd availability-checker
   ```

2. Install the required packages:
   ```
   pip install -r requirements.txt
   ```

3. Set up API credentials:

   ### Google Calendar
   1. Go to the [Google Cloud Console](https://console.cloud.google.com/)
   2. Create a new project
   3. Enable the Google Calendar API
   4. Create OAuth 2.0 credentials (Desktop application)
   5. Download the credentials JSON file
   6. Save it to `~/.config/avail/google_credentials.json`

   ### Outlook/Office 365
   1. Go to the [Microsoft Azure Portal](https://portal.azure.com/)
   2. Register a new application
   3. Add the Calendar.Read API permission
   4. Get the client ID and client secret
   5. Create a file at `~/.config/avail/outlook_credentials.json` with the following format:
      ```json
      {
        "client_id": "YOUR_CLIENT_ID",
        "client_secret": "YOUR_CLIENT_SECRET"
      }
      ```

4. Make the script executable:
   ```
   chmod +x avail.py
   ```

5. (Optional) Create a symlink to use it from anywhere:
   ```
   sudo ln -s $(pwd)/avail.py /usr/local/bin/avail
   ```

## Usage

```
avail [DAYS] [OPTIONS]
```

### Arguments
- `DAYS`: Number of days to look ahead for availability (default: 3 days if not specified)

### Options
- `-p, --professional`: Limit to professional hours (9AM-5PM, no weekends)
- `-pst, --pst`: Use PST timezone for this query
- `-est, --est`: Use EST timezone for this query
- `-default, --set-default-timezone [EST|PST]`: Set default timezone for future use
- `-q, --quiet`: Toggle quiet mode on/off (error messages are suppressed by default)
- `-toggle, --toggle-timezone`: Toggle between EST and PST as default timezone
- `--google/--no-google`: Enable/disable Google Calendar integration
- `--outlook/--no-outlook`: Enable/disable Outlook Calendar integration
- `--cache/--no-cache`: Enable/disable caching of API responses
- `--cache-time [SECONDS]`: Set cache expiration time in seconds
- `--clear-cache`: Clear all cached API responses

### Examples

Check availability for the next 3 days (default):
```
avail
```

Check availability for the next 5 days:
```
avail 5
```

Toggle quiet mode on/off:
```
avail -q
```

Toggle default timezone between EST and PST:
```
avail -toggle
```

Disable Outlook Calendar integration:
```
avail --no-outlook
```

Enable only Google Calendar integration:
```
avail --no-outlook -google
```

Enable response caching (already on by default):
```
avail --cache
```

Set cache expiration to 10 minutes (600 seconds):
```
avail --cache-time 600
```

Clear all cached responses:
```
avail --clear-cache
```

Check professional availability (9AM-5PM, no weekends) for the next week:
```
avail 7 -p
```

Check availability in PST timezone:
```
avail -pst
```

Check availability in EST timezone:
```
avail -est
```

Set PST as your default timezone:
```
avail --set-default-timezone PST
```

## Timezone Configuration

The tool allows you to set a default timezone (EST or PST) to match your current location:

1. If you're in San Francisco: `avail -toggle` or `avail --set-default-timezone PST`
2. If you're in New York: `avail -toggle` or `avail --set-default-timezone EST`

You can always override the default for a specific query with the `-est` or `-pst` flags.

## Output Format

The tool displays available time slots in different formats based on the date range:

### For less than 7 days
```
Mo - 3:00 PM - 5:00 PM
Tu - 10:00 AM - 11:00 AM // 2:30 PM - 4:00 PM
```

### For 7+ days within the same month
```
Mo 15th - 3:00 PM - 5:00 PM
Tu 16th - 10:00 AM - 11:00 AM // 2:30 PM - 4:00 PM
```

### For dates spanning across different months
```
January 15 Mo - 3:00 PM - 5:00 PM
February 1 Tu - 10:00 AM - 11:00 AM // 2:30 PM - 4:00 PM
```

Where:
- The day is represented by the first two letters (Mo, Tu, We, etc.)
- Multiple time slots for the same day are separated by double slashes (`//`)
- The output is automatically copied to your clipboard for easy sharing

## Implementation Details

### Configuration System

The tool uses a configuration system stored in JSON format at `~/.config/avail/config.json`. This stores:

- `default_timezone`: The default timezone to use (EST or PST)
- `quiet_mode`: Whether to suppress error messages and notifications (default: true)

Configuration is loaded at startup and persists between runs. The `-toggle` and `-q` flags modify this configuration file.

### Credential Storage

API credentials and tokens are stored in the `~/.config/avail/` directory:
- `google_credentials.json`: Your Google API credentials
- `google_token.pickle`: Cached Google authentication token
- `outlook_credentials.json`: Your Microsoft API credentials
- `outlook_token.pickle`: Cached Microsoft authentication token

### Calendar Integration

The tool integrates with two calendar systems:

1. **Google Calendar API**:
   - Uses OAuth2 authentication
   - Fetches all calendars associated with your Google account
   - Reads events from each calendar within the specified date range

2. **Microsoft Outlook/Office 365 API**:
   - Uses OAuth2 authentication
   - Accesses your default Office 365 calendar
   - Reads events including recurring events

### Availability Calculation Process

The availability checker works as follows:

1. **Fetch Busy Slots**:
   - Retrieves events from Google Calendar
   - Retrieves events from Outlook Calendar
   - Combines all events into a unified list of "busy" time slots

2. **Merge Overlapping Slots**:
   - Sorts all busy slots by start time
   - Merges any overlapping busy periods to avoid duplicates

3. **Generate Available Slots**:
   - Creates a list of all possible time slots in 15-minute intervals
   - For professional mode, limits to 9AM-5PM and excludes weekends
   - Removes any slots that overlap with busy periods
   - Merges adjacent available slots into continuous blocks

4. **Format Output**:
   - Groups available slots by day
   - Formats dates based on the range (< 7 days, same month, cross-month)
   - Adds ordinal suffixes (1st, 2nd, 3rd) for dates when appropriate

### Time Block Intervals

The tool uses a 15-minute time block interval for slot calculations. This can be modified by changing the `TIME_BLOCK_INTERVAL` constant in the code.

### Clipboard Integration

Results are automatically copied to the clipboard using the `pyperclip` library, allowing you to easily paste your availability into emails or messages.

### Error Handling

The tool has comprehensive error handling for:
- Missing credential files
- API authentication failures
- Event retrieval failures
- Timezone conversion issues

In quiet mode (default), these errors are suppressed to provide clean output.

### Performance Optimization

The tool is optimized for performance in several ways:

1. **Asynchronous API Calls**:
   - Calendar API requests run in parallel using async/await
   - Multiple calendars are fetched concurrently
   - Google and Outlook calendars are queried simultaneously

2. **Response Caching**:
   - API responses are cached locally (enabled by default)
   - Default cache expiration is 5 minutes (configurable)
   - Cached responses bypass network requests entirely
   - Cache can be cleared manually with `--clear-cache`

3. **Calendar Service Selection**:
   - Selectively enable only the calendar services you use
   - Each disabled service provides significant performance gains

4. **Lazy Loading**:
   - Calendar services are only initialized when actually needed
   - Service clients are instantiated only when first accessed

5. **Error Recovery**:
   - Better error handling with less waiting for timeouts
   - Graceful fallback when API services are unavailable

For optimal performance:

```
# Enable caching with a longer timeout (15 minutes)
avail --cache --cache-time 900

# Use only the calendar service you primarily use
avail --no-outlook  # If you mainly use Google Calendar
avail --no-google   # If you mainly use Outlook

# Clear cache if you need fresh data
avail --clear-cache
```

These optimizations can reduce execution time by up to 80% compared to the original implementation, especially when using caching and disabling unused calendar services.

## First Run

On the first run, you'll be prompted to authorize the application to access your calendars:

1. For Google Calendar, a browser window will open asking you to sign in and grant permissions
2. For Outlook, you'll be prompted to sign in via a browser window

After successful authentication, tokens will be saved locally so you won't need to authenticate again unless the tokens expire.

## Installation Note

If you've installed this tool using pyenv, you can set up an alias in your `~/.zshrc` file:

```
alias avail="~/.pyenv/versions/availability-checker/bin/avail"
```

After adding the alias, remember to run `source ~/.zshrc` or restart your terminal to apply the changes.
