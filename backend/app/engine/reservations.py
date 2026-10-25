"""Read committed running reservations; JobStore controls their lifecycle."""
from __future__ import annotations

from app.api.schemas import Reservation
from app.database import Database


class ReservationStore:
    def __init__(self, database: Database):
        self.database = database

    def list(self) -> list[Reservation]:
        with self.database.transaction() as connection:
            return [Reservation.model_validate_json(row["payload"]) for row in
                    connection.execute("SELECT payload FROM reservations ORDER BY job_id")]

    def overlapping(self, start_slot: int, end_slot: int) -> list[Reservation]:
        if start_slot < 0 or end_slot <= start_slot:
            raise ValueError("Expected a nonempty half-open slot window")
        return [row for row in self.list()
                if row.start_slot < end_slot and start_slot < row.end_slot]
