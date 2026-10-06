# Global Snapshot source repair 2

Follow-up to the deployed source repair 1. Changes are restricted to Global Snapshot and the existing South Africa transport workflow.

- China GDP and unemployment: official NBS release discovery and table/paragraph parsing; GDP excludes half-year cumulative growth.
- Brazil: IBGE API variables 6561 (quarterly GDP year-on-year) and 4099 (rolling three-month national unemployment).
- India: MoSPI PLFS monthly bulletin through the official PIB archive; RBI current policy repo rate, explicitly dated as an observation month.
- Argentina: INDEC homepage unemployment release with numeric entity decoding.
- Korea: actual BOK release listing endpoint and year-on-year GDP paragraph, excluding GDI and North Korea estimates.
- South Africa: national official QLFS PDF added to the existing CPI bridge workflow. Its existing 17:20 UTC daily schedule is unchanged. CPI updates are committed even if the QLFS step fails, and such a failure remains visible.
- Switzerland: quarterly ILO survey cadence applies only to Eurostat/OECD observations labelled by quarter or quarter-end month.

The installer validates fingerprints against repair 1, syntax, current KV and current live schedules. It checks the Stats SA source bridge before deploying the Worker, retains a backup, deploys once, confirms version and unchanged schedules, runs one full refresh and prints actual public health. It does not edit dashboard files or add cron triggers.

Luxembourg Q2 GDP is missing from the checked official Eurostat feed. The existing Q1 lag warning remains visible until an approved official newer observation is available; no value or period is invented.

Validation: official response fixtures for all changed direct parsers, PIB archive POST without cookies, actual BOK filtered listing, QLFS headline parser period/definition rejection, prior repair regression checks, and installer simulation preserving live schedule/KV/browser and refusing unseen source. Production QLFS PDF transport and the deployed full refresh remain for the installer to verify on the authorized GitHub runner and Cloudflare account.
