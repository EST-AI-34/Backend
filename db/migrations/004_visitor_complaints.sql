-- 방문객이 직접 접수한 민원은 작성자(운영자 계정)가 없다.
ALTER TABLE ops_tickets ALTER COLUMN created_by DROP NOT NULL;
