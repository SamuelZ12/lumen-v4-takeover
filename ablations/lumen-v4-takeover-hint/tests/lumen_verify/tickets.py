"""Ticket state as the verifier reads it from replayed snapshots.

``tickets/<id>`` = ``{id, title, status, assignee, steps, history}``; it changes only in an
accepted ``tickets.status_updated`` event (validator ``tickets``).
"""

TICKETS_PREFIX = "tickets/"
UPDATE_EVENT = "tickets.status_updated"
