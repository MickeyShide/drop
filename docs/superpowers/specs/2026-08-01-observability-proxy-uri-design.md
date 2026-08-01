# Observability proxy routing fix

## Problem

Drop connects to the shared `shide-observability` Docker network, but its nginx
routing does not match the HTTP contracts configured by that stack.

Prometheus is started with `--web.external-url=/prometheus/` and
`--web.route-prefix=/`. Public links therefore use the `/prometheus` prefix,
while the Prometheus server expects internal requests such as `/api/v1/query`.
Forwarding the public URI unchanged returns `404`; replacing every URI with `/`
creates a redirect loop back to `/prometheus/query`.

Grafana is configured with `GF_SERVER_ROOT_URL=https://grafana.shide.world` and
is published separately on port 3001 for the host-level reverse proxy. Serving
that same instance below `/grafana/` on the Drop domain is incompatible with its
root URL and asset paths.

## Reference implementation

FlashMarket joins the same external Docker network. Its gateway dynamically
resolves `shide-prometheus`, strips `/prometheus/` with an nginx rewrite, and
passes the remaining URI to Prometheus. It does not proxy Grafana; users access
the shared instance at `https://grafana.shide.world`.

## Design

Drop will follow the FlashMarket routing model:

- Keep the request-time Docker DNS resolver and variable-based Prometheus
  upstream.
- Redirect only the exact `/prometheus` path to `/prometheus/`. Return a
  relative `Location` value so the inner nginx does not incorrectly advertise
  HTTP when TLS terminates at the outer proxy.
- In `/prometheus/`, rewrite the public URI by removing `/prometheus` before
  proxying. The query string remains intact.
- Remove the `/grafana` and `/grafana/` proxy locations.
- Point the frontend Grafana navigation link directly to
  `https://grafana.shide.world`.
- Update project documentation that currently describes Grafana as a Drop
  subpath proxy.

## Alternatives considered

- Reconfigure shared Prometheus to use `/prometheus` as its route prefix. This
  changes shared infrastructure and is unnecessary because FlashMarket already
  demonstrates the intended integration contract.
- Reconfigure Grafana for `/grafana/`. One Grafana instance cannot use both the
  dedicated `grafana.shide.world` root URL and a Drop-specific subpath as its
  canonical root.
- Rewrite Grafana HTML and response headers in nginx. This is fragile and still
  conflicts with Grafana-generated URLs.

## Verification

- Validate the repository nginx configuration with a real nginx container.
- Use mock upstream containers to verify that
  `/prometheus/api/v1/query?query=up` reaches the upstream as
  `/api/v1/query?query=up`.
- Verify that only exact `/prometheus` receives the canonical slash redirect and
  that its `Location` header is relative.
- Verify there is no Drop `/grafana` proxy and the frontend link targets
  `https://grafana.shide.world`.
- Run the complete project test suite with the documented environment.
- After deployment, verify the live Prometheus instant/range query APIs and the
  shared Grafana health endpoint.

## Scope

Runtime changes are limited to Drop nginx routing and the frontend Grafana link.
The shared observability stack, metric collection, dashboards, and application
APIs remain unchanged.
