CREATE UNIQUE INDEX IF NOT EXISTS participating_businesses_festival_name_unique
  ON participating_businesses(festival_id, name);
