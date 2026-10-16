#!/bin/bash
set -uo pipefail

reminder_exit=0
outbox_exit=0
scan_exit=0
renewal_exit=0
python manage.py enqueue_appointment_reminders || reminder_exit=$?
python manage.py process_communication_outbox || outbox_exit=$?
python manage.py process_appointment_exception_scans || scan_exit=$?
python manage.py process_google_calendar_channel_expiry_renewal || renewal_exit=$?

exit_code=$reminder_exit
if [ "$outbox_exit" -gt "$exit_code" ]; then
  exit_code=$outbox_exit
fi
if [ "$scan_exit" -gt "$exit_code" ]; then
  exit_code=$scan_exit
fi
if [ "$renewal_exit" -gt "$exit_code" ]; then
  exit_code=$renewal_exit
fi
exit "$exit_code"
