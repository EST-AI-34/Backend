-- 방문객 앱에 어떤 메뉴를 노출할지는 축제 단위 운영 설정이다.
-- 그동안 관리자 브라우저 localStorage에만 있어서 다른 관리자·방문객에게 반영되지 않았다.
ALTER TABLE festivals ADD COLUMN IF NOT EXISTS visitor_menus jsonb NOT NULL
  DEFAULT '{"reservation":true,"stampTour":true,"coupons":true,"nearby":true,"survey":true}';
