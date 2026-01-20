# Django `humanize` Template Tags

Django ships with an optional `django.contrib.humanize` application that provides a
set of template filters designed to make data appear more “human friendly.” Once the
app is added to `INSTALLED_APPS` you can load its tag library in a template with
`{% load humanize %}` and use filters such as:

- `intcomma` — formats large integers with thousands separators (e.g., `12000` →
  `12,000`).
- `intword` — expresses large numbers in words (e.g., `1000000` → `1.0 million`).
- `apnumber` — spells out numbers one through nine (e.g., `7` → `seven`).
- `naturalday` and `naturaltime` — display dates and times in a relative format such
  as “yesterday” or “4 minutes ago.”

These filters are handy when presenting prices, quantities, or timestamps in store
management dashboards and customer-facing pages so that the content is easier to scan
and understand.
