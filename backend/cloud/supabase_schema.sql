create extension if not exists pgcrypto;

create table if not exists public.products (
  id bigint primary key,
  registration_number text unique,
  product_name text,
  generic_name text,
  active_ingredient text,
  strength text,
  dosage_form_id bigint,
  route_id bigint,
  category_id bigint,
  atc_code text,
  description text,
  pack_size text,
  composition text,
  approval_date text,
  expiry_date text,
  status text,
  applicant_id bigint,
  manufacturer_id bigint,
  source_last_updated text,
  synced_at text,
  created_at text,
  updated_at text
);

create table if not exists public.manufacturers (
  id bigint primary key,
  nafdac_manufacturer_id text,
  manufacturer_name text unique,
  country text,
  address text,
  created_at text,
  updated_at text
);

create table if not exists public.applicants (
  id bigint primary key,
  nafdac_applicant_id text,
  applicant_name text unique,
  address text,
  created_at text,
  updated_at text
);

create table if not exists public.renewal_alerts (
  id bigint primary key,
  product_id bigint,
  expiry_date text,
  days_remaining integer,
  alert_level text,
  created_at text,
  updated_at text
);

create table if not exists public.opportunities (
  id bigint primary key,
  product_id bigint,
  opportunity_type text,
  title text,
  description text,
  opportunity_status text,
  created_at text,
  updated_at text
);

create table if not exists public.sync_history (
  id bigint primary key,
  started_at text,
  finished_at text,
  status text,
  products_added integer,
  products_updated integer,
  products_removed integer,
  duration_seconds integer,
  error_message text
);
