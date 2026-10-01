-- Chay 1 lan khi volume Postgres duoc khoi tao lan dau.
-- DB rieng cho pytest (cung container voi DB dev). Neu volume da ton tai tu truoc,
-- tao tay: docker compose exec postgres psql -U adpp -c "CREATE DATABASE ai_generation_test;"
CREATE DATABASE ai_generation_test;
