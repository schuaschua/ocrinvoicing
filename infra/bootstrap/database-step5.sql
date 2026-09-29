-- AD-17 step 5 / AD-11: database logins, ownership and CONNECT rules for one
-- environment. Run by database-step5.sh as the server's Entra admin, connected to
-- the `postgres` database. Idempotent.
--
-- psql variables (all required, set with -v by the script):
--   env_db          this environment's database (invoicing_dev | invoicing_prod)
--   other_db        the other environment's database
--   pipeline_login  the environment's pipeline identity (UAMI name)
--   staff_login     the environment's staff-api identity (UAMI name)
--   accounts_login  the environment's accounts-sim identity (UAMI name)
--   deploy_login    the environment's deploy identity (UAMI name)
--   dj_login        Dj's user (UPN), for the supplier load script
-- supplier-api has no database login (AD-11). Schema grants are Alembic migrations.
-- It ends connected to env_db, where it creates pgcrypto (Story 1.6).

\set ON_ERROR_STOP on

-- Entra principals, created once per server (pgaadauth_create_principal(name, isAdmin, isMfa)).
SELECT pgaadauth_create_principal(:'pipeline_login', false, false)
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :'pipeline_login');
SELECT pgaadauth_create_principal(:'staff_login', false, false)
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :'staff_login');
SELECT pgaadauth_create_principal(:'accounts_login', false, false)
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :'accounts_login');
SELECT pgaadauth_create_principal(:'deploy_login', false, false)
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :'deploy_login');
SELECT pgaadauth_create_principal(:'dj_login', false, false)
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :'dj_login');

-- The deploy identity owns the environment database and runs the migrations.
-- ALTER ... OWNER needs the admin to be able to SET ROLE to the new owner, so the
-- membership is granted for the change and revoked straight after, in one
-- transaction so a failed ALTER never leaves the admin a member.
BEGIN;
GRANT :"deploy_login" TO CURRENT_USER;
ALTER DATABASE :"env_db" OWNER TO :"deploy_login";
REVOKE :"deploy_login" FROM CURRENT_USER;
COMMIT;

-- Nobody connects by default. Both databases are closed on every run, so running
-- one environment first never leaves the other open to it.
REVOKE CONNECT, TEMPORARY ON DATABASE :"env_db" FROM PUBLIC;
REVOKE CONNECT, TEMPORARY ON DATABASE :"other_db" FROM PUBLIC;

-- Only this environment's logins may connect to this environment's database.
GRANT CONNECT ON DATABASE :"env_db"
  TO :"pipeline_login", :"staff_login", :"accounts_login", :"deploy_login", :"dj_login";

-- Story 1.6 / AD-11: pgcrypto (pgp_pub_encrypt for bank details), created as the
-- admin because only azure_pg_admin may create an extension on Azure; Terraform
-- allow-lists it (azure.extensions). Migration 0004's IF NOT EXISTS is then a no-op.
\connect :env_db
CREATE EXTENSION IF NOT EXISTS pgcrypto;
