# KC Water Home Assistant integration

An unofficial, read-only custom integration for retrieving usage history from the Kansas City, Missouri KC Water customer portal.

## Install

### HACS custom repository

The repository is laid out as a Home Assistant custom integration (`custom_components/kcwater`) and includes `hacs.json`. In HACS, add this Git repository as an **Integration** custom repository, install **KC Water**, then restart Home Assistant. HACS compatibility metadata is included, but this repository has not been accepted into the HACS default catalog.

### Manual

Copy `custom_components/kcwater` into `<Home Assistant config>/custom_components/kcwater`, restart Home Assistant, and add **KC Water** from **Settings → Devices & services → Add integration**.

Enter the portal username/password. If login returns usable account and service records, select the desired pair.

## Sensors

The integration creates latest daily gallons and cubic feet, portal period gallons and cubic feet (using the portal's own `Total Usage` summaries), average and high daily gallons from portal summaries, and last valid reading date. Summary labels are intentionally not called calendar-month totals: the portal period semantics have not been verified. Cubic feet from daily history are converted from gallons using 7.48051948 gallons per cubic foot; the portal's `Total Usage` summary is shown as cubic feet based on the observed response convention and should be confirmed against a sanitized capture.

History ignores future-dated placeholders, deduplicates by reading date, preserves legitimate zero readings, and omits malformed values. Polling is every six hours. Authentication is attempted on setup and access tokens use the reported `expires_in` (defaulting to the observed 3600 seconds only when absent); refresh failure falls back once to password authentication.

## Known limitations and API evidence needed

No live KC Water credentials or sanitized network capture were available in this workspace. Therefore live authentication, account discovery, refresh behavior, and sensor values have **not** been verified. The implementation uses only the observed `/rest/oauth/token` and `/rest/usage/month/day` paths supplied with the starter/request; it does not invent an account endpoint.

Before relying on this integration, collect sanitized browser Network evidence for:

* The exact token request Basic-auth client identifier and secret behavior. The starter contained `webClientIdPassword` / `secret`; these remain placeholders pending evidence and are not represented as private credentials. A distributed client secret is recoverable from the integration and should be treated as public.
* A successful login response showing the account/service field names and whether `user.accounts` is complete. The config flow currently recognizes `accountNumber`/`accountNo`, and `services`/`serviceList` with `serviceId`/`serviceID`.
* A usage request and response for multiple dates, to establish the meaning of `month` (the captured `DD-MMM-YYYY` shape is retained but semantics are unknown), the returned date format, and whether data covers billing period or calendar month.
* A refresh-token request/response confirming grant format, rotation, and expiry behavior.
* Accounts with multiple meters/services, including how meter details map to service IDs.

Sanitize usernames, passwords, account/customer IDs, tokens, cookies, request authorization headers, and personally identifying response fields before reporting issues. Do not attach raw HAR files.

## Security

Credentials are stored in Home Assistant config-entry data, so protect backups. Requests use HTTPS and Home Assistant's shared aiohttp session; TLS verification remains enabled. No credentials or account IDs are written to logs or diagnostics. Entity attributes contain only normalized status and reading count. The integration performs no account changes or payment operations.

## Troubleshooting

* **Login fails:** confirm portal credentials and collect a sanitized token-request status and response shape. Never share the password or auth header.
* **Account list unavailable:** the current implementation intentionally stops rather than guessing another endpoint. Provide a sanitized login `user.accounts` shape.
* **No usage readings:** check integration availability and provide a sanitized usage response, especially `history` dates, `gallonsConsumption`, `jsonData`, and `serviceTableData`.
* **Repeated authentication prompt:** provide sanitized token status codes and whether refresh returns a rotated refresh token.

## Development

Run tests with `python -m pytest`. Test fixtures must remain synthetic and contain no real customer data.
