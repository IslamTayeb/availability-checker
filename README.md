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
- `DAYS`: Number of days to look ahead for availability

### Options
- `-p, --professional`: Limit to professional hours (9AM-5PM, no weekends)
- `-pst, --pst`: Use PST timezone for this query
- `-est, --est`: Use EST timezone for this query
- `-default, --set-default-timezone [EST|PST]`: Set default timezone for future use

### Examples

Check availability for the next 3 days:
```
avail 3
```

Check professional availability (9AM-5PM, no weekends) for the next week:
```
avail 7 -p
```

Check availability in PST timezone:
```
avail 5 -pst
```

Check availability in EST timezone:
```
avail 5 -est
```

Set PST as your default timezone:
```
avail 1 --set-default-timezone PST
```

## Timezone Configuration

The tool allows you to set a default timezone (EST or PST) to match your current location:

1. If you're in San Francisco: `avail 1 --set-default-timezone PST`
2. If you're in New York: `avail 1 --set-default-timezone EST`

You can always override the default for a specific query with the `-est` or `-pst` flags.

## Output Format

The tool displays available time slots in the following format:
```
Mo - 3:00 PM - 5:00 PM
Tu - 10:00 AM - 11:00 AM; 2:30 PM - 4:00 PM
```

Where:
- The day is represented by the first two letters (Mo, Tu, We, etc.)
- Multiple time slots for the same day are separated by semicolons
- The output is automatically copied to your clipboard for easy sharing

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
