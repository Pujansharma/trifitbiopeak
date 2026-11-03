#!/bin/bash
set -uo pipefail

# Initialize exit codes
reminder_exit=0
outbox_exit=0
scan_exit=0
renewal_exit=0

# Health processing (Phase 1 ROOK integration)
health_enqueue_exit=0
health_process_exit=0

# Protocol and AI processing (develop branch)
protocol_exit=0
ai_exit=0

# Existing scheduled jobs
python manage.py enqueue_appointment_reminders || reminder_exit=$?
python manage.py process_communication_outbox || outbox_exit=$?
python manage.py process_appointment_exception_scans || scan_exit=$?
python manage.py process_google_calendar_channel_expiry_renewal || renewal_exit=$?

# Health processing jobs
python manage.py enqueue_health_freshness_checks || health_enqueue_exit=$?
python manage.py process_health_jobs --limit 50 || health_process_exit=$?

# Protocol and AI jobs
python manage.py sweep_protocol_versions || protocol_exit=$?
python manage.py process_protocol_ai_jobs --limit 1 || ai_exit=$?

# Return the highest exit code from all commands
exit_code=0

for command_exit in \
    "$reminder_exit" \
    "$outbox_exit" \
    "$scan_exit" \
    "$renewal_exit" \
    "$health_enqueue_exit" \
    "$health_process_exit" \
    "$protocol_exit" \
    "$ai_exit"
do
    if [ "$command_exit" -gt "$exit_code" ]; then
        exit_code=$command_exit
    fi
done

exit "$exit_code"
