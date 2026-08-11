from datetime import datetime

from app.repositories.festival_repository import FestivalRepository
from app.schemas.festival import (
    Coupon,
    Facility,
    Festival,
    FestivalOverview,
    Notice,
    Program,
    Store,
)


class FestivalService:
    def __init__(self) -> None:
        self.repo = FestivalRepository()

    def get_overview(self) -> FestivalOverview:
        today = datetime.now().date()
        programs = [Program(**item) for item in self.repo.list_programs()]
        today_programs = [item for item in programs if item.start_time.date() == today]
        if not today_programs:
            today_programs = programs

        stores = [Store(**item) for item in self.repo.list_stores() if item["coupon_available"]]
        return FestivalOverview(
            festival=Festival(**self.repo.get_festival()),
            notices=[Notice(**item) for item in self.repo.list_notices()],
            today_programs=today_programs,
            recommended_stores=stores,
        )

    def list_programs(self) -> list[Program]:
        return [Program(**item) for item in self.repo.list_programs()]

    def list_facilities(self) -> list[Facility]:
        return [Facility(**item) for item in self.repo.list_facilities()]

    def list_stores(self) -> list[Store]:
        return [Store(**item) for item in self.repo.list_stores()]

    def list_coupons(self) -> list[Coupon]:
        return [Coupon(**item) for item in self.repo.list_coupons()]

    def list_notices(self) -> list[Notice]:
        return [Notice(**item) for item in self.repo.list_notices()]
