import psycopg
from psycopg.rows import dict_row

from app.core.config import settings


BUSINESSES = [
    {
        "name": "Local Vegan Bakery",
        "category": "restaurant",
        "description": "Approved local bakery with festival coupons.",
        "latitude": 37.5259,
        "longitude": 126.9352,
        "is_sponsored": False,
        "accessible": True,
        "esg_participating": True,
        "coupon_available": True,
    },
    {
        "name": "Garden Cafe",
        "category": "cafe",
        "description": "Accessible sponsored cafe near the main area.",
        "latitude": 37.5272,
        "longitude": 126.9341,
        "is_sponsored": True,
        "accessible": True,
        "esg_participating": False,
        "coupon_available": True,
    },
    {
        "name": "Green Goods Market",
        "category": "market",
        "description": "Local ESG goods market for festival visitors.",
        "latitude": 37.5266,
        "longitude": 126.9360,
        "is_sponsored": False,
        "accessible": True,
        "esg_participating": True,
        "coupon_available": False,
    },
]


def main() -> None:
    if not settings.database_url:
        raise RuntimeError("DATABASE_URL is required.")

    with psycopg.connect(settings.database_url, row_factory=dict_row, prepare_threshold=None) as connection:
        festival = connection.execute(
            "SELECT id FROM festivals WHERE code = %s LIMIT 1",
            ("EST34-2026",),
        ).fetchone()
        if not festival:
            raise RuntimeError("Festival EST34-2026 was not found.")

        area = connection.execute(
            """
            SELECT id
            FROM festival_areas
            WHERE festival_id = %s
            ORDER BY created_at, id
            LIMIT 1
            """,
            (festival["id"],),
        ).fetchone()

        for business in BUSINESSES:
            connection.execute(
                """
                INSERT INTO participating_businesses(
                  festival_id, area_id, name, category, description, latitude, longitude,
                  operating_status, participation_status, is_sponsored, accessible,
                  esg_participating, coupon_available, updated_at
                )
                VALUES (
                  %s, %s, %s, %s, %s, %s, %s,
                  'OPEN', 'APPROVED', %s, %s, %s, %s, now()
                )
                ON CONFLICT (festival_id, name)
                DO UPDATE SET
                  area_id = EXCLUDED.area_id,
                  category = EXCLUDED.category,
                  description = EXCLUDED.description,
                  latitude = EXCLUDED.latitude,
                  longitude = EXCLUDED.longitude,
                  operating_status = EXCLUDED.operating_status,
                  participation_status = EXCLUDED.participation_status,
                  is_sponsored = EXCLUDED.is_sponsored,
                  accessible = EXCLUDED.accessible,
                  esg_participating = EXCLUDED.esg_participating,
                  coupon_available = EXCLUDED.coupon_available,
                  updated_at = now()
                """,
                (
                    festival["id"],
                    area["id"] if area else None,
                    business["name"],
                    business["category"],
                    business["description"],
                    business["latitude"],
                    business["longitude"],
                    business["is_sponsored"],
                    business["accessible"],
                    business["esg_participating"],
                    business["coupon_available"],
                ),
            )

        count = connection.execute(
            """
            SELECT count(*)::int AS count
            FROM participating_businesses
            WHERE festival_id = %s
              AND name = ANY(%s::text[])
            """,
            (festival["id"], [business["name"] for business in BUSINESSES]),
        ).fetchone()["count"]
        print(f"seeded participating businesses: {count}")


if __name__ == "__main__":
    main()
