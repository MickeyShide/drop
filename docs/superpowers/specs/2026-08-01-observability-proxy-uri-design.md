# Observability proxy URI fix

## Problem

The nginx upstreams for Prometheus and Grafana are stored in variables so that
Docker DNS is resolved at request time. Their values currently end in `/`.
With a variable-based `proxy_pass`, that slash is treated as an explicit URI,
so every incoming subpath is replaced with `/` before proxying.

For Prometheus this creates a redirect loop: `/prometheus/query` is proxied as
`/`, Prometheus redirects to `/prometheus/query`, and the next request is again
proxied as `/`. For Grafana, asset and API requests incorrectly return the root
HTML document.

## Design

Keep the existing Docker DNS resolver and variable-based upstreams, but remove
the trailing slash from both backend URL values. A `proxy_pass` containing only
the scheme and authority preserves the complete incoming request URI, including
the `/prometheus` or `/grafana` prefix expected by the services' configured
external URLs.

The canonical redirects from `/prometheus` to `/prometheus/` and from
`/grafana` to `/grafana/` use exact-match locations, so similarly prefixed
routes are not redirected into either service.

## Alternatives considered

- Rewrite and strip each prefix before proxying. This conflicts with the
  services' existing subpath configuration and adds unnecessary rewrite rules.
- Return to static upstream names. This restores nginx startup coupling to the
  external observability containers and loses the reason dynamic resolution was
  introduced.

## Verification

- Validate nginx syntax with the repository config mounted into an nginx
  container when Docker is available.
- Assert that both variable values contain an authority only and no URI suffix.
- Assert that only the exact extensionless service paths receive canonical
  slash redirects.
- After deployment, verify that `/prometheus/query`,
  `/prometheus/api/v1/query?query=up`, and `/prometheus/-/healthy` no longer
  redirect to `/prometheus/query`.
- Verify that a nested Grafana asset path returns its actual asset rather than
  the root HTML page.

## Scope

Only `nginx/nginx.conf` changes at runtime. No application, metrics collection,
authentication, or public-route behavior is otherwise changed.
