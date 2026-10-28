#!/bin/bash
set -uo pipefail

reminder_exit=0
outbox_exit=0
scan_exit=0
renewal_exit=0
health_enqueue_exit=0
health_process_exit=0
python manage.py enqueue_appointment_reminders || reminder_exit=$?
python manage.py process_communication_outbox || outbox_exit=$?
python manage.py process_appointment_exception_scans || scan_exit=$?
python manage.py process_google_calendar_channel_expiry_renewal || renewal_exit=$?
python manage.py enqueue_health_freshness_checks || health_enqueue_exit=$?
python manage.py process_health_jobs --limit 50 || health_process_exit=$?

exit_code=0
for command_exit in "$reminder_exit" "$outbox_exit" "$scan_exit" "$renewal_exit" \
                    "$health_enqueue_exit" "$health_process_exit"; do
  if [ "$command_exit" -gt "$exit_code" ]; then
    exit_code=$command_exit
  fi
done
exit "$exit_code"
