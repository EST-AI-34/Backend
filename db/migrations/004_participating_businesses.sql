CREATE TABLE IF NOT EXISTS participating_businesses (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  festival_id uuid NOT NULL REFERENCES festivals(id) ON DELETE CASCADE,
  area_id uuid REFERENCES festival_areas(id) ON DELETE SET NULL,
  name text NOT NULL,
  category text NOT NULL CHECK (category IN ('restaurant', 'cafe', 'market', 'souvenir')),
  description text NOT NULL DEFAULT '',
  latitude numeric(10,7),
  longitude numeric(10,7),
  operating_status text NOT NULL DEFAULT 'OPEN' CHECK (operating_status IN ('OPEN', 'CLOSED', 'PAUSED', 'ENDED')),
  participation_status text NOT NULL DEFAULT 'APPROVED' CHECK (participation_status IN ('PENDING', 'APPROVED', 'REJECTED', 'SUSPENDED')),
  is_sponsored boolean NOT NULL DEFAULT false,
  accessible boolean NOT NULL DEFAULT false,
  esg_participating boolean NOT NULL DEFAULT false,
  coupon_available boolean NOT NULL DEFAULT false,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CHECK (
    (latitude IS NULL AND longitude IS NULL)
    OR (
      latitude BETWEEN -90 AND 90
      AND longitude BETWEEN -180 AND 180
    )
  )
);

CREATE INDEX IF NOT EXISTS participating_businesses_recommendation_idx
  ON participating_businesses(festival_id, participation_status, operating_status, category, is_sponsored);

CREATE INDEX IF NOT EXISTS participating_businesses_area_idx
  ON participating_businesses(area_id);
